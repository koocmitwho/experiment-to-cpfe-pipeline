"""Synthetic behavior tests: declarations do not establish experimental truth."""
import copy
from pathlib import Path

import pytest

from literature_fixtures import collection
from experiment_to_cpfe.datasets.training import build_training_dataset
from experiment_to_cpfe.datasets.hdf5 import read_hdf5, write_hdf5


def task_contract():
    return dict(version=1, purpose='synthetic force curve', data_kind='synthetic',
        prediction_time=dict(value=0., unit='s', reference='loading start'),
        inputs={'x': dict(source='prescribed command', role='predictor', availability='confirmed',
            available_at=0., evidence='synthetic command known before loading')},
        targets={'y': dict(quantity='force', unit='N', entity='specimen', spatial_support='whole specimen',
            coordinate_frame='scalar', component_convention='scalar axial force',
            time_window=dict(start=0., stop=3., unit='s', reference='loading start'),
            basis='synthetic equation, not instrument data')},
        context_requirements={'preload': ['confirmed', 'not_applicable']},
        independence_axes={'specimen': '/sample_metadata/experiment_id'})


def build_config(tmp_path, *, strict=True):
    cfg = collection(tmp_path/'raw', ['a', 'b', 'c'], offsets=[0., .1, .2])
    cfg['version'] = 2
    for i, item in enumerate(cfg['inputs']):
        item['split'] = 'train' if i < 2 else 'validation'
    if strict:
        cfg['task_contract'] = task_contract()
    return cfg


def edit_sample(cfg, index, edit):
    path = Path(cfg['inputs'][index]['path'])
    sample = read_hdf5(path)
    edit(sample)
    updated = path.with_stem(path.stem + '-edited')
    write_hdf5(sample, updated)
    cfg['inputs'][index]['path'] = str(updated)


def test_legacy_keeps_numerical_path_but_is_explicitly_unassessed(tmp_path):
    data = build_training_dataset(build_config(tmp_path, strict=False), base_dir=tmp_path)
    assert data.metadata['task_assessment']['status'] == 'legacy_unassessed'
    assert data.features.shape == (12, 1)


@pytest.mark.parametrize('change,reason', [
    ({'role':'label_only'}, 'input role'),
    ({'role':'target_derived'}, 'input role'),
    ({'role':'future_response'}, 'input role'),
    ({'availability':'unavailable'}, 'unavailable input'),
    ({'available_at':1.}, 'prediction time'),
])
def test_known_unusable_inputs_are_rejected_before_training(tmp_path, change, reason):
    cfg = build_config(tmp_path)
    cfg['task_contract']['inputs']['x'].update(change)
    with pytest.raises(ValueError, match=reason):
        build_training_dataset(cfg, base_dir=tmp_path)


def test_unknown_availability_and_missing_context_are_conditional_not_ready(tmp_path):
    cfg = build_config(tmp_path)
    cfg['task_contract']['inputs']['x'].update(availability='unconfirmed', available_at=None)
    data = build_training_dataset(cfg, base_dir=tmp_path)
    assessment = data.metadata['task_assessment']
    assert assessment['status'] == 'conditional'
    assert assessment['unconfirmed_inputs'] == ['x']
    assert len(assessment['context_gaps']) == 3
    assert assessment['physical_validity'] == 'not_established'


def test_context_extensions_roundtrip_and_only_selected_requirements_apply(tmp_path):
    from experiment_to_cpfe.datasets.experiment_context import parse_experiment_context
    cfg = build_config(tmp_path)
    for i, item in enumerate(cfg['inputs']):
        values = dict(sample_id=dict(status='confirmed', value=item['sample_id'], evidence='fixture'),
            preload=dict(status='not_applicable', evidence='synthetic formula has no preload'),
            hold_relaxation=dict(status='unconfirmed', value={'duration':12., 'unit':'s'}, evidence='draft record'),
            measurement_timing=dict(status='confirmed', value={'times':[0, 1, 2, 3], 'unit':'s'}, evidence='synthetic grid'),
            preprocessing=dict(status='confirmed', value=[{'operation':'identity', 'basis':'raw numeric fixture', 'fit_role':'not_fitted'}], evidence='no numerical change'))
        context = parse_experiment_context(values, sample_id=item['sample_id'], raw_metadata={'untouched':'原始字段'})
        assert context['fields']['hold_relaxation']['value']['duration'] == 12.
        assert context['fields']['temperature']['status'] == 'unavailable'
        edit_sample(cfg, i, lambda s: s.solver_inputs.update(experiment_context=context))
    data = build_training_dataset(cfg, base_dir=tmp_path)
    assert data.metadata['task_assessment']['status'] == 'declared_ready'
    assert data.metadata['sources'][0]['solver_inputs']['experiment_context']['raw_metadata'] == {'untouched':'原始字段'}


@pytest.mark.parametrize('strict', [True, False])
def test_renaming_target_column_cannot_make_a_training_feature(tmp_path, strict):
    cfg = build_config(tmp_path, strict=strict)
    cfg['layouts']['table']['columns']['x'] = copy.deepcopy(cfg['layouts']['table']['columns']['y'])
    cfg['features'][0]['unit'] = 'N'
    with pytest.raises(ValueError, match='target contamination'):
        build_training_dataset(cfg, base_dir=tmp_path)


def test_target_ancestor_cannot_be_selected_as_training_input(tmp_path):
    cfg = build_config(tmp_path)
    def mark(s):
        s.assets = (s.assets[0].model_copy(update={'descriptive_metadata':{
            'table_name':'measured_observations', 'meaning':{'role':'target', 'split':'train', 'group_id':'a'}}}),)
    edit_sample(cfg, 0, mark)
    with pytest.raises(ValueError, match='target asset'):
        build_training_dataset(cfg, base_dir=tmp_path)


def test_same_specimen_renamed_to_another_group_is_not_independent(tmp_path):
    cfg = build_config(tmp_path)
    cfg['group_by'] = 'explicit'
    for item in cfg['inputs']:
        item['group_id'] = item['sample_id']
    edit_sample(cfg, 2, lambda s: setattr(s.metadata, 'experiment_id', 'a'))
    with pytest.raises(ValueError, match='independence axis'):
        build_training_dataset(cfg, base_dir=tmp_path)


def test_feature_root_leakage_is_rejected_even_with_distinct_target_roots(tmp_path):
    cfg = build_config(tmp_path)
    original = read_hdf5(cfg['inputs'][0]['path']).assets[0]
    def reuse(s):
        # Add a selected feature root shared with train; truth still has its own root.
        feature = original.model_copy(update={'asset_id':'feature-root'})
        s.assets = (*s.assets, feature)
    edit_sample(cfg, 2, reuse)
    cfg['layouts']['leak'] = copy.deepcopy(cfg['layouts']['table'])
    # Give the feature its own table so source_asset_id selects the reused ancestor.
    def rows(s):
        s.tables['simulation_records'] = [dict(row_id=str(j), x=float(j), source_asset_id='feature-root', source_kind='input') for j in range(4)]
        s.assets = tuple(a.model_copy(update={'descriptive_metadata':{'table_name':'simulation_records'}}) if a.asset_id=='feature-root' else a for a in s.assets)
    edit_sample(cfg, 2, rows)
    cfg['layouts']['leak']['columns']['x']['table'] = 'simulation_records'
    cfg['inputs'][2]['layout'] = 'leak'
    with pytest.raises(ValueError, match='root source'):
        build_training_dataset(cfg, base_dir=tmp_path)


def test_task_unit_mismatch_is_not_silently_converted(tmp_path):
    cfg = build_config(tmp_path)
    cfg['task_contract']['targets']['y']['unit'] = 'MPa'
    with pytest.raises(ValueError, match='target unit'):
        build_training_dataset(cfg, base_dir=tmp_path)


def test_fitted_preprocessing_cannot_use_validation_or_test_records(tmp_path):
    cfg = build_config(tmp_path)
    def preprocess(s):
        s.solver_inputs['experiment_context'] = {'fields': {'preprocessing': dict(status='confirmed',
            value=[dict(operation='standardization', basis='test response statistics', fit_role='test')], evidence='fixture')}}
    edit_sample(cfg, 0, preprocess)
    with pytest.raises(ValueError, match='preprocessing.*train'):
        build_training_dataset(cfg, base_dir=tmp_path)


def test_training_bundle_roles_must_match_source_row_ledger(tmp_path):
    import hashlib
    import json
    import numpy as np
    from literature_fixtures import save
    from experiment_to_cpfe.assets.registry import array_payload_sha256
    from experiment_to_cpfe.datasets.training import run_dataset_build
    from experiment_to_cpfe.learning.data_contract import read_training_bundle
    cfg = build_config(tmp_path)
    run_dataset_build(save(tmp_path/'build.json', cfg), tmp_path/'dataset')
    with np.load(tmp_path/'dataset/dataset.npz', allow_pickle=False) as f:
        arrays = {name:f[name] for name in f.files}
    metadata = json.loads(arrays['__metadata_json__'].item())
    arrays['groups'][0] = 'wrong'
    metadata['payload_hashes']['groups'] = array_payload_sha256(arrays['groups'])
    encoded = json.dumps(metadata)
    arrays['__metadata_json__'] = np.asarray(encoded)
    arrays['__metadata_sha256__'] = np.asarray(hashlib.sha256(encoded.encode()).hexdigest())
    np.savez(tmp_path/'changed.npz', **arrays)
    declarations = json.loads((tmp_path/'dataset/training-config.json').read_text())
    with np.load(tmp_path/'changed.npz', allow_pickle=False) as f, pytest.raises(ValueError, match='source row ledger'):
        read_training_bundle(f, declarations)
