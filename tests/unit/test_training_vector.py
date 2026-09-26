"""Named multi-target dataset construction; all numerical labels are synthetic."""

import json

import numpy as np
import pytest

from training_fixtures import training_collection, replace_sample, save_config


def vector_collection(root, make_sample, count=5):
    config, samples = training_collection(root, make_sample, count=count)
    config["version"] = 2
    config["targets"] = [config.pop("target"), {"name": "temperature", "unit": "K"}]
    config["layouts"]["table"]["columns"]["temperature"] = {
        "kind": "table", "table": "measured_observations", "column": "temperature",
        "source_unit": "K", "id_columns": ["increment_id"], "where": {"phase": "response"}}
    for sample in samples:
        sample.assets = (sample.assets[0].model_copy(update={
            "units": dict(sample.assets[0].units, temperature="K")}),)
        for row in sample.tables["measured_observations"]:
            row["temperature"] = 273.15 + 1000 * row["eps"] - 10 * row["modulus"]
        replace_sample(root, sample)
    return config, samples


def test_vector_builder_aligns_each_target_and_records_units(tmp_path, make_sample):
    from experiment_to_cpfe.datasets.training import build_training_dataset, run_dataset_build
    config, _ = vector_collection(tmp_path, make_sample)
    data = build_training_dataset(config, base_dir=tmp_path)
    assert data.features.shape == (20, 2)
    assert data.targets.shape == (20, 2)
    assert data.targets[:2] == pytest.approx(np.array([[0., 263.15], [.25, 513.15]]))
    assert data.row_ids.shape == (20,)
    assert data.metadata["sources"][0]["columns"]["temperature"]["source_rows"] == [9, 8, 7, 6, 5]
    run_dataset_build(save_config(tmp_path / "build.json", config), tmp_path / "built")
    train = json.loads((tmp_path / "built/training-config.json").read_text())
    assert train["target_names"] == ["stress", "temperature"]
    assert train["target_units"] == ["Pa", "K"]
    assert "target_name" not in train
    with np.load(tmp_path / "built/dataset.npz", allow_pickle=False) as payload:
        assert payload["__format_version__"].item() == "experiment-to-cpfe-training-2"


@pytest.mark.parametrize("mutation", ["both", "missing", "duplicate", "unit", "shape"])
def test_vector_contract_rejects_ambiguous_or_incomplete_targets(tmp_path, make_sample, mutation):
    from experiment_to_cpfe.datasets.training import build_training_dataset
    config, _ = vector_collection(tmp_path, make_sample)
    if mutation == "both": config["target"] = config["targets"][0]
    elif mutation == "missing": config.pop("targets")
    elif mutation == "duplicate": config["targets"][1]["name"] = "stress"
    elif mutation == "unit": config["targets"][1]["unit"] = "unknown"
    else: config["layouts"]["table"]["columns"].pop("temperature")
    with pytest.raises(ValueError):
        build_training_dataset(config, base_dir=tmp_path)


def test_secondary_target_source_leakage_is_rejected(tmp_path, make_sample):
    from experiment_to_cpfe.datasets.training import build_training_dataset
    config, samples = vector_collection(tmp_path, make_sample)
    for sample in samples:
        target_asset = sample.assets[0].model_copy(update={
            "asset_id": "temperature-raw", "uri": "synthetic:shared-temperature", "sha256": None})
        sample.assets += (target_asset,)
        sample.tables["measured_observations"] += [
            dict(row, phase="temperature", source_asset_id="temperature-raw")
            for row in list(sample.tables["measured_observations"]) if row["phase"] == "response"]
        replace_sample(tmp_path, sample)
    config["layouts"]["table"]["columns"]["temperature"]["where"] = {"phase": "temperature"}
    with pytest.raises(ValueError, match="target source.*splits"):
        build_training_dataset(config, base_dir=tmp_path)
