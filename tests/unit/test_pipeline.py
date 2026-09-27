import json
import shutil
import pytest


def test_validate_build_and_export_commands_write_stage_artifacts(
    tmp_path,
    multimodal_sample_config,
):
    from experiment_to_cpfe.cli import main

    run_dir = tmp_path / "offline-run"
    config = str(multimodal_sample_config)

    assert main(["validate", "--config", config, "--run-dir", str(run_dir)]) == 0
    assert main(["build-inp", "--config", config, "--run-dir", str(run_dir)]) == 0
    assert main(["export", "--config", config, "--run-dir", str(run_dir), "--format", "hdf5"]) == 0

    assert (run_dir / "reports" / "validation.json").exists()
    assert (run_dir / "reports" / "solver_readiness.json").exists()
    assert (run_dir / "reports" / "run_manifest.json").exists()
    assert (run_dir / "reports" / "qa_report.md").exists()
    assert (run_dir / "input" / "model.inp").exists()
    assert (run_dir / "dataset" / "sample.h5").exists()


def test_validate_refuses_to_overwrite_existing_run(
    tmp_path,
    multimodal_sample_config,
):
    from experiment_to_cpfe.cli import main

    run_dir = tmp_path / "offline-run"
    config = str(multimodal_sample_config)
    assert main(["validate", "--config", config, "--run-dir", str(run_dir)]) == 0
    manifest = (run_dir / "reports" / "run_manifest.json").read_bytes()

    assert main(["validate", "--config", config, "--run-dir", str(run_dir)]) == 1
    assert (run_dir / "reports" / "run_manifest.json").read_bytes() == manifest


def test_inspect_returns_manifest_summary(tmp_path, multimodal_sample_config, capsys):
    from experiment_to_cpfe.cli import main

    run_dir = tmp_path / "offline-run"
    config = str(multimodal_sample_config)
    assert main(["validate", "--config", config, "--run-dir", str(run_dir)]) == 0
    assert "validate: completed" in capsys.readouterr().out
    assert main(["inspect", "--run-dir", str(run_dir)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stages"][-1]["stage"] == "validate"


def test_unknown_command_returns_usage_error():
    from experiment_to_cpfe.cli import main

    assert main(["not-a-command"]) == 2


def test_hdf5_export_merges_extracted_simulation_bundle(
    tmp_path,
    multimodal_sample_config,
    monkeypatch,
):
    from pathlib import Path
    import subprocess
    import sys
    import yaml
    from experiment_to_cpfe import pipeline
    from experiment_to_cpfe.cli import main
    from experiment_to_cpfe.datasets.hdf5 import read_hdf5
    from experiment_to_cpfe.provenance.hashing import sha256_file

    run_dir = tmp_path / "offline-run"
    monkeypatch.delenv("EXP2CPFE_ABAQUS_COMMAND", raising=False)
    payload = yaml.safe_load(multimodal_sample_config.read_text())
    payload['abaqus']['command'] = [sys.executable, str(Path('tests/fixtures/fake_solver.py').resolve())]
    payload['abaqus']['required_fields'] = ['S']
    payload['abaqus']['extraction_position'] = 'native'
    payload['abaqus']['extraction_max_records'] = 42
    payload['abaqus']['field_units'] = {'S':'Pa','LE':'1'}
    multimodal_sample_config.write_text(yaml.safe_dump(payload))
    config = str(multimodal_sample_config)
    assert main(["validate", "--config", config, "--run-dir", str(run_dir)]) == 0
    assert main(["build-inp", "--config", config, "--run-dir", str(run_dir)]) == 0
    for stage in ('datacheck', 'analysis'):
        assert main(['run-abaqus', '--config', config, '--run-dir', str(run_dir), '--stage', stage]) == 0

    def extract(command, **kwargs):
        assert command[command.index('--position')+1] == 'native'
        assert command[command.index('--max-records')+1] == '42'
        odb = Path(command[command.index('--odb')+1])
        assert odb.parent == run_dir/'solver/analysis'
        extracted = Path(command[command.index('--output-dir')+1])
        shutil.copytree('tests/fixtures/odb_extract_fixture', extracted)
        metadata = json.loads((extracted/'metadata.json').read_text())
        metadata['odb_sha256'] = sha256_file(odb)
        metadata['missing_fields'] = []
        metadata['requested_fields'] = ['S']
        (extracted/'metadata.json').write_text(json.dumps(metadata))
        return subprocess.CompletedProcess(command, 0, '', '')

    monkeypatch.setattr(pipeline, 'execute_process', extract)
    assert main(['extract-odb', '--config', config, '--run-dir', str(run_dir)]) == 0

    assert main(["export", "--config", config, "--run-dir", str(run_dir), "--format", "hdf5"]) == 0
    restored = read_hdf5(run_dir / "dataset" / "sample.h5")

    assert "simulation_records" in restored.tables
    assert any(asset.source_kind.value == "simulated" for asset in restored.assets)
    assert any(source.kind.value == "simulated" for source in restored.metadata.sources)


@pytest.mark.parametrize("missing", ["units", "material"])
def test_solver_stage_blocks_incomplete_contract_without_launch(
    tmp_path, multimodal_sample_config, monkeypatch, missing,
):
    import yaml
    from experiment_to_cpfe import pipeline

    payload = yaml.safe_load(multimodal_sample_config.read_text())
    if missing == "units":
        payload["sample"]["unit_system"] = {}
    else:
        payload["solver_inputs"]["material_parameters"] = {}
    multimodal_sample_config.write_text(yaml.safe_dump(payload))
    run_dir = tmp_path / "blocked"
    pipeline.run_validate(multimodal_sample_config, run_dir)
    (run_dir / "input/model.inp").write_text('*Heading\nUnverified native input\n')

    def unexpected_launch(*args, **kwargs):
        raise AssertionError("Incomplete contract reached the solver")

    monkeypatch.setattr(pipeline, "run_abaqus", unexpected_launch)
    result = pipeline.run_abaqus_stage(multimodal_sample_config, run_dir, "datacheck")
    assert result["status"] == "blocked"
    assert result["limitations"]
    receipt = json.loads((run_dir / "reports/run_manifest.json").read_text())
    assert receipt["stages"][-1]["status"] == "blocked"
    assert not list((run_dir / "solver").iterdir())
