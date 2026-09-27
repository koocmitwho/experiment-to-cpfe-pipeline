"""Solver identity and optional version probes use synthetic command files."""

import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest
import yaml


PROBE_TIMEOUT_SECONDS = 3


def capture(command, tmp_path, args=()):
    from experiment_to_cpfe.provenance.solver_fingerprint import capture_solver_fingerprint

    return capture_solver_fingerprint(command, cwd=tmp_path, version_probe_args=args)


def test_existing_command_is_hashed_with_streaming_io_and_no_default_probe(tmp_path, monkeypatch):
    from experiment_to_cpfe.solvers.abaqus import runner

    executable = tmp_path / "synthetic-command.exe"
    executable.write_bytes(b"known synthetic command bytes")
    monkeypatch.setattr(Path, "read_bytes", lambda *args: pytest.fail("whole-file read used for hashing"))
    monkeypatch.setattr(runner, "_execute_process", lambda *args, **kwargs: pytest.fail("unconfigured probe executed"))
    result = capture((str(executable), "fixed-argument"), tmp_path)
    assert result["command"] == [str(executable), "fixed-argument"]
    assert result["executable_path"] == str(executable.resolve())
    assert result["executable_sha256"] == hashlib.sha256(b"known synthetic command bytes").hexdigest()
    assert result["version"] is None
    assert result["probe"]["status"] == "not_configured"


@pytest.mark.parametrize("command,reason", [((), "command_not_configured"), (("exp2cpfe-missing-solver",), "command_not_found")])
def test_missing_command_has_null_identity_and_a_reason(tmp_path, monkeypatch, command, reason):
    monkeypatch.setenv("PATH", str(tmp_path))
    result = capture(command, tmp_path, ("information=release",))
    assert result["executable_path"] is None
    assert result["executable_sha256"] is None
    assert result["version"] is None
    assert result["resolution_error"] == reason


def test_relative_path_search_uses_the_invocation_directory(tmp_path, monkeypatch):
    folder = tmp_path / "bin"
    folder.mkdir()
    executable = folder / ("synthetic.exe" if os.name == "nt" else "synthetic")
    executable.write_bytes(b"synthetic executable")
    executable.chmod(0o700)
    monkeypatch.setenv("PATH", "bin")
    result = capture((executable.name,), tmp_path)
    assert result["executable_path"] == str(executable.resolve())
    assert result["resolution_cwd"] == str(tmp_path.resolve())


def test_unreadable_command_hash_is_a_diagnostic(tmp_path, monkeypatch):
    from experiment_to_cpfe.provenance import solver_fingerprint

    path = tmp_path / "synthetic.exe"
    path.write_bytes(b"content")

    def denied(path):
        raise PermissionError("synthetic read denial")

    monkeypatch.setattr(solver_fingerprint, "sha256_file", denied)
    result = capture((str(path),), tmp_path)
    assert result["executable_path"] == str(path.resolve())
    assert result["executable_sha256"] is None
    assert "synthetic read denial" in result["hash_error"]


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_explicit_probe_arguments_return_the_version_string(tmp_path, stream):
    script = tmp_path / "fake version.py"
    script.write_text(
        "import sys\nassert sys.argv[1:] == ['information=release']\n"
        f"sys.{stream}.write('SyntheticSolver 9.0\\n')\n"
    )
    result = capture((sys.executable, str(script)), tmp_path, ("information=release",))
    assert result["version"] == "SyntheticSolver 9.0"
    assert result["probe"]["status"] == "completed"
    assert result["probe"]["timeout_seconds"] == PROBE_TIMEOUT_SECONDS
    assert result["probe"]["command"][-1] == "information=release"


def test_version_probe_preserves_the_virtual_environment_launcher(tmp_path):
    import venv

    script = tmp_path / "fake-environment-version.py"
    script.write_text("import sys\nprint(sys.prefix)\n")
    executable, expected_prefix = sys.executable, sys.prefix
    if os.name != "nt":
        environment = tmp_path / "symlink-environment"
        venv.EnvBuilder(with_pip=False, symlinks=True).create(environment)
        executable, expected_prefix = str(environment / "bin/python"), str(environment)
        assert Path(executable).is_symlink()
    result = capture((executable, str(script)), tmp_path, ("--version",))
    assert result["version"] == expected_prefix


@pytest.mark.parametrize("code,status", [("pass", "empty"), ("import sys; sys.exit(7)", "failed")])
def test_empty_or_failed_probe_has_a_null_version(tmp_path, code, status):
    script = tmp_path / "fake-version.py"
    script.write_text(code)
    result = capture((sys.executable, str(script)), tmp_path, ("--version",))
    assert result["version"] is None
    assert result["probe"]["status"] == status
    assert result["probe"]["reason"]


def test_invalid_executable_does_not_raise_from_the_probe(tmp_path):
    executable = tmp_path / "invalid-program.exe"
    executable.write_text("synthetic invalid executable")
    executable.chmod(0o700)
    result = capture((str(executable),), tmp_path, ("--version",))
    assert result["executable_sha256"]
    assert result["version"] is None
    assert result["probe"]["status"] == "failed"
    assert result["probe"]["reason"]


def test_real_probe_timeout_returns_inside_a_bounded_outer_process(tmp_path):
    script = tmp_path / "slow-probe.py"
    script.write_text(f"import time; time.sleep({PROBE_TIMEOUT_SECONDS * 8})\n")
    driver = (
        "import json,sys; from pathlib import Path; "
        "from experiment_to_cpfe.provenance.solver_fingerprint import capture_solver_fingerprint; "
        "print(json.dumps(capture_solver_fingerprint((sys.executable,sys.argv[1]), "
        "cwd=Path(sys.argv[2]),version_probe_args=('--version',))))"
    )
    result = subprocess.run(
        [sys.executable, "-c", driver, str(script), str(tmp_path)],
        capture_output=True, text=True, check=False, timeout=PROBE_TIMEOUT_SECONDS * 4,
    )
    assert result.returncode == 0, result.stderr
    fingerprint = json.loads(result.stdout)
    assert fingerprint["version"] is None
    assert fingerprint["probe"]["status"] == "timeout"
    assert fingerprint["probe"]["timeout_seconds"] == PROBE_TIMEOUT_SECONDS


def test_batch_launcher_scope_is_explicit_and_platform_aware(tmp_path):
    launcher = tmp_path / "fake-release.bat"
    launcher.write_bytes(b"@echo off\r\necho SyntheticBatch 1.0\r\n")
    result = capture((str(launcher),), tmp_path, ("information=release",))
    assert result["command_file_kind"] == "batch_launcher"
    assert result["executable_path"] == str(launcher.resolve())
    assert result["executable_sha256"] == hashlib.sha256(launcher.read_bytes()).hexdigest()
    if os.name == "nt":
        assert result["version"] == "SyntheticBatch 1.0"
    else:
        assert result["version"] is None
        assert result["probe"]["status"] == "unsupported"


def test_validation_keeps_working_when_configured_solver_is_absent(multimodal_sample_config, tmp_path, monkeypatch):
    from experiment_to_cpfe import pipeline

    monkeypatch.delenv("EXP2CPFE_ABAQUS_COMMAND", raising=False)
    config = yaml.safe_load(multimodal_sample_config.read_text())
    config["abaqus"]["command"] = ["exp2cpfe-deliberately-absent-abaqus"]
    config["abaqus"]["version_probe_args"] = ["information=release"]
    multimodal_sample_config.write_text(yaml.safe_dump(config))
    run = tmp_path / "run"
    assert pipeline.run_validate(multimodal_sample_config, run)["status"] == "completed"
    manifest = json.loads((run / "reports/run_manifest.json").read_text())
    assert manifest["runtime"]["solver"]["executable_path"] is None
    assert manifest["runtime"]["solver"]["resolution_error"] == "command_not_found"
    assert manifest["schema_version"] == "0.1"


def test_runtime_records_the_parsed_environment_command(multimodal_sample_config, tmp_path, monkeypatch):
    from experiment_to_cpfe import pipeline

    script = tmp_path / "fake version.py"
    script.write_text("print('SyntheticOverride 2.0')\n")
    monkeypatch.setenv("EXP2CPFE_ABAQUS_COMMAND", f'"{sys.executable}" "{script}"')
    config = yaml.safe_load(multimodal_sample_config.read_text())
    config["abaqus"]["version_probe_args"] = ["--version"]
    multimodal_sample_config.write_text(yaml.safe_dump(config))
    run = tmp_path / "run"
    assert pipeline.run_validate(multimodal_sample_config, run)["status"] == "completed"
    fingerprint = json.loads((run / "reports/run_manifest.json").read_text())["runtime"]["solver"]
    assert fingerprint["command"] == [sys.executable, str(script)]
    assert fingerprint["version"] == "SyntheticOverride 2.0"


def test_malformed_environment_command_is_a_fingerprint_diagnostic(multimodal_sample_config, tmp_path, monkeypatch):
    from experiment_to_cpfe import pipeline

    monkeypatch.setenv("EXP2CPFE_ABAQUS_COMMAND", '"unterminated')
    run = tmp_path / "run"
    assert pipeline.run_validate(multimodal_sample_config, run)["status"] == "completed"
    fingerprint = json.loads((run / "reports/run_manifest.json").read_text())["runtime"]["solver"]
    assert fingerprint["executable_path"] is None
    assert "command_parse_error" in fingerprint["resolution_error"]


def test_each_solver_stage_records_replaced_launcher_without_rewriting_history(multimodal_sample_config, tmp_path, monkeypatch):
    from experiment_to_cpfe import pipeline

    monkeypatch.delenv("EXP2CPFE_ABAQUS_COMMAND", raising=False)
    source = Path("tests/fixtures/fake_solver.py").resolve()
    if os.name == "nt":
        launcher = tmp_path / "synthetic-driver.bat"
        launcher.write_text(
            '@echo off\nif "%~1"=="--version" (\n'
            ' echo SyntheticDriver 1.0\n exit /b 0\n)\n'
            f'"{sys.executable}" "{source}" %*\n'
        )
        revision = "\nREM synthetic revision two\n"
    else:
        launcher = tmp_path / "synthetic-driver"
        launcher.write_text(
            '#!/bin/sh\nif [ "$1" = "--version" ]; then\n'
            " echo 'SyntheticDriver 1.0'\n exit 0\nfi\n"
            f'exec {shlex.quote(sys.executable)} {shlex.quote(str(source))} "$@"\n'
        )
        launcher.chmod(0o700)
        revision = "\n# synthetic revision two\n"
    config = yaml.safe_load(multimodal_sample_config.read_text())
    config["abaqus"]["command"] = [str(launcher)]
    config["abaqus"]["version_probe_args"] = ["--version"]
    multimodal_sample_config.write_text(yaml.safe_dump(config))
    run = tmp_path / "run"
    assert pipeline.run_validate(multimodal_sample_config, run)["status"] == "completed"
    initial = json.loads((run / "reports/run_manifest.json").read_text())
    old_digest = hashlib.sha256(launcher.read_bytes()).hexdigest()
    assert initial["runtime"]["solver"]["executable_sha256"] == old_digest
    assert initial["runtime"]["solver"]["version"] == "SyntheticDriver 1.0"
    assert pipeline.run_build_inp(multimodal_sample_config, run)["status"] == "completed"
    first = pipeline.run_abaqus_stage(multimodal_sample_config, run, "datacheck")
    assert first["status"] == "completed"
    assert first["solver_fingerprint"]["executable_sha256"] == old_digest
    assert first["solver_fingerprint"]["version"] == "SyntheticDriver 1.0"
    launcher.write_text(launcher.read_text().replace("SyntheticDriver 1.0", "SyntheticDriver 2.0") + revision)
    new_digest = hashlib.sha256(launcher.read_bytes()).hexdigest()
    second = pipeline.run_abaqus_stage(multimodal_sample_config, run, "analysis")
    assert second["status"] == "completed"
    assert second["solver_fingerprint"]["executable_sha256"] == new_digest != old_digest
    assert second["solver_fingerprint"]["version"] == "SyntheticDriver 2.0"

    def interrupted(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 1)

    monkeypatch.setattr(pipeline, "execute_process", interrupted)
    extraction = pipeline.run_extract_odb(multimodal_sample_config, run)
    assert extraction["status"] == "failed"
    assert extraction["solver_fingerprint"]["executable_sha256"] == new_digest
    assert extraction["solver_fingerprint"]["version"] == "SyntheticDriver 2.0"
    final = json.loads((run / "reports/run_manifest.json").read_text())
    assert final["runtime"] == initial["runtime"]
    assert final["stages"][0] == initial["stages"][0]
    assert all(final["artifacts"][name] == receipt for name, receipt in initial["artifacts"].items())
