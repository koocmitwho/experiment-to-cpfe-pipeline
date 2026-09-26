"""NumPy-only contracts shared by dataset construction and CPU training."""

import hashlib
import json

import numpy as np

from experiment_to_cpfe.assets.registry import array_payload_sha256


TRAINING_FORMAT = "experiment-to-cpfe-training-1"
VECTOR_TRAINING_FORMAT = "experiment-to-cpfe-training-2"
TRAINING_ARRAYS = ("features", "targets", "groups", "splits", "sample_ids", "row_ids")


def validate_group_splits(groups, splits) -> dict[str, str]:
    groups, splits = np.asarray(groups, str), np.asarray(splits, str)
    if groups.ndim != 1 or splits.shape != groups.shape:
        raise ValueError("aligned one-dimensional group/split arrays are required")
    provided = set(splits)
    if (not {"train", "validation"}.issubset(provided) or not provided.issubset({"train", "validation", "test"})
            or any(not value.strip() for value in groups)):
        raise ValueError("train and validation splits with named groups are required; test is optional")
    group_splits = {}
    for group, split in zip(groups.tolist(), splits.tolist()):
        previous = group_splits.setdefault(group, split)
        if previous != split:
            raise ValueError(f"group {group!r} appears in multiple dataset splits: {previous} and {split}")
    if any(np.count_nonzero(splits == split) < 2 for split in provided):
        raise ValueError("each split needs at least two records")
    return group_splits


def read_training_bundle(payload, declarations) -> tuple[dict, dict | None]:
    """Accept legacy numerical NPZ or verify an identified training collection."""
    required = {"features", "targets", "groups", "splits"}
    if not required <= set(payload.files):
        raise ValueError("training NPZ requires features, targets, groups and splits")
    arrays = {name: payload[name] for name in required}
    marker = None
    if "__format_version__" in payload.files:
        version = payload["__format_version__"]
        if version.ndim == 0:
            marker = version.item()
    training_marker = isinstance(marker, str) and marker.startswith("experiment-to-cpfe-training-")
    has_training_metadata = bool({"__metadata_json__", "__metadata_sha256__"} & set(payload.files))
    if not training_marker and not has_training_metadata:
        return arrays, None
    try:
        if marker not in (TRAINING_FORMAT, VECTOR_TRAINING_FORMAT):
            raise ValueError("missing or unsupported training bundle format")
        text = payload["__metadata_json__"].item()
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != payload["__metadata_sha256__"].item():
            raise ValueError("training bundle metadata digest mismatch")
        metadata = json.loads(text)
        if metadata["format"] != marker:
            raise ValueError("unsupported training dataset metadata format")
        for name in TRAINING_ARRAYS:
            if array_payload_sha256(payload[name]) != metadata["payload_hashes"][name]:
                raise ValueError(f"training dataset payload changed: {name}")
        expected = {
            "feature_names": [quantity["name"] for quantity in metadata["features"]],
            "feature_units": [quantity["unit"] for quantity in metadata["features"]],
        }
        if marker == TRAINING_FORMAT:
            expected.update(target_name=metadata["target"]["name"], target_unit=metadata["target"]["unit"])
            if arrays["targets"].ndim != 1:
                raise ValueError("scalar training target must be one-dimensional")
        else:
            expected.update(target_names=[quantity["name"] for quantity in metadata["targets"]],
                            target_units=[quantity["unit"] for quantity in metadata["targets"]])
            if arrays["targets"].shape != (len(arrays["features"]), len(metadata["targets"])):
                raise ValueError("vector training targets must match row and target counts")
        for key, value in expected.items():
            if declarations[key] != value:
                raise ValueError(f"training dataset {key} disagrees with training configuration")
        row_shape = (len(arrays["features"]),)
        if payload["sample_ids"].shape != row_shape or payload["row_ids"].shape != row_shape:
            raise ValueError("training dataset row identities are misaligned")
        from experiment_to_cpfe.datasets.task_contract import assess_task
        assess_task(metadata['config'].get('task_contract'), metadata['features'],
                    metadata.get('targets', [metadata.get('target')]), metadata['sources'])
        if metadata['config'].get('task_contract') is not None:
            expected = {(s['sample_metadata']['sample_id'], row): (s['group'], s['split'])
                        for s in metadata['sources'] for row in s['row_ids']}
            actual = {(str(sample), str(row)): (str(group), str(split))
                      for sample, row, group, split in zip(payload['sample_ids'], payload['row_ids'],
                          arrays['groups'], arrays['splits'], strict=True)}
            if expected != actual or len(actual) != len(arrays['features']):
                raise ValueError('training identities/roles differ from the source row ledger')
        return arrays, metadata
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise ValueError(f"invalid training bundle metadata: {exc}") from exc
