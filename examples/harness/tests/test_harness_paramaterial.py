"""Fixed-case evidence gates, including real files and one real offline execution."""
import csv
import hashlib
import importlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import h5py
import pytest


CASE = Path(__file__).resolve().parents[3] / "examples" / "paramaterial_tensile"


def api(module):
    try:
        return importlib.import_module("experiment_to_cpfe.harness." + module)
    except ImportError as exc:
        pytest.fail(f"The public harness evidence API is missing: {exc}")


def save(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def case_copy(tmp_path):
    target = tmp_path / "case"
    shutil.copytree(CASE, target)
    return target


def test_inspection_freezes_complete_case_and_does_not_write():
    adapter = api("workflows.paramaterial")
    before = {str(p.relative_to(CASE)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in CASE.rglob("*") if p.is_file()}
    result = adapter.inspect_case(CASE)
    assert result["valid"] is True, result
    assert result["total_rows"] == 1889
    assert result["specimen_ids"] == ["test_ID_055", "test_ID_056", "test_ID_057"]
    assert {"workflow.py", "verify_outputs.py", "data/manifest.json",
            "data/reference_metrics.json", "requirements.txt"} <= result["files"].keys()
    assert before == {str(p.relative_to(CASE)): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in CASE.rglob("*") if p.is_file()}


@pytest.mark.parametrize("field,value,code", [
    ("units", {"Strain": "1", "Stress_MPa": "Pa"}, "INVALID_UNITS"),
    ("original_filename", None, "MISSING_METADATA"),
    ("sample_id", "test_ID_055-duplicate", "SPECIMEN_IDENTITY_MISMATCH"),
])
def test_bad_units_and_missing_identity_metadata_are_specific(case_copy, field, value, code):
    adapter = api("workflows.paramaterial")
    path = case_copy / "data/manifest.json"
    manifest = json.loads(path.read_text())
    if value is None:
        manifest["specimens"][0].pop(field)
    else:
        manifest["specimens"][0][field] = value
    save(path, manifest)
    result = adapter.inspect_case(case_copy)
    assert result["valid"] is False
    assert any(issue["code"] == code and field in issue["field"] for issue in result["issues"])


@pytest.mark.parametrize("path", ["dataset.license", "paramaterial.processing_sha256", "specimens.0.screening.source_url"])
def test_missing_nested_source_metadata_identifies_the_field(case_copy, path):
    adapter = api("workflows.paramaterial")
    manifest_path = case_copy / "data/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    parent = manifest
    parts = path.split(".")
    for name in parts[:-1]:
        parent = parent[int(name)] if isinstance(parent, list) else parent[name]
    parent.pop(parts[-1])
    save(manifest_path, manifest)
    result = adapter.inspect_case(case_copy)
    assert any(issue["code"] == "MISSING_METADATA" and issue["field"] == path for issue in result["issues"])


@pytest.mark.parametrize("relative", ["data/test_ID_055.csv", "data/reference_metrics.json", "workflow.py"])
def test_changed_data_reference_or_executable_cannot_be_registered(case_copy, relative):
    adapter = api("workflows.paramaterial")
    path = case_copy / relative
    path.write_bytes(path.read_bytes() + b"\n# modified\n")
    result = adapter.inspect_case(case_copy)
    assert not result["valid"]
    assert any(issue["code"] == "SOURCE_HASH_MISMATCH" for issue in result["issues"])


def test_environment_captures_real_processing_identity_without_model_calls():
    result = api("workflows.paramaterial").environment_identity()
    assert result["dependencies"]["paramaterial"] == "0.1.0"
    assert result["processing_sha256"] == "5c991eebb20968e77d93522c4be50d4fa9812de8bf0d430471d46fadbd4e6d22"
    assert result["python_executable"] == str(Path(sys.executable).resolve())
    assert len(result["core_sha256"]) == 64
    assert result["available"] is True


def test_environment_freezes_transitive_packages_and_interpreter_binary():
    result = api("workflows.paramaterial").environment_identity()
    assert "tqdm" in result["distribution_versions"]
    assert "jinja2" in result["distribution_versions"]
    assert result["python_sha256"] == hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()


def test_editable_environment_is_identical_outside_repository(tmp_path):
    adapter = api("workflows.paramaterial")
    expected = adapter.environment_identity()
    script = ("import json; from experiment_to_cpfe.harness.workflows.paramaterial "
              "import environment_identity; print(json.dumps(environment_identity()))")
    observed = []
    for cwd in (CASE.parents[1], tmp_path):
        result = subprocess.run([sys.executable, "-I", "-B", "-c", script], cwd=cwd,
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert result.returncode == 0, result.stderr
        identity = json.loads(result.stdout)
        assert identity["available"] is True
        observed.append(identity)
    assert expected == observed[0] == observed[1]
    package = importlib.import_module("experiment_to_cpfe")
    assert expected["package_dir"] == str(Path(package.__file__).resolve().parent)


def test_actual_loaded_code_change_still_changes_environment_identity(tmp_path):
    package = importlib.import_module("experiment_to_cpfe")
    copied = tmp_path / "experiment_to_cpfe"
    shutil.copytree(Path(package.__file__).resolve().parent, copied, ignore=shutil.ignore_patterns("__pycache__"))
    script = ("import json,sys; sys.path.insert(0,sys.argv[1]); "
              "from experiment_to_cpfe.harness.workflows.paramaterial import environment_identity; "
              "print(json.dumps(environment_identity()))")

    def observe():
        result = subprocess.run([sys.executable, "-I", "-B", "-c", script, str(tmp_path)],
                                cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    before = observe()
    source = copied / "mechanics/tensile.py"
    source.write_bytes(source.read_bytes() + b"\n# deliberate isolated source drift\n")
    after = observe()
    assert before["package_dir"] == after["package_dir"] == str(copied)
    assert before["dependencies"] == after["dependencies"]
    assert before["core_sha256"] != after["core_sha256"]


def test_case_command_is_fixed_and_rejects_changed_script(case_copy, tmp_path):
    adapter = api("workflows.paramaterial")
    command = adapter.case_command(case_copy, tmp_path / "output with spaces", Path(sys.executable))
    assert command == [str(Path(sys.executable).resolve()), "-I", "-X", "utf8", "-B",
                       str(case_copy / "workflow.py"), "--run-dir", str(tmp_path / "output with spaces")]
    (case_copy / "workflow.py").write_text("raise RuntimeError('unregistered')")
    with pytest.raises(ValueError):
        adapter.case_command(case_copy, tmp_path / "different", Path(sys.executable))


@pytest.fixture(scope="module")
def real_output(tmp_path_factory):
    api("acceptance")  # Missing implementation must fail before doing any computation.
    target = tmp_path_factory.mktemp("real-paramaterial") / "run"
    result = subprocess.run([sys.executable, "-I", "-X", "utf8", "-B", str(CASE / "workflow.py"),
                             "--run-dir", str(target)], capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert result.returncode == 0, result.stderr
    return target


@pytest.fixture
def output_copy(real_output, tmp_path):
    target = tmp_path / "output"
    shutil.copytree(real_output, target)
    for path in target.rglob("*.json"):
        path.write_text(path.read_text(encoding="utf-8").replace(
            str(real_output).replace("\\", "\\\\"), str(target).replace("\\", "\\\\")), encoding="utf-8")
    return target


def test_real_case_acceptance_is_independent_readonly_and_scientifically_bounded(real_output):
    module = api("acceptance")
    before = {str(p.relative_to(real_output)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in real_output.rglob("*") if p.is_file()}
    result = module.accept_case(CASE, real_output)
    assert result["overall_acceptance"] == "accepted", result
    assert result["engineering_status"] == result["data_status"] == "passed"
    assert len(result["criterion_results"]) == 9
    assert all(item["status"] == "met" for item in result["criterion_results"])
    assert result["scientific_claim_status"] == "not_established"
    assert len(result["semantic_sha256"]) == 64
    assert before == {str(p.relative_to(real_output)): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in real_output.rglob("*") if p.is_file()}


def test_acceptance_semantic_digest_ignores_output_location(real_output, output_copy):
    accept = api("acceptance").accept_case
    assert accept(CASE, real_output)["semantic_sha256"] == accept(CASE, output_copy)["semantic_sha256"]


def test_claimed_passed_with_missing_specimen_is_rejected(output_copy):
    path = output_copy / "run.json"
    run = json.loads(path.read_text())
    run["cases"].pop()
    save(path, run)
    result = api("acceptance").accept_case(CASE, output_copy)
    assert result["overall_acceptance"] == "rejected"
    assert result["data_status"] == "failed"


@pytest.mark.parametrize("kind", ["unit", "number", "source"])
def test_hdf5_corruption_is_rejected_even_after_rehashing_receipt(output_copy, kind):
    path = output_copy / "normalized/test_ID_055/sample.h5"
    with h5py.File(path, "r+") as handle:
        if kind == "number":
            handle["measured/measured_observations/columns/Stress_MPa"][0] = 999
        elif kind == "unit":
            metadata = json.loads(handle["meta/sample_metadata_json"][()])
            metadata["unit_system"]["Stress_MPa"] = "Pa"
            handle["meta/sample_metadata_json"][()] = json.dumps(metadata)
        else:
            group = handle["assets/asset-source-0000"]
            metadata = json.loads(group.attrs["metadata_json"])
            metadata["sha256"] = "0" * 64
            group.attrs["metadata_json"] = json.dumps(metadata)
    receipt_path = path.parent / "normalization.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["artifacts"]["sample.h5"] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
    save(receipt_path, receipt)
    result = api("acceptance").accept_case(CASE, output_copy)
    assert result["overall_acceptance"] == "rejected"
    assert result["data_status"] == "failed"


def test_metric_failure_does_not_become_execution_failure_or_pass(output_copy):
    path = output_copy / "metrics.csv"
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    rows[0]["UTS_MPa"] = "999"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    result = api("acceptance").accept_case(CASE, output_copy)
    assert result["execution_status"] == "completed"
    assert result["overall_acceptance"] == "rejected"
    assert any(item["status"] == "not_met" for item in result["criterion_results"])


@pytest.mark.parametrize("mutation", ["code", "source", "curve"])
def test_claimed_success_cannot_hide_changed_provenance_or_derived_curve(output_copy, mutation):
    if mutation == "curve":
        path = output_copy / "curves/test_ID_055.csv"
        path.unlink()
    else:
        path = output_copy / "run.json"
        run = json.loads(path.read_text())
        if mutation == "code":
            run["pipeline"]["normalization_sha256"] = "0" * 64
        else:
            run["examples_commit"] = "0" * 40
        save(path, run)
    result = api("acceptance").accept_case(CASE, output_copy)
    assert result["overall_acceptance"] == "rejected"


def test_external_hdf5_link_is_not_dereferenced(output_copy):
    path = output_copy / "normalized/test_ID_055/sample.h5"
    with h5py.File(path, "r+") as handle:
        handle["untrusted"] = h5py.ExternalLink("missing-sensitive-file.h5", "/data")
    result = api("acceptance").accept_case(CASE, output_copy)
    assert result["overall_acceptance"] == "rejected"
    assert result["data_status"] == "failed"


def test_missing_evidence_does_not_pass(tmp_path):
    result = api("acceptance").accept_case(CASE, tmp_path)
    assert result["overall_acceptance"] == "rejected"
    assert result["execution_status"] == "unknown"


@pytest.mark.parametrize("threshold,holdout,expected", [
    ("not_met", "metadata_supported", "rejected"),
    ("not_requested", "metadata_supported", "not_evaluated"),
    ("met", "not_verified", "blocked"),
    ("met", "metadata_supported", "criteria_met"),
])
def test_protocol_report_never_promotes_exit_success_to_science(threshold, holdout, expected):
    report = {"format": "experiment-to-cpfe-evaluation-protocol-1", "holdout_status": holdout,
              "scientific_claim_status": "not_established_by_metadata", "scope_limits": ["fixed evidence"],
              "metric_evidence": [{"metric_id": "rmse", "value": 2.0, "unit": "MPa", "threshold_status": threshold}]}
    result = api("acceptance").evaluate_protocol_report(report)
    assert result["execution_status"] == "completed"
    assert result["overall_acceptance"] == expected
    assert result["scientific_claim_status"] == "not_established_by_metadata"


def test_protocol_missing_or_empty_metric_set_is_not_accepted():
    evaluate = api("acceptance").evaluate_protocol_report
    assert evaluate({})["overall_acceptance"] == "blocked"
    report = {"format": "experiment-to-cpfe-evaluation-protocol-1", "holdout_status": "metadata_supported",
              "scientific_claim_status": "not_established_by_metadata", "metric_evidence": []}
    assert evaluate(report)["overall_acceptance"] == "not_evaluated"
