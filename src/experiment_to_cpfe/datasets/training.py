"""Build an identity-aligned named regression collection from canonical HDF5."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path

import numpy as np

from experiment_to_cpfe.datasets.package import _load_source
from experiment_to_cpfe.assets.registry import array_payload_sha256
from experiment_to_cpfe.datasets.training_columns import select_column
from experiment_to_cpfe.datasets.training_config import TrainingDatasetConfig
from experiment_to_cpfe.datasets.training_sources import TargetSourceIndex, register_target_sources
from experiment_to_cpfe.learning.data_contract import TRAINING_ARRAYS, TRAINING_FORMAT, VECTOR_TRAINING_FORMAT, validate_group_splits
from experiment_to_cpfe.provenance.hashing import sha256_file


@dataclass
class TrainingDataset:
    features: np.ndarray
    targets: np.ndarray
    groups: np.ndarray
    splits: np.ndarray
    sample_ids: np.ndarray
    row_ids: np.ndarray
    metadata: dict


def build_training_dataset(config, *, base_dir: Path) -> TrainingDataset:
    """Read explicit inputs; no file creation, Torch dependency or scientific inference."""
    if isinstance(config, TrainingDatasetConfig):
        config = config.model_dump(mode="json")
    config = TrainingDatasetConfig.model_validate(config)
    from experiment_to_cpfe.datasets.prediction import selector_identity
    from experiment_to_cpfe.datasets.task_contract import assess_task, check_input_assets
    base_dir = Path(base_dir).resolve()
    chunks, sources = [], []
    seen_paths, seen_hashes = set(), set()
    target_sources = TargetSourceIndex()
    quantities = [*config.features, *config.target_quantities]
    for item in config.inputs:
        source = (base_dir / item.path).resolve()
        context = f"sample {item.sample_id!r} ({source})"
        try:
            digest = sha256_file(source)
            if source in seen_paths or digest in seen_hashes:
                raise ValueError("duplicate HDF5 file path or content")
            seen_paths.add(source)
            seen_hashes.add(digest)
            sample, provenance = _load_source(source, digest)
            if sample.metadata.sample_id != item.sample_id:
                raise ValueError(f"sample identity differs from expected {item.sample_id!r}: {sample.metadata.sample_id!r}")
            group = item.group_id if config.group_by == "explicit" else getattr(sample.metadata, config.group_by)
            if "dataset_split" in sample.solver_inputs and sample.solver_inputs["dataset_split"] != item.split:
                raise ValueError("dataset_split conflicts with requested split")
            layout = config.layouts[item.layout]
            target_selectors = [selector_identity(layout.columns[q.name]) for q in config.target_quantities]
            if any(selector_identity(layout.columns[q.name]) in target_selectors for q in config.features):
                raise ValueError('target contamination: a feature selects the same source column as a target')
            columns = {}
            for quantity in quantities:
                try:
                    columns[quantity.name] = select_column(sample, layout.columns[quantity.name])
                except (ValueError, KeyError, TypeError, IndexError) as exc:
                    raise ValueError(f"field {quantity.name!r}: {exc}") from exc
            anchor = columns[config.features[0].name].ids
            rows = layout.rows
            stop = len(anchor) if rows.stop is None else rows.stop
            if stop > len(anchor) or rows.start >= stop:
                raise ValueError("row selection is empty or outside aligned rows")
            indices = rows.indices if rows.indices is not None else list(range(rows.start, stop, rows.step))
            if indices[-1] >= len(anchor):
                raise ValueError('row indices are outside aligned rows')
            row_ids = [anchor[index] for index in indices]
            vectors, column_records = [], {}
            for name, column in columns.items():
                if set(column.ids) != set(anchor):
                    raise ValueError(f"field {name!r}: identity alignment differs from first feature")
                lookup = {identity: index for index, identity in enumerate(column.ids)}
                order = [lookup[identity] for identity in row_ids]
                vectors.append(column.values[order])
                column_records[name] = {
                    "selector": layout.columns[name].model_dump(mode="json"),
                    "source_rows": [column.source_rows[index] for index in order],
                    "asset_ids": [column.asset_ids[index] for index in order],
                }
            partitions = []
            for quantity in config.target_quantities:
                partitions.extend(register_target_sources(
                    sample, column_records[quantity.name], layout.columns[quantity.name],
                    item.target_specimen, item.split, group, target_sources))
            for quantity in config.features:
                check_input_assets(sample, column_records[quantity.name]['asset_ids'])
            width = len(config.features)
            targets = vectors[-1] if config.version == 1 else np.column_stack(vectors[width:])
            chunks.append((np.column_stack(vectors[:width]), targets, [group] * len(indices),
                           [item.split] * len(indices), [item.sample_id] * len(indices), row_ids))
            sources.append({"path": str(source), "hdf5_sha256": digest, "layout": item.layout,
                            "sample_metadata": sample.metadata.model_dump(mode="json"),
                            "assets": [asset.model_dump(mode="json") for asset in sample.assets],
                            "source_manifest": provenance, "solver_inputs": sample.solver_inputs,
                            "group": group, "split": item.split, "row_ids": row_ids,
                            "columns": column_records, "target_partitions": partitions})
        except (ValueError, KeyError, TypeError, IndexError, OSError) as exc:
            raise ValueError(f"{context}: {exc}") from exc
    arrays = [np.concatenate([chunk[index] for chunk in chunks]) for index in range(6)]
    group_splits = validate_group_splits(arrays[2], arrays[3])
    target_metadata = {"target": config.target.model_dump()} if config.version == 1 else {
        "targets": [quantity.model_dump() for quantity in config.targets]}
    metadata = {"format": TRAINING_FORMAT if config.version == 1 else VECTOR_TRAINING_FORMAT,
                "config": config.model_dump(mode="json", exclude_none=True),
                "features": [quantity.model_dump() for quantity in config.features],
                **target_metadata, "sources": sources, "group_splits": group_splits,
                "processing": ["explicit scalar column selection", "exact row identity alignment",
                               "declared affine conversion", "common row selection", "ordered concatenation"],
                "lossy_transformations": ["unselected rows, fields and arrays omitted", "numeric values represented as float64",
                                           "HDF5 storage layout and compression omitted"]}
    metadata['task_assessment'] = assess_task(config.task_contract, config.features, config.target_quantities, sources)
    return TrainingDataset(*arrays, metadata)


def _json(value) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"


def run_dataset_build(config_path: Path, output_dir: Path) -> dict:
    """Write a new dataset directory and its declared training-input configuration.

    The scalar trainer consumes v1 target declarations and train/validation/test
    partitions; v2 construction records an ordered target list.
    """
    import yaml

    config_path, output = Path(config_path).resolve(), Path(output_dir).resolve()
    if output.exists():
        raise FileExistsError(output)
    config_bytes = config_path.read_bytes()
    try:
        config = yaml.safe_load(config_bytes.decode("utf-8"))
    except (yaml.YAMLError, UnicodeError) as exc:
        raise ValueError(f"invalid dataset configuration: {exc}") from exc
    dataset = build_training_dataset(config, base_dir=config_path.parent)
    payload = {name: getattr(dataset, name) for name in TRAINING_ARRAYS}
    dataset.metadata["payload_hashes"] = {name: array_payload_sha256(array) for name, array in payload.items()}
    metadata_text = _json(dataset.metadata)
    payload.update({"__format_version__": np.asarray(dataset.metadata["format"]),
                    "__metadata_json__": np.asarray(metadata_text),
                    "__metadata_sha256__": np.asarray(hashlib.sha256(metadata_text.encode("utf-8")).hexdigest())})
    buffer = io.BytesIO()
    np.savez_compressed(buffer, **payload)
    npz_bytes = buffer.getvalue()
    training = {"dataset": "dataset.npz", "dataset_sha256": hashlib.sha256(npz_bytes).hexdigest(),
                "feature_names": [quantity["name"] for quantity in dataset.metadata["features"]],
                "feature_units": [quantity["unit"] for quantity in dataset.metadata["features"]]}
    if "target" in dataset.metadata:
        training.update(target_name=dataset.metadata["target"]["name"], target_unit=dataset.metadata["target"]["unit"])
    else:
        training.update(target_names=[quantity["name"] for quantity in dataset.metadata["targets"]],
                        target_units=[quantity["unit"] for quantity in dataset.metadata["targets"]])
    files = {"dataset.npz": npz_bytes, "dataset.json": metadata_text.encode("utf-8"),
             "training-config.json": _json(training).encode("utf-8")}
    manifest = {"status": "completed", "stage": "build-training-dataset", "format": dataset.metadata["format"],
                "created_at": datetime.now(timezone.utc).isoformat(), "config_path": str(config_path),
                "config_sha256": hashlib.sha256(config_bytes).hexdigest(), "rows": len(dataset.targets),
                "artifacts": {name: {"sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content)}
                              for name, content in files.items()},
                "sources": [{"path": source["path"], "sha256": source["hdf5_sha256"]} for source in dataset.metadata["sources"]]}
    files["build-manifest.json"] = _json(manifest).encode("utf-8")
    # Reserve only after the complete collection and all serialization have succeeded.
    output.mkdir(parents=True, exist_ok=False)
    for name, content in files.items():
        with (output / name).open("xb") as stream:
            stream.write(content)
    return {"status": "completed", "dataset": str(output / "dataset.npz"),
            "training_config": str(output / "training-config.json"), "rows": len(dataset.targets)}
