"""Pure data import must not invent a solver-ready mesh to train a table task."""
import json
from pathlib import Path

import pytest

from experiment_to_cpfe.cli import main
from experiment_to_cpfe.datasets.hdf5 import read_hdf5


def recipe(root):
    raw = root / 'instrument.csv'
    raw.write_text('row_id,position\nr0,0\nr1,2.5\n', encoding='utf-8')
    payload = dict(version=1, purpose='synthetic input only; data engineering verification',
        sample=dict(sample_id='sample-a', experiment_id='batch-a', microstructure_id='not-applicable',
            load_path_id='synthetic', schema_version='0.1',
            coordinate=dict(name='time-series', axes=['time'], units='s'),
            unit_system={'length': 'mm', 'time': 's'}, tensor_order=['scalar'],
            orientation=dict(representation='not_applicable', reason='scalar instrument')),
        sources=[dict(path=raw.name, table_name='measured_observations', source_kind='input',
            modality='time_series', format='csv', delimiter=',', encoding='utf-8',
            column_map={'row_id':'row_id','position':'position'}, units={'row_id':'1','position':'mm'},
            coordinate_frame='time-series', axis_order=['row'], native_layout='named columns', license='synthetic fixture')],
        solver_inputs={'dataset_split':'train'})
    config = root / 'normalize.json'
    config.write_text(json.dumps(payload), encoding='utf-8')
    return config, payload


def test_normalization_cli_preserves_values_identity_and_source_without_solver(tmp_path):
    config, _ = recipe(tmp_path)
    output = tmp_path / 'result'
    assert main(['normalize-sample','--config',str(config),'--run-dir',str(output)]) == 0
    sample = read_hdf5(output / 'sample.h5')
    assert [row['position'] for row in sample.tables['measured_observations']] == [0, 2.5]
    assert sample.metadata.sample_id == 'sample-a'
    assert sample.metadata.experiment_id == 'batch-a'
    assert sample.assets[0].sha256
    receipt = json.loads((output / 'normalization.json').read_text())
    assert receipt['status'] == 'completed' and receipt['validation']['passed']
    assert receipt['solver_readiness_assessed'] is False
    assert receipt['artifacts']['sample.h5']['sha256']
    assert receipt['inputs'][0]['sha256'] == sample.assets[0].sha256


@pytest.mark.parametrize('change', ['unknown', 'missing-file', 'missing-unit'])
def test_bad_normalization_is_failed_with_receipt_and_no_dataset(tmp_path, change):
    config, payload = recipe(tmp_path)
    if change == 'unknown': payload['infer_material'] = True
    if change == 'missing-file': payload['sources'][0]['path'] = 'absent.csv'
    if change == 'missing-unit': payload['sources'][0]['units'].pop('position')
    config.write_text(json.dumps(payload), encoding='utf-8')
    output = tmp_path / 'result'
    assert main(['normalize-sample','--config',str(config),'--run-dir',str(output)]) == 1
    assert json.loads((output / 'normalization.json').read_text())['status'] == 'failed'
    assert not (output / 'sample.h5').exists()


def test_normalization_never_overwrites_previous_attempt(tmp_path):
    config, _ = recipe(tmp_path)
    output = tmp_path / 'result'
    output.mkdir()
    (output / 'keep.txt').write_text('existing user result')
    assert main(['normalize-sample','--config',str(config),'--run-dir',str(output)]) == 1
    assert list(p.name for p in output.iterdir()) == ['keep.txt']


def test_malformed_yaml_writes_failure_receipt(tmp_path):
    config=tmp_path/'bad.yaml';config.write_text('sources: [unterminated')
    output=tmp_path/'result'
    assert main(['normalize-sample','--config',str(config),'--run-dir',str(output)]) == 1
    assert json.loads((output/'normalization.json').read_text())['status']=='failed'


def test_drift_during_hdf5_write_prevents_completed_receipt(tmp_path, monkeypatch):
    from experiment_to_cpfe.datasets import normalization
    config,_=recipe(tmp_path)
    original=normalization.write_hdf5
    def concurrent_writer(*args,**kwargs):
        original(*args,**kwargs)
        with (tmp_path/'instrument.csv').open('a') as stream:stream.write('r2,99\n')
    monkeypatch.setattr(normalization,'write_hdf5',concurrent_writer)
    result=normalization.run_normalization(config,tmp_path/'result')
    assert result['status']=='failed'
    assert 'integrity' in result['error']


def test_interruption_preserves_terminal_state(tmp_path, monkeypatch):
    from experiment_to_cpfe.datasets import normalization
    config,_=recipe(tmp_path)
    def interrupted(*args,**kwargs):
        raise KeyboardInterrupt('controlled interruption')
    monkeypatch.setattr(normalization,'assemble_sample',interrupted)
    try:
        result=normalization.run_normalization(config,tmp_path/'result')
    except KeyboardInterrupt:
        result={}
    assert result.get('status')=='interrupted'
    assert json.loads((tmp_path/'result/normalization.json').read_text())['status']=='interrupted'
