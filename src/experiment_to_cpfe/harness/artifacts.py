"""Local artifact integrity, atomic records, and deliberately bounded views.

The caller owns authorization and dataset registration. This module does not
accept arbitrary executables, unpickle data, follow container links, or infer
that a file's presence proves scientific acceptance.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import mimetypes
import os
from pathlib import Path
import re
import stat
import tempfile
import threading


MAX_ROWS = 500
MAX_BYTES = 256 * 1024
_JSON_INPUT_BYTES = 4 * 1024 * 1024
_TEXT_SUFFIXES = {'.txt', '.log', '.md', '.json', '.csv', '.yaml', '.yml'}
_PARTIAL_SUFFIXES = {'.tmp', '.partial', '.part', '.incomplete'}
_ATOMIC_THREAD_LOCK = threading.Lock()


def _linked(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, 'st_file_attributes', 0)
        & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400))


def atomic_json(path: Path, value: dict) -> None:
    """Publish a complete JSON record, preserving the old record on short writes."""
    if not isinstance(value, dict):
        raise ValueError('JSON record must be an object')
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True,
                          indent=2, allow_nan=False) + '\n').encode('utf-8')
    # OS replacement is atomic, but Windows may reject concurrent replacements.
    # Cross-process execution ownership remains the harness store's responsibility.
    with _ATOMIC_THREAD_LOCK:
        _publish_record(Path(path), payload)


def _publish_record(path, payload):
    path = Path(path)
    if path.exists() and _linked(path):
        raise ValueError('linked record destination is unsupported')
    descriptor, temporary = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            if stream.write(payload) != len(payload):
                raise OSError('incomplete JSON record write')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def digest_file(path) -> str:
    """SHA-256 without materializing large ODB/HDF5 payloads."""
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_within(root, path, *, must_exist=True) -> Path:
    """Resolve a regular file/directory without crossing links or the given root."""
    if not isinstance(root, (str, Path)) or not isinstance(path, (str, Path)):
        raise ValueError('root and path must be filesystem path strings')
    if not str(root).strip() or not str(path).strip() or '\x00' in str(path):
        raise ValueError('empty or invalid path')
    root = Path(root).absolute()
    if not root.is_dir() or _linked(root):
        raise ValueError('root must be an existing ordinary directory')
    root = root.resolve()
    supplied = Path(path)
    if '..' in supplied.parts or any(':' in p for p in supplied.parts if p != supplied.anchor):
        raise ValueError('path traversal or alternate streams are unsupported')
    candidate = supplied if supplied.is_absolute() else root / supplied
    candidate = candidate.absolute()
    try:
        parts = candidate.relative_to(root).parts
    except ValueError:
        raise ValueError('path lies outside the authorized root') from None
    current = root
    for part in parts:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            if must_exist:
                raise ValueError('artifact path does not exist') from None
            break
        if _linked(current):
            raise ValueError('linked or reparse paths are unsupported')
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise ValueError('special filesystem objects are unsupported')
    resolved = candidate.resolve(strict=must_exist)
    if not resolved.is_relative_to(root):
        raise ValueError('resolved path lies outside the authorized root')
    return resolved


def _media_type(path):
    known = {'.csv': 'text/csv', '.json': 'application/json', '.h5': 'application/x-hdf5',
             '.hdf5': 'application/x-hdf5', '.md': 'text/markdown', '.log': 'text/plain'}
    return known.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or 'application/octet-stream'


def inventory(root: Path) -> list[dict]:
    """Record completed regular files only; never register links or temporary files."""
    root = resolve_within(root, root)
    result, pending = [], [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                path = resolve_within(root, Path(entry.path))
                if path.suffix.lower() in _PARTIAL_SUFFIXES or path.name.endswith('~'):
                    raise ValueError('partial artifact cannot be registered')
                if path.is_dir():
                    pending.append(path)
                else:
                    before = path.stat()
                    digest = digest_file(path)
                    after = path.stat()
                    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                        raise ValueError('artifact changed during registration')
                    result.append(dict(relative_path=path.relative_to(root).as_posix(), sha256=digest,
                                       size_bytes=after.st_size, media_type=_media_type(path)))
    return sorted(result, key=lambda item: item['relative_path'])


def _page(items, offset, limit, *, total=None, more=False, **extra):
    return dict(items=items, offset=offset, limit=limit, total=total,
                next_offset=offset + len(items) if more else None, **extra)


def _bounded(result):
    try:
        payload = json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (ValueError, TypeError):
        raise ValueError('artifact view contains unsupported values') from None
    if len(payload) > MAX_BYTES:
        raise ValueError('artifact view exceeds the response byte limit')
    return result


def _json_view(path, offset, limit):
    with path.open('rb') as stream:
        payload = stream.read(_JSON_INPUT_BYTES + 1)
    if len(payload) > _JSON_INPUT_BYTES:
        raise ValueError('JSON artifact exceeds the bounded parser input limit')
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON object key')
            result[key] = value
        return result
    try:
        data = json.loads(payload.decode('utf-8-sig'), object_pairs_hook=unique_object)
    except (UnicodeError, ValueError, RecursionError):
        raise ValueError('invalid JSON artifact') from None
    if isinstance(data, list):
        items = data[offset:offset + limit]
        return _page(items, offset, limit, total=len(data), more=offset + len(items) < len(data))
    if not isinstance(data, dict) or offset:
        raise ValueError('JSON view requires a paged list or an object at offset zero')
    return {'data': data}


class _BoundedLines:
    def __init__(self, stream):
        self.stream = stream
        self.consumed = 0

    def __iter__(self):
        return self

    def __next__(self):
        line = self.stream.readline(MAX_BYTES + 1)
        if not line:
            raise StopIteration
        self.consumed += len(line)
        if self.consumed > MAX_BYTES:
            raise ValueError('text or CSV record exceeds the byte limit')
        try:
            decoded = line.decode('utf-8-sig')
        except UnicodeError:
            raise ValueError('artifact text must use UTF-8') from None
        if '\x00' in decoded:
            raise ValueError('binary artifact cannot be viewed as text')
        return decoded


def _text_view(path, view, offset, limit, columns):
    if path.suffix.lower() not in _TEXT_SUFFIXES or (view == 'csv' and path.suffix.lower() != '.csv'):
        raise ValueError('artifact type does not support the requested text view')
    with path.open('rb') as stream:
        lines = _BoundedLines(stream)
        iterator = csv.reader(lines, strict=True) if view == 'csv' else lines
        selected = None
        if view == 'csv':
            try:
                header = next(iterator)
            except StopIteration:
                raise ValueError('CSV header is absent') from None
            if not header or len(set(header)) != len(header):
                raise ValueError('CSV header is ambiguous')
            selected = header if columns is None else columns
            if (not isinstance(selected, list) or not selected
                    or any(not isinstance(name, str) or name not in header for name in selected)
                    or len(set(selected)) != len(selected)):
                raise ValueError('CSV columns must be unique declared header names')
        items, more = [], False
        for index in range(offset + limit + 1):
            lines.consumed = 0
            try:
                row = next(iterator)
            except StopIteration:
                break
            except csv.Error:
                raise ValueError('invalid or oversized CSV record') from None
            if view == 'csv':
                if len(row) != len(header):
                    raise ValueError('CSV row width disagrees with its header')
                row = {name: row[header.index(name)] for name in selected}
            else:
                row = row.rstrip('\r\n')
            if index < offset:
                continue
            if len(items) == limit:
                more = True
                break
            items.append(row)
            _bounded({'items': items})
    return _page(items, offset, limit, more=more, **({'columns': selected} if selected else {}))


def _scan_hdf5(h5):
    """Inspect links and storage declarations before reading any dataset values."""
    import h5py
    seen, pending, count = set(), [h5], 0
    while pending:
        group = pending.pop()
        address = h5py.h5o.get_info(group.id).addr
        if address in seen:
            continue
        seen.add(address)
        for key in group:
            count += 1
            if count > 10000:
                raise ValueError('HDF5 metadata scan limit exceeded')
            link = group.get(key, getlink=True)
            if not isinstance(link, h5py.HardLink):
                raise ValueError('HDF5 external and soft links are unsupported')
            obj = group[key]
            if isinstance(obj, h5py.Group):
                pending.append(obj)
            elif isinstance(obj, h5py.Dataset):
                if obj.is_virtual or obj.external:
                    raise ValueError('HDF5 virtual or external storage is unsupported')


def _hdf5_view(path, record, dataset, offset, limit):
    import h5py
    import numpy as np
    allowed = record.get('datasets', [])
    if (not isinstance(allowed, list) or not isinstance(dataset, str) or not dataset
            or dataset not in allowed or any(p in {'..', '.'} for p in dataset.split('/'))
            or '\\' in dataset or ':' in dataset):
        raise ValueError('HDF5 dataset is not registered for access')
    with h5py.File(path, 'r') as h5:
        _scan_hdf5(h5)
        obj = h5.get(dataset)
        if not isinstance(obj, h5py.Dataset) or obj.dtype.kind not in 'biuf' or obj.shape is None:
            raise ValueError('HDF5 view requires a registered numeric dataset')
        shape = obj.shape
        total = shape[0] if shape else 1
        count = max(0, min(limit, total - offset))
        elements = count * math.prod(shape[1:])
        if elements * max(32, obj.dtype.itemsize) > MAX_BYTES:
            raise ValueError('HDF5 slice exceeds the bounded read limit')
        values = (obj[offset:offset + count] if shape else np.asarray([obj[()]]) if count else np.asarray([]))
        if not np.isfinite(values).all():
            raise ValueError('HDF5 view contains nonfinite values')
        return _page(values.tolist(), offset, limit, total=total, more=offset + count < total,
                     dataset=dataset, shape=list(shape), dtype=str(obj.dtype))


def read_view(root: Path, record: dict, *, view='summary', offset=0, limit=100,
              columns=None, dataset=None) -> dict:
    """Read a registered file through metadata or bounded structured projections."""
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= MAX_ROWS:
        raise ValueError('offset and row limit are invalid')
    if not isinstance(view, str) or view not in {'summary', 'json', 'text', 'csv', 'hdf5'}:
        raise ValueError('unsupported artifact view')
    if not isinstance(record, dict) or not isinstance(record.get('relative_path'), str):
        raise ValueError('artifact record is invalid')
    if Path(record['relative_path']).is_absolute():
        raise ValueError('artifact record must contain a relative path')
    if (not isinstance(record.get('sha256'), str) or not re.fullmatch('[a-f0-9]{64}', record['sha256'])
            or type(record.get('size_bytes')) is not int or record['size_bytes'] < 0
            or not isinstance(record.get('media_type'), str)):
        raise ValueError('artifact integrity declaration is invalid')
    path = resolve_within(root, record['relative_path'])
    if not path.is_file():
        raise ValueError('artifact record must identify a regular file')
    def verify():
        resolve_within(root, record['relative_path'])
        if path.stat().st_size != record['size_bytes'] or digest_file(path) != record['sha256']:
            raise ValueError('artifact integrity mismatch')
    verify()
    if view == 'summary':
        result = {key: record[key] for key in ('relative_path', 'sha256', 'size_bytes', 'media_type')}
    elif view == 'json':
        if path.suffix.lower() != '.json':
            raise ValueError('artifact type does not support JSON view')
        result = _json_view(path, offset, limit)
    elif view in {'text', 'csv'}:
        result = _text_view(path, view, offset, limit, columns)
    else:
        if path.suffix.lower() not in {'.h5', '.hdf5'}:
            raise ValueError('artifact type does not support HDF5 view')
        result = _hdf5_view(path, record, dataset, offset, limit)
    verify()
    return _bounded(dict(result, view=view))
