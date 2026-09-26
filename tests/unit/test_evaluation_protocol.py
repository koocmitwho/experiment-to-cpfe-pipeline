"""Protocol facts must not turn aliases or metadata into scientific validation."""
import copy
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path

import pytest


def api():
    name = 'experiment_to_cpfe.evaluation_protocol'
    assert importlib.util.find_spec(name) is not None, 'evaluation protocol behavior is not implemented'
    return importlib.import_module(name)


def fixture_config():
    return {
        'version': 1,
        'purpose': 'Count a synthetic non-RVE coupon example',
        'claim': 'Transfer between explicitly held-out manufacturing lots',
        'population': 'Four synthetic coupon conditions from three declared lots',
        'data_kind': 'synthetic',
        'declaration_timing': 'retrospective',
        'identity_definition': 'Source coupon plus load programme identifies one condition',
        'group_definition': 'All coupons in a manufacturing lot share one statistical group',
        'record_unit': 'sensor observation',
        'holdout_axes': ['lot'],
        'scope_limits': ['Identity-only fixture; no real experiment or model validation'],
        'cases': [
            {'case_id': 'a', 'identity': {'coupon': 'a', 'load': 'tension'}, 'group_id': 'lot-A',
             'split': 'train', 'axes': {'lot': 'A', 'material': 'synthetic-alloy'}, 'records': ['t0', 't1']},
            {'case_id': 'b', 'identity': {'coupon': 'b', 'load': 'tension'}, 'group_id': 'lot-A',
             'split': 'train', 'axes': {'lot': 'A', 'material': 'synthetic-alloy'}, 'records': ['t0']},
            {'case_id': 'c', 'identity': {'coupon': 'c', 'load': 'tension'}, 'group_id': 'lot-B',
             'split': 'validation', 'axes': {'lot': 'B', 'material': 'synthetic-alloy'}, 'records': ['t0', 't1']},
            {'case_id': 'd', 'identity': {'coupon': 'd', 'load': 'tension'}, 'group_id': 'lot-C',
             'split': 'validation', 'axes': {'lot': 'C', 'material': 'synthetic-alloy'}, 'records': ['t0']},
        ],
        'metrics': [],
        'sources': [],
    }


def write_config(tmp_path, config):
    path = tmp_path / 'protocol.json'
    path.write_text(json.dumps(config), encoding='utf-8')
    return path


def add_metric(tmp_path, config, value=2.5, unit='MPa'):
    metric_path = tmp_path / 'metrics.json'
    metric_path.write_text(json.dumps({'validation': {'rmse': value, 'unit': unit},
                                      'model_path': 'DO-NOT-OPEN/model.pt',
                                      'truth_path': 'DO-NOT-OPEN/response.h5'}), encoding='utf-8')
    config['metrics'] = [{'metric_id': 'validation-rmse', 'path': 'metrics.json',
                          'sha256': hashlib.sha256(metric_path.read_bytes()).hexdigest(),
                          'value_pointer': '/validation/rmse', 'unit_pointer': '/validation/unit',
                          'unit': 'MPa', 'split': 'validation',
                          'threshold': {'operator': 'le', 'value': 3.0, 'unit': 'MPa'}}]
    return metric_path


def test_alias_and_retry_do_not_increase_hand_counted_conditions(tmp_path):
    cfg = fixture_config()
    for name in ('a-alias', 'a-retry'):
        alias = copy.deepcopy(cfg['cases'][0]); alias.update(case_id=name)
        cfg['cases'].append(alias)
    result = api().run_evaluation_protocol(write_config(tmp_path, cfg), tmp_path / 'run')
    assert result['counts'] == {'manifest_entries': 6, 'unique_conditions': 4,
                                'statistical_groups': 3, 'expanded_records': 6,
                                'record_unit': 'sensor observation'}
    assert result['splits']['train'] == {'unique_conditions': 2, 'statistical_groups': 1,
                                       'expanded_records': 3}
    assert result['holdout_axes']['lot']['status'] == 'metadata_supported'
    assert result['scientific_claim_status'] == 'not_established_by_metadata'
    assert result['declaration_timing'] == 'retrospective'
    assert json.loads((tmp_path / 'run/evaluation-protocol.json').read_text()) == result
    assert (tmp_path / 'run/REPORT.md').is_file()
    assert (tmp_path / 'run/config.json').is_file()


@pytest.mark.parametrize('mutation', ['same_name_other_identity', 'same_identity_other_split',
                                     'same_identity_other_group', 'same_identity_other_axis',
                                     'group_across_splits', 'duplicate_record'])
def test_ambiguous_identity_and_leakage_fail_closed(tmp_path, mutation):
    cfg = fixture_config()
    if mutation == 'same_name_other_identity':
        cfg['cases'][1]['case_id'] = 'a'
    elif mutation == 'same_identity_other_split':
        cfg['cases'][2]['identity'] = cfg['cases'][0]['identity']
    elif mutation == 'same_identity_other_group':
        cfg['cases'][1]['identity'] = cfg['cases'][0]['identity']
        cfg['cases'][1]['group_id'] = 'different-group'
    elif mutation == 'same_identity_other_axis':
        cfg['cases'][1]['identity'] = cfg['cases'][0]['identity']
        cfg['cases'][1]['axes']['material'] = 'other-alloy'
    elif mutation == 'group_across_splits':
        cfg['cases'][2]['group_id'] = 'lot-A'
    elif mutation == 'duplicate_record':
        cfg['cases'][0]['records'].append('t0')
    with pytest.raises(ValueError):
        api().run_evaluation_protocol(write_config(tmp_path, cfg), tmp_path / 'run')
    assert not (tmp_path / 'run').exists()


@pytest.mark.parametrize('axes,remove,status', [([], False, 'not_verified'),
    (['material'], False, 'not_verified'), (['lot'], True, 'not_verified')])
def test_missing_or_single_valued_axis_never_verifies_generalization(tmp_path, axes, remove, status):
    cfg = fixture_config(); cfg['holdout_axes'] = axes
    if remove:
        del cfg['cases'][-1]['axes']['lot']
    result = api().run_evaluation_protocol(write_config(tmp_path, cfg), tmp_path / 'run')
    assert result['holdout_status'] == status
    assert result['scientific_claim_status'] == 'not_established_by_metadata'


def test_overlapping_axis_values_are_not_a_holdout(tmp_path):
    cfg = fixture_config(); cfg['cases'][2]['axes']['lot'] = 'A'
    result = api().run_evaluation_protocol(write_config(tmp_path, cfg), tmp_path / 'run')
    assert result['holdout_axes']['lot']['status'] == 'not_verified'


def test_metric_is_bound_with_finite_value_unit_pointer_and_threshold(tmp_path):
    cfg = fixture_config(); add_metric(tmp_path, cfg)
    result = api().run_evaluation_protocol(write_config(tmp_path, cfg), tmp_path / 'run')
    metric = result['metric_evidence'][0]
    assert metric['value'] == 2.5
    assert metric['threshold_status'] == 'met'
    assert metric['unit'] == 'MPa'
    assert result['scientific_claim_status'] == 'not_established_by_metadata'
    assert {Path(x['path']).name for x in result['inputs_read']} == {'protocol.json', 'metrics.json'}


@pytest.mark.parametrize('value', [True, '2.5', float('nan'), float('inf'), [2.5], None])
def test_metric_rejects_nonfinite_or_non_numeric_saved_value(tmp_path, value):
    cfg = fixture_config(); add_metric(tmp_path, cfg, value=value)
    with pytest.raises(ValueError):
        api().run_evaluation_protocol(write_config(tmp_path, cfg), tmp_path / 'run')


@pytest.mark.parametrize('mutation', ['unit', 'threshold_unit', 'sha256', 'pointer', 'split'])
def test_metric_evidence_mismatch_is_rejected(tmp_path, mutation):
    cfg = fixture_config(); path = add_metric(tmp_path, cfg)
    if mutation == 'unit': cfg['metrics'][0]['unit'] = 'Pa'
    if mutation == 'threshold_unit': cfg['metrics'][0]['threshold']['unit'] = 'Pa'
    if mutation == 'sha256': path.write_text('{}')
    if mutation == 'pointer': cfg['metrics'][0]['value_pointer'] = '/missing'
    if mutation == 'split': cfg['metrics'][0]['split'] = 'test'
    with pytest.raises(ValueError):
        api().run_evaluation_protocol(write_config(tmp_path, cfg), tmp_path / 'run')


def test_preregistered_claim_requires_explicit_registration_evidence(tmp_path):
    cfg = fixture_config(); cfg['declaration_timing'] = 'preregistered_claim'
    with pytest.raises(ValueError):
        api().validate_evaluation_protocol_config(write_config(tmp_path, cfg))


def test_preflight_validates_without_creating_output(tmp_path):
    cfg = fixture_config(); add_metric(tmp_path, cfg)
    parsed = api().validate_evaluation_protocol_config(write_config(tmp_path, cfg))
    assert parsed.claim == cfg['claim']
    assert sorted(p.name for p in tmp_path.iterdir()) == ['metrics.json', 'protocol.json']


def test_existing_run_is_never_overwritten(tmp_path):
    run = tmp_path / 'run'; run.mkdir(); (run / 'keep.txt').write_text('preserve')
    with pytest.raises((ValueError, FileExistsError)):
        api().run_evaluation_protocol(write_config(tmp_path, fixture_config()), run)
    assert (run / 'keep.txt').read_text() == 'preserve'


def test_saved_config_resolves_evidence_paths_for_replay(tmp_path):
    cfg = fixture_config(); add_metric(tmp_path, cfg)
    module = api()
    module.run_evaluation_protocol(write_config(tmp_path, cfg), tmp_path / 'run')
    result = module.run_evaluation_protocol(tmp_path / 'run/config.json', tmp_path / 'replay')
    assert result['metric_evidence'][0]['value'] == 2.5


def test_mixed_identity_key_sets_are_rejected(tmp_path):
    cfg = fixture_config(); cfg['cases'][1]['identity']['alias'] = 'could-hide-duplicate'
    with pytest.raises(ValueError):
        api().validate_evaluation_protocol_config(write_config(tmp_path, cfg))


def test_duplicate_json_keys_are_rejected_as_ambiguous(tmp_path):
    cfg = fixture_config(); path = write_config(tmp_path, cfg)
    path.write_text(path.read_text().replace('"version": 1', '"version": 9, "version": 1'))
    with pytest.raises(ValueError):
        api().validate_evaluation_protocol_config(path)


def test_preregistration_evidence_does_not_independently_verify_timing(tmp_path):
    cfg = fixture_config(); path = tmp_path / 'registration.json'; path.write_text('{"claim": "earlier"}')
    cfg['declaration_timing'] = 'preregistered_claim'
    cfg['registration_evidence'] = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                    'purpose': 'Caller supplied registration statement'}
    result = api().run_evaluation_protocol(write_config(tmp_path, cfg), tmp_path / 'run')
    assert result['registration_evidence']['timing_independently_verified'] is False


def test_explicit_source_receipt_is_hashed_without_following_links(tmp_path):
    cfg = fixture_config(); path = tmp_path / 'identity-receipt.json'
    path.write_text('{"response_path": "DO-NOT-OPEN/response.h5", "model_path": "missing.pt"}')
    cfg['sources'] = [{'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                       'purpose': 'Identity-only source receipt'}]
    result = api().run_evaluation_protocol(write_config(tmp_path, cfg), tmp_path / 'run')
    assert len(result['inputs_read']) == 2
    path.write_text('{}')
    with pytest.raises(ValueError):
        api().validate_evaluation_protocol_config(tmp_path / 'protocol.json')


@pytest.mark.parametrize('mutation', ['empty_identity', 'empty_group', 'empty_record_unit',
                                     'negative_count', 'numeric_record', 'unknown_field'])
def test_invalid_identity_count_and_contract_are_rejected(tmp_path, mutation):
    cfg = fixture_config()
    if mutation == 'empty_identity': cfg['cases'][0]['identity'] = {}
    if mutation == 'empty_group': cfg['cases'][0]['group_id'] = ''
    if mutation == 'empty_record_unit': cfg['record_unit'] = ''
    if mutation == 'negative_count': cfg['cases'][0]['records'] = -1
    if mutation == 'numeric_record': cfg['cases'][0]['records'] = [True]
    if mutation == 'unknown_field': cfg['auto_load_model'] = True
    with pytest.raises(ValueError):
        api().run_evaluation_protocol(write_config(tmp_path, cfg), tmp_path / 'run')
