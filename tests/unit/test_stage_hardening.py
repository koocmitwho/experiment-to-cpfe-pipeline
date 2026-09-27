"""Public CLI, configured gates and reproducibility metadata."""

import importlib
import importlib.metadata
import hashlib
import json
from pathlib import Path
import platform
import sys

import pytest
import yaml


def test_cli_version_reports_the_package_version(capsys):
    from experiment_to_cpfe import __version__
    from experiment_to_cpfe.cli import main

    assert main(["--version"]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == f"pipeline {__version__}"
    assert not captured.err


@pytest.mark.parametrize("command,module,function,extra", [
    ("validate", "cli", "run_validate", []),
    ("build-inp", "cli", "run_build_inp", []),
    ("stage-input-bundle", "cli", "run_stage_input_bundle", []),
    ("run-abaqus", "cli", "run_abaqus_stage", ["--stage", "analysis"]),
    ("extract-odb", "cli", "run_extract_odb", []),
    ("export", "cli", "run_export", ["--format", "hdf5"]),
    ("adapt", "adapters.native_runner", "run_native_adapt", []),
    ("build-training-dataset", "datasets.training", "run_dataset_build", []),
    ("train-surrogate", "learning.surrogate", "run_training", []),
])
def test_cli_reports_stage_completion(command, module, function, extra, monkeypatch, capsys, tmp_path):
    from experiment_to_cpfe.cli import main

    # Isolate CLI presentation from solver execution and model optimization.
    implementation = importlib.import_module(f"experiment_to_cpfe.{module}")
    monkeypatch.setattr(implementation, function, lambda *args: {
        "status": "completed", "artifacts": [str(tmp_path / "result.json")],
    })
    assert main([command, "--config", "sample.yaml", "--run-dir", str(tmp_path), *extra]) == 0
    captured = capsys.readouterr()
    assert command in captured.out
    assert "completed" in captured.out
    assert str(tmp_path) in captured.out
    assert not captured.err


def test_cli_real_validate_build_and_export_report_results(multimodal_sample_config, tmp_path, capsys):
    from experiment_to_cpfe.cli import main

    run = tmp_path / "run"
    for command, extra in (("validate", []), ("build-inp", []), ("export", ["--format", "hdf5"])):
        assert main([command, "--config", str(multimodal_sample_config), "--run-dir", str(run), *extra]) == 0
        assert "completed" in capsys.readouterr().out
    assert (run / "dataset/sample.h5").is_file()


def test_cli_reports_a_blocked_stage_to_stderr(multimodal_sample_config, tmp_path, capsys):
    from experiment_to_cpfe import pipeline
    from experiment_to_cpfe.cli import main

    run = tmp_path / "run"
    pipeline.run_validate(multimodal_sample_config, run)
    assert main(["run-abaqus", "--config", str(multimodal_sample_config),
                 "--run-dir", str(run), "--stage", "analysis"]) == 1
    captured = capsys.readouterr()
    assert "blocked" in captured.err
    assert "build-inp" in captured.err
    assert not captured.out


@pytest.mark.parametrize("format_name", ["hdf5", "npz"])
def test_export_requires_the_requested_format_in_configuration(multimodal_sample_config, tmp_path, format_name):
    from experiment_to_cpfe import pipeline

    config = multimodal_sample_config
    payload = yaml.safe_load(config.read_text())
    payload["export"]["formats"] = ["hdf5"] if format_name == "npz" else ["npz"]
    config.write_text(yaml.safe_dump(payload))
    run = tmp_path / "run"
    pipeline.run_validate(config, run)
    if format_name == "npz":
        assert pipeline.run_export(config, run, "hdf5")["status"] == "completed"
    result = pipeline.run_export(config, run, format_name)
    assert result["status"] == "blocked"
    assert any("export.formats" in issue for issue in result["limitations"])
    suffix = "h5" if format_name == "hdf5" else "npz"
    assert not (run / f"dataset/sample.{suffix}").exists()


def test_loaded_warning_policy_is_shared_by_validation_readiness_and_preflight(
    multimodal_sample_config, tmp_path, monkeypatch,
):
    from experiment_to_cpfe import pipeline

    config = multimodal_sample_config
    payload = yaml.safe_load(config.read_text())
    payload["sample"]["unit_system"]["temperature"] = "unknown"
    payload["abaqus"]["command"] = [sys.executable, str(Path("tests/fixtures/fake_solver.py").resolve())]
    config.write_text(yaml.safe_dump(payload))
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text("missing_units_severity: warning\n")
    monkeypatch.setattr(pipeline, "_default_policy_path", lambda: policy_path)
    monkeypatch.delenv("EXP2CPFE_ABAQUS_COMMAND", raising=False)
    run = tmp_path / "run"
    assert pipeline.run_validate(config, run)["status"] == "completed"
    validation = json.loads((run / "reports/validation.json").read_text())
    readiness = json.loads((run / "reports/solver_readiness.json").read_text())
    assert validation["passed"] and readiness["ready"]
    assert any(issue["severity"] == "warning" for issue in validation["issues"])
    assert any("temperature" in issue for issue in readiness["warnings"])
    assert pipeline.run_build_inp(config, run)["status"] == "completed"
    assert pipeline.run_abaqus_stage(config, run, "datacheck")["status"] == "completed"
    preflight = json.loads((run / "reports/abaqus_datacheck_preflight.json").read_text())
    assert preflight["validation"]["passed"] and preflight["solver_readiness"]["ready"]


def test_run_manifest_records_actual_runtime_versions_and_package_sources(multimodal_sample_config, tmp_path):
    from experiment_to_cpfe import __version__, pipeline

    run = tmp_path / "run"
    pipeline.run_validate(multimodal_sample_config, run)
    before = json.loads((run / "reports/run_manifest.json").read_text())
    runtime = before["runtime"]
    assert runtime["tool"]["version"] == __version__
    assert runtime["python"]["version"] == platform.python_version()
    for distribution in ("numpy", "pandas", "h5py"):
        assert runtime["dependencies"][distribution] == importlib.metadata.version(distribution)
    assert len(runtime["code"]["sha256"]) == 64
    assert "pipeline.py" in runtime["code"]["files"]
    pipeline.run_export(multimodal_sample_config, run, "hdf5")
    after = json.loads((run / "reports/run_manifest.json").read_text())
    assert after["runtime"] == runtime
    assert all(after["artifacts"][key] == value for key, value in before["artifacts"].items())


def test_source_fingerprint_detects_same_version_code_changes_and_ignores_bytecode(tmp_path):
    from experiment_to_cpfe.provenance.manifest import source_fingerprint

    source = tmp_path / "module.py"
    source.write_bytes(b"value = 1\n")
    (tmp_path / "__pycache__").mkdir()
    cached = tmp_path / "__pycache__/module.pyc"
    cached.write_bytes(b"bytecode-one")
    first = source_fingerprint(tmp_path)
    cached.write_bytes(b"bytecode-two")
    assert source_fingerprint(tmp_path) == first
    source.write_bytes(b"value = 2\n")
    assert source_fingerprint(tmp_path)["sha256"] != first["sha256"]
    assert first["files"] == {"module.py": hashlib.sha256(b"value = 1\n").hexdigest()}
