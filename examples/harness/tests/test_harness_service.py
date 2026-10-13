"""Public task boundaries: no private state edits or mock success receipts."""
import importlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
CASE = ROOT / 'examples' / 'paramaterial_tensile'


def api():
    try:
        return importlib.import_module('experiment_to_cpfe.harness')
    except ModuleNotFoundError:
        pytest.fail('public harness API is not implemented')


def client(tmp_path, **options):
    module = api()
    module.initialize_workspace(tmp_path / 'workspace', CASE, **options)
    return module.HarnessClient(tmp_path / 'workspace')


def request(**args):
    return dict(schema_version='harness.v1', request_id='request-1', workspace_id='local', **args)


def create(c, key='create-1', **spec):
    return c.call('task.create', request(idempotency_key=key, workflow_id='paramaterial_tensile.v1', **spec))


def test_discovery_and_dry_plan_never_create_computation(tmp_path):
    c = client(tmp_path)
    result = c.call('task.plan', request(workflow_id='paramaterial_tensile.v1'))
    assert result['ok']
    assert result['data']['dry_run'] is True
    assert not list((tmp_path / 'workspace' / 'runs').glob('*'))
    tools = c.tools()
    assert {'task.create', 'task.start', 'task.status', 'task.control', 'artifacts.read'} <= {t['name'] for t in tools}
    assert all(t['input_schema'] and t['output_schema'] for t in tools)


def test_concurrent_identical_create_allocates_one_task(tmp_path):
    c = client(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: create(c), range(4)))
    assert all(r['ok'] for r in results), results
    assert len({r['data']['task_id'] for r in results}) == 1
    assert len({r['data']['run_id'] for r in results}) == 1


def test_changed_payload_with_same_key_is_conflict(tmp_path):
    c = client(tmp_path)
    assert create(c)['ok']
    result = create(c, require_review=True)
    assert result['error']['code'] == 'IDEMPOTENCY_CONFLICT'


def test_equivalent_request_with_new_key_deduplicates_unless_explicit_replicate(tmp_path):
    c = client(tmp_path)
    first = create(c)
    second = create(c, key='another')
    assert first['data']['run_id'] == second['data']['run_id']
    third = create(c, key='replicate', replicate=True)
    assert third['data']['run_id'] != first['data']['run_id']


def test_agent_cannot_raise_budget_or_choose_shell(tmp_path):
    c = client(tmp_path)
    result = create(c, budget={'wall_seconds': 601})
    assert result['error']['code'] == 'BUDGET_EXCEEDED'
    result = create(c, command=['powershell', 'anything'])
    assert result['error']['code'] == 'INVALID_REQUEST'


def test_unknown_backend_and_unknown_workspace_are_explicit(tmp_path):
    c = client(tmp_path)
    result = c.call('task.plan', request(workflow_id='abaqus'))
    assert result['error']['code'] == 'UNSUPPORTED'
    payload = request(workflow_id='paramaterial_tensile.v1')
    payload['workspace_id'] = 'unregistered'
    assert c.call('task.plan', payload)['error']['code'] == 'WORKSPACE_DENIED'


def test_pause_and_cancel_before_start_do_not_execute(tmp_path):
    c = client(tmp_path)
    run = create(c)['data']
    paused = c.call('task.control', request(idempotency_key='pause', run_id=run['run_id'], action='pause', reason='review', expected_state_version=run['state_version']))
    assert paused['data']['execution_status'] == 'paused'
    stale = c.call('task.control', request(idempotency_key='stale', run_id=run['run_id'], action='cancel', reason='stop', expected_state_version=run['state_version']))
    assert stale['error']['code'] == 'STATE_CONFLICT'
    cancelled = c.call('task.control', request(idempotency_key='cancel', run_id=run['run_id'], action='cancel', reason='stop', expected_state_version=paused['data']['state_version']))
    assert cancelled['data']['execution_status'] == 'cancelled'
    assert not list((tmp_path / 'workspace' / 'runs').glob('*/attempts/*'))


def test_changed_source_is_rejected_before_any_worker_starts(tmp_path):
    import shutil
    case = tmp_path / 'case'
    shutil.copytree(CASE, case)
    module = api()
    module.initialize_workspace(tmp_path / 'workspace', case)
    c = module.HarnessClient(tmp_path / 'workspace')
    run = create(c)['data']
    source = case / 'data/test_ID_055.csv'
    source.write_bytes(source.read_bytes() + b'\n')
    result = c.call('task.start', request(idempotency_key='start', run_id=run['run_id'], expected_state_version=run['state_version']))
    assert result['error']['code'] == 'INPUT_CHANGED'
    assert not list((tmp_path / 'workspace' / 'runs').glob('*'))


def test_lost_dispatch_can_be_reissued_without_overwriting_launch_logs(tmp_path, monkeypatch):
    from experiment_to_cpfe.harness.backends import local
    c = client(tmp_path)
    run = create(c)['data']
    calls = []
    def simulate_crash_before_claim(argv, *, cwd, stdout, stderr, env):
        calls.append((stdout, stderr))
        stdout.write_bytes(b'first launch stopped before claim')
        stderr.write_bytes(b'')
        raise OSError('injected launch failure')
    monkeypatch.setattr(local, 'spawn_worker', simulate_crash_before_claim)
    c.call('task.start', request(idempotency_key='start', run_id=run['run_id'], expected_state_version=run['state_version']))
    c.call('task.reconcile', request(idempotency_key='reconcile', run_id=run['run_id']))
    assert len(calls) == 2
    assert calls[0][0] != calls[1][0], 'dispatch must retain each launch log'
    assert calls[0][0].read_bytes() == b'first launch stopped before claim'


def test_storage_scan_tolerates_temporary_file_removed_during_enumeration(tmp_path, monkeypatch):
    from experiment_to_cpfe.harness.worker import _size
    stable = tmp_path / 'data.bin'
    stable.write_bytes(b'12345')
    gone = tmp_path / '.normalization.json.tmp'
    monkeypatch.setattr(Path, 'rglob', lambda self, pattern: iter([stable, gone]))
    assert _size(tmp_path) == 5


def test_persistence_error_is_structured_without_raw_message(tmp_path, monkeypatch):
    import sqlite3
    c = client(tmp_path)
    def unavailable():
        raise sqlite3.OperationalError('sensitive-local-path-and-credential')
    monkeypatch.setattr(c.store, 'transaction', unavailable)
    response = create(c)
    assert response['ok'] is False
    assert response['error']['code'] == 'STORE_UNAVAILABLE'
    assert 'credential' not in json.dumps(response)


def test_cancellation_intent_survives_worker_error(tmp_path, monkeypatch):
    from experiment_to_cpfe.harness.backends import local
    from experiment_to_cpfe.harness.worker import _claim, _failed
    from experiment_to_cpfe.harness.store import Store
    c = client(tmp_path)
    monkeypatch.setattr(local, 'spawn_worker', lambda *args, **kwargs: None)
    run = create(c)['data']
    queued = c.call('task.start', request(idempotency_key='start', run_id=run['run_id'], expected_state_version=run['state_version']))['data']
    with Store(c.root).connection() as db:
        attempt = db.execute('SELECT * FROM attempts WHERE id=?', (queued['attempt_id'],)).fetchone()
    owned, running = _claim(c.root, attempt['id'], attempt['nonce'])
    status = c.call('task.status', request(run_id=run['run_id']))['data']
    monkeypatch.setattr(local, 'stop_process', lambda identity: False)
    cancel = c.call('task.control', request(idempotency_key='cancel', run_id=run['run_id'],
        expected_state_version=status['state_version'], action='cancel', reason='test stop not yet confirmed'))
    assert cancel['data']['execution_status'] == 'cancel_requested'
    _failed(c.root, running, owned, 'STATE_CONFLICT', .2)
    final = c.call('task.status', request(run_id=run['run_id']))['data']
    assert final['execution_status'] == 'cancelled'
