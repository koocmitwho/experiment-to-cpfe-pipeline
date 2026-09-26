"""Status declarations must not silently outrun their evidence or review."""
import hashlib
import importlib
import json
from pathlib import Path

import pytest


def _api():
    try:
        return importlib.import_module('experiment_to_cpfe.intake_status')
    except ModuleNotFoundError as exc:
        if exc.name != 'experiment_to_cpfe.intake_status':
            raise
        pytest.fail('intake status reporting is not implemented')


def _config(tmp_path):
    evidence = tmp_path / 'review.txt'
    evidence.write_bytes(b'Synthetic table: sample identity and MPa units reviewed.\n')
    config = {
        'version': 1,
        'handoff_id': 'synthetic-table-demo',
        'purpose': 'Review a synthetic table only; no solver is required.',
        'evidence_scope': 'synthetic_mechanism_only',
        'checkpoints': [{
            'id': 'raw_to_semantics',
            'status': 'ready',
            'reviewer': 'Synthetic example reviewer',
            'basis': 'The explicit table metadata records identities and units.',
            'conditions': [],
            'blockers': [],
            'evidence': [{'path': 'review.txt', 'sha256': hashlib.sha256(evidence.read_bytes()).hexdigest()}],
        }],
    }
    return config


def _write(tmp_path, config):
    path = tmp_path / 'intake.json'
    path.write_text(json.dumps(config), encoding='utf-8')
    return path


def test_pure_tabular_subset_reports_human_status_without_solver_or_scientific_certification(tmp_path):
    config = _config(tmp_path)
    source = _write(tmp_path, config)
    before = (tmp_path / 'review.txt').read_bytes()
    result = _api().run_intake_status(source, tmp_path / 'result')
    saved = json.loads((tmp_path / 'result/intake-status.json').read_text(encoding='utf-8'))
    assert result == saved
    assert saved['selected_checkpoint_count'] == 1
    assert saved['unselected_checkpoints_assessed'] is False
    assert saved['status_counts'] == {'ready': 1, 'conditional': 0, 'awaiting_information': 0, 'not_applicable': 0}
    assert saved['scientific_validity'] == 'not_assessed'
    assert saved['downstream_execution'] == 'not_started'
    assert saved['checkpoints'][0]['evidence_integrity'] == 'verified'
    assert saved['source_config']['sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert saved['checkpoints'][0]['evidence'][0]['path'] == str((tmp_path / 'review.txt').resolve())
    report = (tmp_path / 'result/REPORT.md').read_text(encoding='utf-8')
    assert 'Synthetic example reviewer' in report
    assert 'synthetic_mechanism_only' in report
    assert (tmp_path / 'review.txt').read_bytes() == before


@pytest.mark.parametrize(('status', 'conditions', 'blockers', 'reason', 'expected_integrity'), [
    ('conditional', ['Unit conversion requires reviewer sign-off.'], [], None, 'verified'),
    ('awaiting_information', [], ['Missing original units.'], None, 'not_provided'),
    ('not_applicable', [], [], 'This table-only study has no solver stage.', 'not_provided'),
])
def test_explicit_unready_and_inapplicable_records_remain_visible(tmp_path, status, conditions, blockers, reason, expected_integrity):
    config = _config(tmp_path)
    item = config['checkpoints'][0]
    item.update(status=status, conditions=conditions, blockers=blockers)
    if status != 'conditional':
        item['evidence'] = []
    if reason:
        item['not_applicable_reason'] = reason
    result = _api().run_intake_status(_write(tmp_path, config), tmp_path / 'result')
    assert result['checkpoints'][0]['status'] == status
    assert result['checkpoints'][0]['conditions'] == conditions
    assert result['checkpoints'][0]['blockers'] == blockers
    assert result['checkpoints'][0]['evidence_integrity'] == expected_integrity


@pytest.mark.parametrize('change', [
    {'status': 'ready', 'evidence': []},
    {'status': 'ready', 'blockers': ['Units are unknown.']},
    {'status': 'ready', 'conditions': ['Needs another review.']},
    {'status': 'conditional', 'conditions': []},
    {'status': 'awaiting_information', 'blockers': []},
    {'status': 'not_applicable'},
    {'status': 'not_applicable', 'not_applicable_reason': 'Not relevant.', 'conditions': ['Still needed.']},
    {'status': 'not_applicable', 'not_applicable_reason': 'Not relevant.', 'blockers': ['Still missing.']},
    {'status': 'ready', 'not_applicable_reason': 'Not relevant.'},
    {'status': 'pending'},
    {'reviewer': '  '},
    {'basis': ''},
    {'conditions': ['']},
    {'blockers': 'Missing units'},
    {'id': 'custom_solver_stage'},
    {'unexpected': True},
])
def test_rejects_incomplete_or_contradictory_human_review(tmp_path, change):
    config = _config(tmp_path)
    config['checkpoints'][0].update(change)
    with pytest.raises(ValueError):
        _api().run_intake_status(_write(tmp_path, config), tmp_path / 'result')
    assert not (tmp_path / 'result').exists()


@pytest.mark.parametrize('change', [
    {'version': True}, {'version': 2}, {'evidence_scope': 'unknown'},
    {'handoff_id': ''}, {'purpose': ''}, {'unknown': 1}, {'checkpoints': []},
])
def test_rejects_invalid_config_without_outputs(tmp_path, change):
    config = _config(tmp_path)
    config.update(change)
    with pytest.raises(ValueError):
        _api().validate_intake_status_config(_write(tmp_path, config))
    assert not (tmp_path / 'result').exists()


def test_each_of_the_six_template_checkpoints_can_be_selected_independently(tmp_path):
    config = _config(tmp_path)
    ids = ['raw_to_semantics', 'semantics_to_sample_package', 'sample_package_to_solver',
           'solver_to_numerical_validation', 'simulation_training_to_experimental_evaluation',
           'experimental_evaluation_to_applicability']
    config['checkpoints'] = [dict(config['checkpoints'][0], id=value) for value in ids]
    result = _api().run_intake_status(_write(tmp_path, config), tmp_path / 'result')
    assert result['selected_checkpoint_count'] == 6
    assert {item['id'] for item in result['checkpoints']} == set(ids)


def test_duplicate_checkpoint_is_rejected(tmp_path):
    config = _config(tmp_path)
    config['checkpoints'].append(dict(config['checkpoints'][0]))
    with pytest.raises(ValueError, match='duplicate'):
        _api().validate_intake_status_config(_write(tmp_path, config))


def test_duplicate_json_key_is_not_silently_overwritten(tmp_path):
    source = _write(tmp_path, _config(tmp_path))
    source.write_text(source.read_text().replace('"version": 1', '"version": 1, "version": 1'), encoding='utf-8')
    with pytest.raises(ValueError, match='duplicate'):
        _api().validate_intake_status_config(source)


def test_evidence_drift_is_rejected_before_output_creation(tmp_path):
    source = _write(tmp_path, _config(tmp_path))
    (tmp_path / 'review.txt').write_text('Units are no longer known.', encoding='utf-8')
    with pytest.raises(ValueError, match='SHA256'):
        _api().run_intake_status(source, tmp_path / 'result')
    assert not (tmp_path / 'result').exists()


@pytest.mark.parametrize('change', [
    {'sha256': 'not-a-digest'}, {'path': ''}, {'unknown': 1}, {'path': '.'}, {'path': 'missing.txt'},
])
def test_rejects_bad_explicit_evidence(tmp_path, change):
    config = _config(tmp_path)
    config['checkpoints'][0]['evidence'][0].update(change)
    with pytest.raises(ValueError):
        _api().validate_intake_status_config(_write(tmp_path, config))


@pytest.mark.parametrize(('name', 'content'), [
    ('receipt.json', b'x' * (1024 * 1024 + 1)),
    ('model.pt', b'serialized model'),
    ('review.txt', b'\xff\xfe\xfd'),
], ids=['oversized', 'model_binary', 'not_utf8'])
def test_evidence_must_be_small_readable_metadata(tmp_path, name, content):
    config = _config(tmp_path)
    evidence = tmp_path / name
    evidence.write_bytes(content)
    config['checkpoints'][0]['evidence'] = [{'path': name, 'sha256': hashlib.sha256(content).hexdigest()}]
    with pytest.raises(ValueError):
        _api().run_intake_status(_write(tmp_path, config), tmp_path / 'result')
    assert not (tmp_path / 'result').exists()


def test_receipt_embedded_model_truth_and_response_paths_are_not_followed(tmp_path):
    config = _config(tmp_path)
    receipt = tmp_path / 'receipt.json'
    receipt.write_text(json.dumps({'model': 'missing-model.pt', 'truth': 'sealed/missing-truth.h5',
                                   'response': 'sealed/missing-response.npy'}), encoding='utf-8')
    config['checkpoints'][0]['evidence'] = [{'path': 'receipt.json', 'sha256': hashlib.sha256(receipt.read_bytes()).hexdigest()}]
    result = _api().run_intake_status(_write(tmp_path, config), tmp_path / 'result')
    assert result['checkpoints'][0]['evidence_integrity'] == 'verified'
    assert set(path.name for path in (tmp_path / 'result').iterdir()) == {'REPORT.md', 'intake-status.json'}
    assert not (tmp_path / 'sealed').exists()


def test_existing_output_directory_is_never_reused(tmp_path):
    source = _write(tmp_path, _config(tmp_path))
    output = tmp_path / 'result'
    output.mkdir()
    marker = output / 'keep.txt'
    marker.write_text('original', encoding='utf-8')
    with pytest.raises(ValueError, match='exist'):
        _api().run_intake_status(source, output)
    assert marker.read_text() == 'original'
    assert list(output.iterdir()) == [marker]
