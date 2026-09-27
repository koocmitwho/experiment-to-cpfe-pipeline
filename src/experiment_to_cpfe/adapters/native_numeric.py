"""Bounded numerical decoding, independent of physical interpretation."""

import math
from pathlib import Path

import h5py
import numpy as np


def reject_matlab_objects(handle):
    """Class/object payloads are native references, including through legacy HDF5 APIs."""
    numeric = {"double", "single", "int8", "uint8", "int16", "uint16", "int32",
               "uint32", "int64", "uint64", "logical", "char", "struct", "cell"}
    def check(name, item):
        cls = item.attrs.get("MATLAB_class")
        if isinstance(cls, bytes):
            cls = cls.decode("ascii", errors="replace")
        if "MCOS" in name or (cls is not None and str(cls) not in numeric):
            raise ValueError(f"MATLAB class/object requires native reference or upstream property export: {name}")
    handle.visititems(check)


def inspect_npy_header(path: Path) -> dict:
    """Inspect a full file or header fragment without allocating the array."""
    path = Path(path)
    with path.open("rb") as stream:
        version = np.lib.format.read_magic(stream)
        if version == (1, 0):
            shape, fortran, dtype = np.lib.format.read_array_header_1_0(stream)
        elif version == (2, 0):
            shape, fortran, dtype = np.lib.format.read_array_header_2_0(stream)
        else:
            raise ValueError(f"unsupported NPY header version: {version}")
        offset = stream.tell()
    if dtype.hasobject:
        raise ValueError("NPY object payload is not supported")
    required = offset + math.prod(shape) * dtype.itemsize
    return {"shape": list(shape), "dtype": dtype.str, "fortran_order": bool(fortran),
            "header_bytes": offset, "expected_file_bytes": required,
            "payload_complete": path.stat().st_size == required}


def local_hdf5_dataset(handle, location):
    """Require selected data to reside in the registered source file."""
    if not isinstance(location, str) or location not in handle or not isinstance(handle[location], h5py.Dataset):
        raise ValueError("explicit numeric HDF5 dataset path is required")
    dataset = handle[location]
    if dataset.file.id != handle.id or dataset.is_virtual or dataset.external:
        raise ValueError("external/virtual HDF5 storage requires separately registered dependency conversion")
    return dataset


def _selection(shape, declarations):
    if declarations is None:
        return tuple(slice(None) for _ in shape), tuple(shape)
    if not isinstance(declarations, (list, tuple)) or len(declarations) != len(shape):
        raise ValueError("slices must explicitly match the source rank")
    indices, selected = [], []
    for size, item in zip(shape, declarations):
        if item is None:
            indices.append(slice(None))
            selected.append(size)
        elif type(item) is int:
            if not 0 <= item < size:
                raise ValueError("slice index is outside source shape")
            indices.append(item)
        elif isinstance(item, (list, tuple)) and len(item) in (2, 3):
            start, stop = item[:2]
            step = item[2] if len(item) == 3 else 1
            if any(type(v) is not int for v in (start, stop, step)) or not (0 <= start < stop <= size and step > 0):
                raise ValueError("slice bounds must be in range with positive step; no silent clipping")
            indices.append(slice(start, stop, step))
            selected.append(len(range(start, stop, step)))
        else:
            raise ValueError("invalid explicit slice")
    return tuple(indices), tuple(selected)


def _bounded(shape, dtype, limit):
    if math.prod(shape) * np.dtype(dtype).itemsize > limit:
        raise ValueError("selected array exceeds max_bytes limit")


def read_numeric(path: Path, selector: dict) -> tuple[np.ndarray, dict]:
    """Decode selected values; nonfinite values stay present for the semantic quality gate."""
    allowed = {"format", "path", "steps", "slices", "transpose", "reshape", "reshape_order",
               "max_bytes", "max_source_bytes", "delimiter", "skiprows", "dtype", "encoding"}
    if set(selector) - allowed:
        raise ValueError(f"unknown numeric selector options: {sorted(set(selector) - allowed)}")
    path = Path(path)
    fmt = selector.get("format")
    limit = selector.get("max_bytes", 64 * 1024 * 1024)
    source_limit = selector.get("max_source_bytes", 128 * 1024 * 1024)
    if type(limit) is not int or limit <= 0 or type(source_limit) is not int or source_limit <= 0:
        raise ValueError("byte limits must be positive integers")
    source_meta = {}
    steps = selector.get("steps", [])
    if fmt != "mat5" and steps:
        raise ValueError("steps are only supported for MAT5 structs/cells")
    if fmt == "npy":
        source_meta = inspect_npy_header(path)
        if not source_meta["payload_complete"]:
            raise ValueError("incomplete NPY payload; header inspection only")
        array = np.load(path, mmap_mode="r", allow_pickle=False)
    elif fmt in {"hdf5", "h5", "mat73"}:
        with h5py.File(path, "r") as handle:
            reject_matlab_objects(handle)
            location = selector.get("path")
            dataset = local_hdf5_dataset(handle, location)
            if dataset.dtype.kind not in "biufcSU":
                raise ValueError("HDF5 object/reference/compound data requires explicit upstream normalization")
            index, shape = _selection(dataset.shape, selector.get("slices"))
            _bounded(shape, dataset.dtype, limit)
            source_meta.update(source_shape=list(dataset.shape), source_dtype=dataset.dtype.str)
            array = np.asarray(dataset[index])
    elif fmt == "mat5":
        if path.stat().st_size > source_limit:
            raise ValueError("MAT5 source exceeds max_source_bytes; selected variables are decoded in memory")
        try:
            from scipy.io import loadmat, whosmat
            from scipy.io.matlab import MatlabObject, MatlabOpaque
        except ImportError as exc:
            raise ValueError("MAT5 requires the native extra (scipy)") from exc
        root = selector.get("path")
        inventory = {name: (shape, kind) for name, shape, kind in whosmat(path)}
        if root not in inventory:
            raise ValueError("explicit MAT5 variable path is required")
        shape, kind = inventory[root]
        if kind in {"object", "function", "opaque"}:
            raise ValueError("MATLAB class/object requires a native reference")
        # Numeric top-level arrays can be budgeted before decompression. Struct/cell
        # contents still require decoding the selected variable, bounded by file size.
        if kind not in {"struct", "cell", "char"}:
            _bounded(shape, np.dtype("complex128"), source_limit)
        array = loadmat(path, variable_names=[root], squeeze_me=False, struct_as_record=True)[root]
        for step in steps:
            if isinstance(array, (MatlabObject, MatlabOpaque)):
                raise ValueError("MATLAB object storage is not numeric data")
            if not isinstance(step, dict) or len(step) != 1:
                raise ValueError("each MAT step must name exactly one field or index")
            if "field" in step:
                if array.dtype.names is None or step["field"] not in array.dtype.names:
                    raise ValueError("MAT struct field is missing")
                array = array[step["field"]]
            elif "index" in step:
                index = step["index"]
                if not isinstance(index, (list, tuple)) or len(index) != array.ndim or any(type(i) is not int or not 0 <= i < size for i, size in zip(index, array.shape)):
                    raise ValueError("MAT index must explicitly address every dimension within range")
                array = array[tuple(index)]
            else:
                raise ValueError("unknown MAT selector step")
        if isinstance(array, (MatlabObject, MatlabOpaque)):
            raise ValueError("MATLAB object storage is not numeric data")
        array = np.asarray(array)
    elif fmt in {"csv", "txt"}:
        if path.stat().st_size > source_limit:
            raise ValueError("text source exceeds max_source_bytes")
        array = np.loadtxt(path, delimiter=selector.get("delimiter"), skiprows=selector.get("skiprows", 0),
                           dtype=selector.get("dtype", "float64"), encoding=selector.get("encoding", "utf-8"), ndmin=2)
    else:
        raise ValueError(f"unsupported native numeric format: {fmt}")
    if array.dtype.kind not in "biufcSU" or array.dtype.fields:
        raise ValueError("selected value is not a plain numeric/string array; select struct/cell contents explicitly")
    if fmt not in {"h5", "hdf5", "mat73"}:
        source_meta.update(source_shape=list(array.shape), source_dtype=array.dtype.str)
        index, shape = _selection(array.shape, selector.get("slices"))
        _bounded(shape, array.dtype, limit)
        array = np.array(array[index], copy=True)
    if "transpose" in selector:
        permutation = selector["transpose"]
        if not isinstance(permutation, (list, tuple)) or sorted(permutation) != list(range(array.ndim)):
            raise ValueError("transpose must be a permutation of all axes")
        array = array.transpose(permutation)
    if "reshape" in selector:
        shape = selector["reshape"]
        order = selector.get("reshape_order")
        if order not in {"C", "F"} or not isinstance(shape, (list, tuple)) or any(type(n) is not int or n <= 0 for n in shape) or math.prod(shape) != array.size:
            raise ValueError("reshape requires explicit positive shape and C/F reshape_order")
        array = array.reshape(shape, order=order)
    elif "reshape_order" in selector:
        raise ValueError("reshape_order requires a reshape")
    return array, {**source_meta, "selector": selector, "shape": list(array.shape), "dtype": array.dtype.str,
                   "losses": ["only explicitly selected values are retained; native headers/layout remain in source"]}
