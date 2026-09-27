"""Exercise extraction data at loading, validation and the export boundary."""

import csv
import json
from pathlib import Path
import shutil

import pytest

from experiment_to_cpfe.schema.validation import ValidationPolicy, validate_sample
from experiment_to_cpfe.solvers.abaqus.extraction import load_extraction_bundle


@pytest.fixture
def valid_bundle(tmp_path):
    from experiment_to_cpfe._resources.field_contract import CSV_COLUMNS

    target = tmp_path / "bundle"
    shutil.copytree("tests/fixtures/odb_extract_fixture", target)
    metadata = json.loads((target / "metadata.json").read_text())
    metadata.update(extraction_version="0.2", field_contract_version="1.0",
                    missing_fields=[], complete=True)
    (target / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    rows = []
    for frame in (0, 1):
        row = dict.fromkeys(CSV_COLUMNS, "")
        row.update(step="Step-1", frame=frame, increment_number=frame,
                   frame_value=float(frame), domain="TIME", frame_time=float(frame),
                   increment_id=f"Step-1:{frame}", load_case="LC",
                   field="S" if frame == 0 else "LE", position="INTEGRATION_POINT", instance="PART-1",
                   element_label=1, integration_point=1, component="S11" if frame == 0 else "LE11",
                   precision="DOUBLE_PRECISION", value=100.0 * frame)
        rows.append(row)
    with (target / "frames.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return target


def codes(sample):
    return {issue.code for issue in validate_sample(sample, ValidationPolicy()).errors}


@pytest.mark.parametrize("column,value,expected", [
    ("frame_time", -5.0, "NONMONOTONIC_TIME"),
    ("value", float("nan"), "NONFINITE_VALUE"),
    ("increment_id", "Step-1:0", "DUPLICATE_INCREMENT"),
    ("source_asset_id", "unregistered", "INVALID_ROW_SOURCE"),
])
def test_export_revalidates_loaded_extraction(
    valid_bundle, multimodal_sample_config, tmp_path, monkeypatch, column, value, expected,
):
    from experiment_to_cpfe import pipeline

    run = tmp_path / "run"
    config = multimodal_sample_config
    assert pipeline.run_validate(config, run)["status"] == "completed"
    initial = (run / "reports/validation.json").read_bytes()
    extracted = run / "solver/extracted"
    shutil.copytree(valid_bundle, extracted)
    pipeline._record_stage(run, config, {
        "stage": "extract-odb", "status": "completed",
        "artifacts": [str(extracted / name) for name in ("metadata.json", "frames.csv")],
        "limitations": [],
    })
    before = json.loads((run / "reports/run_manifest.json").read_text())
    original = pipeline.load_extraction_bundle

    def load_then_poison(path):
        sample = original(path)
        sample.tables["simulation_records"][1][column] = value
        return sample

    monkeypatch.setattr(pipeline, "load_extraction_bundle", load_then_poison)
    result = pipeline.run_export(config, run, "hdf5")
    assert result["status"] == "blocked"
    assert expected in {issue["code"] for issue in result["validation"]["issues"]}
    assert not (run / "dataset/sample.h5").exists()
    report = run / "reports/export-hdf5_validation.json"
    assert json.loads(report.read_text()) == result["validation"]
    assert str(report) in result["artifacts"]
    assert (run / "reports/validation.json").read_bytes() == initial
    after = json.loads((run / "reports/run_manifest.json").read_text())
    assert all(after["artifacts"][path] == receipt for path, receipt in before["artifacts"].items())


def test_export_records_validation_for_successful_merged_sample(valid_bundle, multimodal_sample_config, tmp_path):
    from experiment_to_cpfe import pipeline
    from experiment_to_cpfe.datasets.hdf5 import read_hdf5

    run = tmp_path / "run"
    config = multimodal_sample_config
    assert pipeline.run_validate(config, run)["status"] == "completed"
    extracted = run / "solver/extracted"
    shutil.copytree(valid_bundle, extracted)
    pipeline._record_stage(run, config, {
        "stage": "extract-odb", "status": "completed",
        "artifacts": [str(extracted / name) for name in ("metadata.json", "frames.csv")],
    })
    result = pipeline.run_export(config, run, "hdf5")
    assert result["status"] == "completed"
    assert result["validation"]["passed"] is True
    restored = read_hdf5(run / "dataset/sample.h5")
    assert restored.tables["simulation_records"][1]["value"] == 100.0
    assert validate_sample(restored, ValidationPolicy()).passed


@pytest.mark.parametrize("legacy", [False, True])
def test_step_relative_frame_time_decrease_is_reported(valid_bundle, legacy):
    path = Path("tests/fixtures/odb_extract_fixture") if legacy else valid_bundle
    sample = load_extraction_bundle(path)
    sample.tables["simulation_records"][1]["frame_time"] = -5.0
    assert "NONMONOTONIC_TIME" in codes(sample)


def test_increment_identifies_one_frame_across_fields(valid_bundle):
    sample = load_extraction_bundle(valid_bundle)
    rows = sample.tables["simulation_records"]
    rows[1].update(increment_id=rows[0]["increment_id"], field="LE", component="LE11", unit="1")
    assert "DUPLICATE_INCREMENT" in codes(sample)


def test_one_frame_retains_one_increment_identity_across_components(valid_bundle):
    sample = load_extraction_bundle(valid_bundle)
    rows = sample.tables["simulation_records"]
    rows.append({**rows[0], "increment_id": "conflicting", "component": "S22"})
    assert "INCONSISTENT_INCREMENT" in codes(sample)


@pytest.mark.parametrize("value", ["invalid", True])
def test_loaded_field_values_remain_numeric_data(valid_bundle, value):
    sample = load_extraction_bundle(valid_bundle)
    sample.tables["simulation_records"][0]["value"] = value
    assert "INVALID_FIELD_VALUE" in codes(sample)


def test_one_increment_can_have_multiple_fields_components_and_locations(valid_bundle):
    sample = load_extraction_bundle(valid_bundle)
    rows = sample.tables["simulation_records"]
    rows.extend([
        {**rows[0], "component": "S22"},
        {**rows[0], "element_label": 2},
        {**rows[0], "field": "LE", "component": "LE11", "unit": "1"},
    ])
    assert not codes(sample)


def test_field_clocks_follow_frame_order_instead_of_storage_order(valid_bundle):
    sample = load_extraction_bundle(valid_bundle)
    sample.tables["simulation_records"].reverse()
    assert not codes(sample)


@pytest.mark.parametrize("key", ["step", "load_case"])
def test_frame_clock_resets_for_each_step_and_load_case(valid_bundle, key):
    sample = load_extraction_bundle(valid_bundle)
    rows = sample.tables["simulation_records"]
    rows.append({**rows[0], key: "second"})
    assert not codes(sample)


def test_frequency_frame_value_is_preserved_in_its_own_domain(valid_bundle):
    sample = load_extraction_bundle(valid_bundle)
    for row, value in zip(sample.tables["simulation_records"], (20.0, 10.0)):
        row.update(domain="FREQUENCY", frame_time="", frame_value=value)
    assert not codes(sample)


def test_explicit_time_and_step_relative_time_use_separate_clocks(valid_bundle):
    sample = load_extraction_bundle(valid_bundle)
    rows = sample.tables["simulation_records"]
    rows[0]["time"], rows[1]["time"] = 100.0, 101.0
    assert not codes(sample)
    rows[1]["time"] = 99.0
    assert "NONMONOTONIC_TIME" in codes(sample)


@pytest.mark.parametrize("domain,value", [("TIME", ""), ("TIME", "bad"), ("FREQUENCY", 1.0)])
def test_frame_time_requires_finite_time_domain_data(valid_bundle, domain, value):
    sample = load_extraction_bundle(valid_bundle)
    sample.tables["simulation_records"][0].update(domain=domain, frame_time=value)
    assert "INVALID_TIME" in codes(sample)


def test_one_frame_has_one_time_across_components(valid_bundle):
    sample = load_extraction_bundle(valid_bundle)
    rows = sample.tables["simulation_records"]
    rows.append({**rows[0], "component": "S22", "frame_time": 0.25})
    assert "INCONSISTENT_FRAME_TIME" in codes(sample)


def test_loaded_rows_bind_to_the_simulated_extraction_asset(valid_bundle):
    sample = load_extraction_bundle(valid_bundle)
    asset = next(asset for asset in sample.assets if asset.format == "odb-extraction-bundle")
    for row in sample.tables["simulation_records"]:
        assert row["source_asset_id"] == asset.asset_id
        assert row["source_kind"] == "simulated"
    assert validate_sample(sample, ValidationPolicy()).passed


@pytest.mark.parametrize("mutation,expected", [
    ("remove-binding", "INVALID_ROW_SOURCE"),
    ("measured-source", "CONTRADICTORY_EVIDENCE"),
    ("wrong-unit", "CONTRADICTORY_EVIDENCE"),
])
def test_extracted_row_provenance_and_field_units_are_validated(valid_bundle, mutation, expected):
    from experiment_to_cpfe.assets.models import SourceKind

    sample = load_extraction_bundle(valid_bundle)
    row = sample.tables["simulation_records"][0]
    if mutation == "remove-binding":
        row.pop("source_asset_id", None)
        row.pop("source_kind", None)
    elif mutation == "measured-source":
        sample.assets = tuple(asset.model_copy(update={"source_kind": SourceKind.MEASURED})
                              if asset.format == "odb-extraction-bundle" else asset for asset in sample.assets)
    else:
        row["unit"] = "MPa"
    assert expected in codes(sample)


@pytest.mark.parametrize("field", ["odb_sha256", "odb_path", "sample_metadata"])
def test_missing_required_metadata_is_a_named_value_error(valid_bundle, field):
    path = valid_bundle / "metadata.json"
    metadata = json.loads(path.read_text())
    del metadata[field]
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match=field):
        load_extraction_bundle(valid_bundle)


@pytest.mark.parametrize("field,value", [("odb_sha256", None), ("odb_path", []), ("sample_metadata", None)])
def test_invalid_required_metadata_is_a_named_value_error(valid_bundle, field, value):
    path = valid_bundle / "metadata.json"
    metadata = json.loads(path.read_text())
    metadata[field] = value
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match=field):
        load_extraction_bundle(valid_bundle)


def test_current_extraction_requires_a_field_contract_version(valid_bundle):
    path = valid_bundle / "metadata.json"
    metadata = json.loads(path.read_text())
    del metadata["field_contract_version"]
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="field.contract"):
        load_extraction_bundle(valid_bundle)


def test_legacy_01_bundle_retains_compatible_loading():
    sample = load_extraction_bundle(Path("tests/fixtures/odb_extract_fixture"))
    assert [row["value"] for row in sample.tables["simulation_records"]] == [0.0, 0.001]
    assert validate_sample(sample, ValidationPolicy()).passed
