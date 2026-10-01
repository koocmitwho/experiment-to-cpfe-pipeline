"""Specimen partitions use original native records, never renamed source files."""

import pytest

from experiment_to_cpfe.adapters.tabular import assemble_sample
from experiment_to_cpfe.config import PipelineConfig
from experiment_to_cpfe.datasets.hdf5 import write_hdf5
from experiment_to_cpfe.datasets.training import build_training_dataset


@pytest.fixture
def specimens(tmp_path, make_sample):
    raw = tmp_path / "shared.csv"
    raw.write_text("specimen,x,y\n" + "".join(
        f"{name},{i},{i * 3 + j}\n" for i, name in enumerate("abcdef") for j in range(2)
    ), encoding="utf-8")
    inputs, samples = [], []
    for i, (name, split) in enumerate(zip("abcdef", ("train",)*2 + ("validation",)*2 + ("test",)*2)):
        metadata = make_sample().metadata.model_dump(mode="json", exclude={"sources"})
        metadata["sample_id"] = name
        config = PipelineConfig.model_validate({
            "sample": metadata,
            "sources": [{"path": raw, "table_name": "measured_observations", "source_kind": "input",
                         "modality": "table", "format": "csv", "delimiter": ",", "encoding": "utf-8",
                         "column_map": {"specimen": "0", "x": "1", "y": "2"},
                         "units": {"specimen": "1", "x": "1", "y": "1"},
                         "coordinate_frame": None, "axis_order": ["row"], "native_layout": "synthetic rows",
                         "license": "Apache-2.0", "block": {"data_start_row": 2+i*2, "data_end_row": 4+i*2,
                                                                    "numeric_fields": ["x", "y"]}}],
            "abaqus": {"command": ["unused"], "job_name": "unused"}, "export": {"formats": ["hdf5"]}})
        sample = assemble_sample(config)
        write_hdf5(sample, tmp_path / f"{name}.h5")
        samples.append(sample)
        inputs.append({"path": f"{name}.h5", "sample_id": name, "split": split, "layout": "table",
                       "target_specimen": {"column": "specimen", "evidence": "original specimen column in synthetic CSV"}})
    columns = {k: {"kind": "table", "table": "measured_observations", "column": k,
                   "id_columns": ["source_row"], "source_unit": "1"} for k in ("x", "y")}
    build = {"version": 1, "features": [{"name": "x", "unit": "1"}], "target": {"name": "y", "unit": "1"},
             "group_by": "sample_id", "grouping_evidence": "independent synthetic specimens",
             "layouts": {"table": {"columns": columns, "alignment_evidence": "same original row"}}, "inputs": inputs}
    return build, samples


def test_shared_file_independent_specimens_keep_full_provenance(tmp_path, specimens):
    config, _ = specimens
    result = build_training_dataset(config, base_dir=tmp_path)
    assert result.groups.tolist() == [name for name in "abcdef" for _ in range(2)]
    assert len({s["assets"][0]["sha256"] for s in result.metadata["sources"]}) == 1
    assert result.metadata["sources"][2]["target_partitions"][0] == {
        "asset_id": "asset-source-0000", "specimen": "c", "records": [["", 6], ["", 7]],
        "evidence": "original specimen column in synthetic CSV", "column": "specimen", "source_column": 0}


@pytest.mark.parametrize("unscoped", [0, 2, 5, "all"])
def test_scoped_and_whole_file_cannot_mix_across_splits(tmp_path, specimens, unscoped):
    config, _ = specimens
    for i, item in enumerate(config["inputs"]):
        if unscoped == "all" or i == unscoped:
            item.pop("target_specimen")
    with pytest.raises(ValueError, match="target source.*reused across splits"):
        build_training_dataset(config, base_dir=tmp_path)


@pytest.mark.parametrize("change,match", [
    ({"column": "missing"}, "specimen.*mapped"),
    ({"column": "x"}, "specimen.*(group|original text)"),
    ({"evidence": ""}, "evidence"),
    ({"column": "specimen", "rename": True}, "extra"),
])
def test_specimen_declaration_is_bound_to_actual_mapped_group(tmp_path, specimens, change, match):
    config, _ = specimens
    config["inputs"][0]["target_specimen"].update(change)
    with pytest.raises(ValueError, match=match):
        build_training_dataset(config, base_dir=tmp_path)


def test_original_source_overlap_is_rejected_even_if_group_was_renamed(tmp_path, specimens):
    from experiment_to_cpfe.datasets.training_sources import TargetSourceIndex
    _, samples = specimens
    index = TargetSourceIndex()
    scope = {"specimen": "a", "records": [["Sheet1", 2]]}
    index.register(samples[0].assets[0], "train", "a", scope)
    with pytest.raises(ValueError, match="reused across splits"):
        index.register(samples[0].assets[0], "test", "renamed", {**scope, "specimen": "renamed"})


@pytest.mark.parametrize("digest_missing", [False, True])
def test_same_specimen_disjoint_repeats_still_overlap(tmp_path, specimens, digest_missing):
    from experiment_to_cpfe.datasets.training_sources import TargetSourceIndex
    _, samples = specimens
    raw = samples[0].assets[0]
    index = TargetSourceIndex()
    index.register(raw, "train", "a", {"specimen": "a", "records": [["", 2]]})
    other = raw.model_copy(update={"sha256": None}) if digest_missing else raw
    with pytest.raises(ValueError, match="reused across splits"):
        index.register(other, "test", "a2", {"specimen": "a", "records": [["", 3]]})


@pytest.mark.parametrize("mutation", ["conversion", "mapped", "row", "bounds", "sheet"])
def test_partition_requires_native_location_and_conversion_receipt(tmp_path, specimens, mutation):
    from experiment_to_cpfe.assets.registry import table_payload_sha256
    config, samples = specimens
    sample = samples[0]
    raw, curated = sample.assets
    if mutation == "conversion":
        curated = curated.model_copy(update={"conversion": None})
    elif mutation == "mapped":
        raw = raw.model_copy(update={"descriptive_metadata": {**raw.descriptive_metadata, "column_map": {}}})
    else:
        row = sample.tables["measured_observations"][0]
        if mutation == "row": row.pop("source_row")
        elif mutation == "bounds": row["source_row"] = 900
        else: row["source_sheet"] = "invented"
        digest = table_payload_sha256(sample.tables["measured_observations"])
        curated = curated.model_copy(update={"sha256": digest, "conversion": curated.conversion.model_copy(
            update={"target_payload_sha256": digest})})
    sample.assets = (raw, curated)
    path = tmp_path / "a.h5"
    path.unlink()
    write_hdf5(sample, path)
    with pytest.raises(ValueError, match="specimen|missing fields"):
        build_training_dataset(config, base_dir=tmp_path)
