"""Strict records remain independent of learning or orchestration engines."""
import json

import pytest

from experiment_file_fixtures import ref


def test_bound_record_rejects_nonfinite_values(tmp_path):
    from experiment_to_cpfe.provenance.records import bound_json
    path = tmp_path / 'record.json'
    path.write_text('{"measurement": NaN}')
    with pytest.raises(ValueError, match='nonfinite JSON'):
        bound_json(ref(path), tmp_path)


def test_bound_record_rejects_content_drift_during_read(tmp_path, monkeypatch):
    from experiment_to_cpfe.provenance import records
    path = tmp_path / 'record.json'
    path.write_text('{"value": 1}')
    original = records.read_json
    def changing_input(source):
        value = original(source)
        source.write_text('{"value": 2}')
        return value
    monkeypatch.setattr(records, 'read_json', changing_input)
    with pytest.raises(ValueError, match='changed while reading'):
        records.bound_json(ref(path), tmp_path)


def test_record_write_preserves_previous_complete_json_after_invalid_value(tmp_path):
    from experiment_to_cpfe.provenance.records import write_record
    path = tmp_path / 'record.json'
    write_record(path, {'status':'completed'})
    with pytest.raises(ValueError):
        write_record(path, {'value':float('nan')})
    assert json.loads(path.read_text()) == {'status':'completed'}


def test_missing_configuration_keeps_failed_import_receipt(tmp_path):
    from pydantic import BaseModel
    from experiment_to_cpfe.provenance.records import recorded_operation
    class Config(BaseModel):
        value: int
    with pytest.raises(FileNotFoundError):
        recorded_operation(tmp_path / 'absent.json', tmp_path / 'run', 'import', Config, None)
    receipt = json.loads((tmp_path / 'run/import.json').read_text())
    assert receipt['status'] == 'failed'
    assert receipt['error']['type'] == 'FileNotFoundError'


@pytest.mark.parametrize('fault', ['interruption', 'config-drift'])
def test_incomplete_operation_cannot_claim_success(tmp_path, fault):
    from pydantic import BaseModel
    from experiment_to_cpfe.provenance.records import recorded_operation
    class Config(BaseModel):
        value: int
    config = tmp_path / 'config.json'
    config.write_text('{"value":1}')
    def operation(*args):
        if fault == 'interruption':
            raise KeyboardInterrupt('controlled interruption')
        config.write_text('{"value":2}')
        return {'value':1}
    exception = KeyboardInterrupt if fault == 'interruption' else ValueError
    with pytest.raises(exception):
        recorded_operation(config, tmp_path / 'run', 'import', Config, operation)
    receipt = json.loads((tmp_path / 'run/import.json').read_text())
    assert receipt['status'] == ('interrupted' if fault == 'interruption' else 'failed')
