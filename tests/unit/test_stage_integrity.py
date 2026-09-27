import json
from pathlib import Path
import sys

import pytest
import yaml


@pytest.fixture
def bound_run(tmp_path, multimodal_sample_config, monkeypatch):
    from experiment_to_cpfe import pipeline

    monkeypatch.delenv("EXP2CPFE_ABAQUS_COMMAND", raising=False)
    payload = yaml.safe_load(multimodal_sample_config.read_text())
    payload["abaqus"]["command"] = [sys.executable, str(Path('tests/fixtures/fake_solver.py').resolve())]
    # Exercise graph-contract failures with PyG export explicitly allowed.
    payload["export"]["formats"] = ["hdf5", "npz", "pyg"]
    multimodal_sample_config.write_text(yaml.safe_dump(payload))
    run = tmp_path / "run"
    assert pipeline.run_validate(multimodal_sample_config, run)["status"] == "completed"
    return multimodal_sample_config, run


@pytest.mark.parametrize("changed", ["config", "source", "template", "normalized"])
def test_changed_validated_input_blocks_build_and_preserves_original_hashes(bound_run, changed):
    from experiment_to_cpfe import pipeline

    config, run = bound_run
    original = json.loads((run/'reports/run_manifest.json').read_text())
    paths = {"config": config, "source": config.parent/'experiment.csv',
             "template": config.parent/'template.inp', "normalized": run/'input/normalized_sample.json'}
    with paths[changed].open('a') as stream:
        stream.write('\n')
    result = pipeline.run_build_inp(config, run)
    assert result['status'] == 'blocked'
    assert any('integrity' in item.lower() for item in result['limitations'])
    assert not (run/'input/model.inp').exists()
    after = json.loads((run/'reports/run_manifest.json').read_text())
    assert after['config_sha256'] == original['config_sha256']
    assert all(after['artifacts'][p] == value for p, value in original['artifacts'].items())


def test_stages_are_isolated_and_both_complete(bound_run):
    from experiment_to_cpfe import pipeline

    config, run = bound_run
    assert pipeline.run_build_inp(config, run)['status'] == 'completed'
    assert pipeline.run_abaqus_stage(config, run, 'datacheck')['status'] == 'completed'
    before = {p.name:p.read_bytes() for p in (run/'solver/datacheck').iterdir() if p.is_file()}
    assert pipeline.run_abaqus_stage(config, run, 'analysis')['status'] == 'completed'
    assert before == {p.name:p.read_bytes() for p in (run/'solver/datacheck').iterdir() if p.is_file()}
    assert list((run/'solver/analysis').glob('*.odb'))
    assert not list((run/'solver').glob('*.odb'))


def test_analysis_without_completed_datacheck_does_not_launch(bound_run, monkeypatch):
    from experiment_to_cpfe import pipeline

    config, run = bound_run
    pipeline.run_build_inp(config, run)
    monkeypatch.setattr(pipeline, 'run_abaqus', lambda *a, **k: pytest.fail('unexpected solver launch'))
    result = pipeline.run_abaqus_stage(config, run, 'analysis')
    assert result['status'] == 'blocked'
    assert any('datacheck' in item.lower() for item in result['limitations'])


def test_modified_inp_blocks_solver_before_launch(bound_run, monkeypatch):
    from experiment_to_cpfe import pipeline

    config, run = bound_run
    pipeline.run_build_inp(config, run)
    with (run/'input/model.inp').open('a') as stream:
        stream.write('** changed after build\n')
    monkeypatch.setattr(pipeline, 'run_abaqus', lambda *a, **k: pytest.fail('unexpected solver launch'))
    result = pipeline.run_abaqus_stage(config, run, 'datacheck')
    assert result['status'] == 'blocked'
    assert not list((run/'solver').iterdir())


def test_completed_stage_is_rejected_before_any_launch_or_report_write(bound_run, monkeypatch):
    from experiment_to_cpfe import pipeline

    config, run = bound_run
    pipeline.run_build_inp(config, run)
    pipeline.run_abaqus_stage(config, run, 'datacheck')
    before = {p.name:p.read_bytes() for p in (run/'reports').iterdir()}
    monkeypatch.setattr(pipeline, 'run_abaqus', lambda *a, **k: pytest.fail('duplicate launch'))
    with pytest.raises(FileExistsError):
        pipeline.run_abaqus_stage(config, run, 'datacheck')
    assert before == {p.name:p.read_bytes() for p in (run/'reports').iterdir()}


def test_downstream_uses_validated_normalized_snapshot(bound_run, monkeypatch):
    from experiment_to_cpfe import pipeline

    config, run = bound_run
    monkeypatch.setattr(pipeline, 'assemble_sample', lambda *a: pytest.fail('re-imported source after validate'))
    assert pipeline.run_build_inp(config, run)['status'] == 'completed'
    assert pipeline.run_export(config, run, 'hdf5')['status'] == 'completed'


def test_datacheck_output_tamper_blocks_analysis(bound_run, monkeypatch):
    from experiment_to_cpfe import pipeline

    config, run = bound_run
    pipeline.run_build_inp(config, run)
    result = pipeline.run_abaqus_stage(config, run, 'datacheck')
    dat = next(Path(p) for p in result['artifacts'] if p.endswith('.dat'))
    dat.write_text('changed')
    monkeypatch.setattr(pipeline, 'run_abaqus', lambda *a, **k: pytest.fail('unverified datacheck'))
    assert pipeline.run_abaqus_stage(config, run, 'analysis')['status'] == 'blocked'


def test_legacy_run_without_binding_is_blocked(bound_run):
    from experiment_to_cpfe import pipeline

    config, run = bound_run
    lock = run/'input/input_lock.json'
    if lock.exists():
        lock.unlink()
    assert pipeline.run_build_inp(config, run)['status'] == 'blocked'


def test_extract_rejects_an_unregistered_odb(bound_run, monkeypatch):
    from experiment_to_cpfe import pipeline

    config, run = bound_run
    (run/'solver/analysis').mkdir()
    (run/'solver/analysis/synthetic.odb').write_bytes(b'not a solver result')
    monkeypatch.setattr(pipeline.subprocess, 'run', lambda *a, **k: pytest.fail('unregistered extraction'))
    assert pipeline.run_extract_odb(config, run)['status'] == 'blocked'


def test_unregistered_extraction_cannot_enter_export(bound_run):
    import shutil
    from experiment_to_cpfe import pipeline

    config, run = bound_run
    shutil.copytree('tests/fixtures/odb_extract_fixture', run/'solver/extracted')
    assert pipeline.run_export(config, run, 'hdf5')['status'] == 'blocked'
    assert not (run/'dataset/sample.h5').exists()


def test_input_changed_during_solver_is_not_recorded_completed(bound_run, monkeypatch):
    from experiment_to_cpfe import pipeline

    config, run = bound_run
    pipeline.run_build_inp(config, run)
    original = pipeline.run_abaqus

    def run_then_change(request):
        result = original(request)
        with (config.parent/'experiment.csv').open('a') as stream:
            stream.write('\n')
        return result

    monkeypatch.setattr(pipeline, 'run_abaqus', run_then_change)
    result = pipeline.run_abaqus_stage(config, run, 'datacheck')
    assert result['status'] == 'failed'
    assert any('integrity' in item for item in result['limitations'])


@pytest.mark.parametrize('invalid', ['hash', 'missing_fields'])
def test_bad_extraction_provenance_fails_and_blocks_export(bound_run, monkeypatch, invalid):
    import shutil
    import subprocess
    from experiment_to_cpfe import pipeline
    from experiment_to_cpfe.provenance.hashing import sha256_file

    config, run = bound_run
    pipeline.run_build_inp(config, run)
    pipeline.run_abaqus_stage(config, run, 'datacheck')
    pipeline.run_abaqus_stage(config, run, 'analysis')

    def extract(command, **kwargs):
        odb = Path(command[command.index('--odb')+1])
        assert odb.parent == run/'solver/analysis'
        output = Path(command[command.index('--output-dir')+1])
        shutil.copytree('tests/fixtures/odb_extract_fixture', output)
        metadata = json.loads((output/'metadata.json').read_text())
        metadata['odb_sha256'] = '0'*64 if invalid == 'hash' else sha256_file(odb)
        metadata['missing_fields'] = ['S'] if invalid == 'missing_fields' else []
        (output/'metadata.json').write_text(json.dumps(metadata))
        return subprocess.CompletedProcess(command, 0, '', '')

    monkeypatch.setattr(pipeline, 'execute_process', extract)
    assert pipeline.run_extract_odb(config, run)['status'] == 'failed'
    assert pipeline.run_export(config, run, 'hdf5')['status'] == 'blocked'


def test_failed_validation_cannot_produce_inp(tmp_path, multimodal_sample_config):
    from experiment_to_cpfe import pipeline

    with (multimodal_sample_config.parent/'orientations.csv').open('a') as stream:
        stream.write('1,1,1,0,0,0\n')
    run = tmp_path/'invalid-data'
    assert pipeline.run_validate(multimodal_sample_config, run)['status'] == 'failed'
    assert pipeline.run_build_inp(multimodal_sample_config, run)['status'] == 'blocked'
    assert not (run/'input/model.inp').exists()


def test_npz_stage_reads_canonical_hdf5_not_reassembled_inputs(bound_run,monkeypatch):
    from experiment_to_cpfe import pipeline

    config,run=bound_run
    assert pipeline.run_export(config,run,'hdf5')['status']=='completed'
    monkeypatch.setattr(pipeline,'load_sample_json',lambda *a: pytest.fail('derived export reread normalized inputs'))
    monkeypatch.setattr(pipeline,'load_extraction_bundle',lambda *a: pytest.fail('derived export reread extraction'))
    assert pipeline.run_export(config,run,'npz')['status']=='completed'


def test_missing_graph_records_blocked_pyg_export(bound_run):
    from experiment_to_cpfe import pipeline
    config,run=bound_run
    pipeline.run_export(config,run,'hdf5')
    result=pipeline.run_export(config,run,'pyg')
    assert result['status']=='blocked'
    assert any('graph' in item for item in result['limitations'])
    assert not (run/'dataset/sample.pt').exists()
