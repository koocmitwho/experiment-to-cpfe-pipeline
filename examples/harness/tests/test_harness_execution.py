"""Real offline execution and public controls; no model or solver is used."""
import json
from pathlib import Path
import sqlite3
import time

from experiment_to_cpfe.harness import HarnessClient, initialize_workspace, approve_handoff


CASE = Path(__file__).resolve().parents[3] / 'examples' / 'paramaterial_tensile'


def req(**args):
    return dict(schema_version='harness.v1', request_id='test', workspace_id='local', **args)


def setup(tmp_path, **spec):
    root = tmp_path / 'workspace'
    initialize_workspace(root, CASE)
    c = HarnessClient(root)
    created = c.call('task.create', req(idempotency_key='create', workflow_id='paramaterial_tensile.v1', **spec))
    assert created['ok'], created
    r = created['data']
    started = c.call('task.start', req(idempotency_key='start', run_id=r['run_id'], expected_state_version=r['state_version']))
    assert started['ok'], started
    return c, started['data']


def wait(c, run, states=('completed', 'failed', 'waiting_human', 'interrupted'), timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = c.call('task.status', req(run_id=run['run_id']))
        assert r['ok'], r
        if r['data']['execution_status'] in states:
            return r['data']
        time.sleep(.1)
    raise AssertionError(f'run did not reach {states}: {r}')


def test_real_case_nonblocking_then_independent_acceptance(tmp_path):
    before = time.monotonic()
    c, run = setup(tmp_path)
    assert time.monotonic() - before < 15  # submission does not wait for the case
    status = wait(c, run)
    assert status['execution_status'] == 'completed', status
    report = c.call('reports.get', req(run_id=run['run_id']))['data']
    assert report['overall_acceptance'] == 'accepted', report
    assert report['scientific_claim_status'] == 'not_established'
    assert len(report['criterion_results']) == 9
    assert len(status['attempts']) == 1
    items = c.call('artifacts.list', req(run_id=run['run_id']))['data']['items']
    hdf5 = [a for a in items if a['relative_path'].endswith('sample.h5')]
    assert len(hdf5) == 3
    assert all(a['sha256'] and a['size_bytes'] > 0 for a in items)
    events = c.call('events.list', req(run_id=run['run_id']))['data']['items']
    assert sum(e['kind'] == 'execution_started' for e in events) == 1


def test_budget_exhaustion_retains_failed_attempt(tmp_path):
    c, run = setup(tmp_path, budget={'wall_seconds': .001})
    status = wait(c, run)
    assert status['execution_status'] == 'failed', status
    assert status['reason_code'] == 'BUDGET_EXCEEDED'
    retry = c.call('task.control', req(idempotency_key='retry', run_id=run['run_id'],
        expected_state_version=status['state_version'], action='retry', reason='retry', attempt_id=status['attempt_id']))
    assert retry['error']['code'] == 'BUDGET_EXCEEDED'
    assert list(c.root.glob('runs/*/attempts/*/failure.json'))


def test_handoff_requires_operator_and_revalidates_frozen_evidence(tmp_path):
    c, run = setup(tmp_path, require_review=True)
    status = wait(c, run)
    assert status['execution_status'] == 'waiting_human', status
    h = c.call('handoffs.list', req(run_id=run['run_id']))['data']['items'][0]
    ids = [a['artifact_id'] for a in c.call('artifacts.list', req(run_id=run['run_id']))['data']['items'][:1]]
    args = dict(run_id=run['run_id'], expected_state_version=status['state_version'],
                handoff_id=h['handoff_id'], attempt_id=h['attempt_id'], evidence_ids=ids)
    forged = c.call('handoffs.submit', req(idempotency_key='forged', approval_id='I said done', **args))
    assert forged['error']['code'] == 'APPROVAL_REQUIRED'
    approved = approve_handoff(c.root, h['handoff_id'], ids, reviewer='test operator', basis='workflow test: inspected evidence')
    resumed = c.call('handoffs.submit', req(idempotency_key='approved', approval_id=approved['approval_id'], **args))
    assert resumed['ok'], resumed
    assert wait(c, run)['execution_status'] == 'completed'
    events = c.call('events.list', req(run_id=run['run_id']))['data']['items']
    assert {'handoff_opened', 'operator_approved', 'handoff_submitted', 'acceptance_completed'} <= {e['kind'] for e in events}


def test_killed_worker_is_not_silently_resubmitted(tmp_path):
    from experiment_to_cpfe.harness.backends.local import stop_process
    c, run = setup(tmp_path)
    status = wait(c, run, states=('running',))
    with sqlite3.connect(c.root / 'harness.sqlite3') as db:
        identity = json.loads(db.execute('SELECT identity FROM attempts WHERE id=?', (status['attempt_id'],)).fetchone()[0])
    assert stop_process(identity)
    result = c.call('task.reconcile', req(idempotency_key='reconcile', run_id=run['run_id']))
    assert result['ok'], result
    assert result['data']['execution_status'] == 'interrupted'
    assert result['data']['reason_code'] == 'CHECKPOINT_UNSUPPORTED'
    assert len(result['data']['attempts']) == 1
    retry = c.call('task.control', req(idempotency_key='retry', run_id=run['run_id'],
        expected_state_version=result['data']['state_version'], action='retry', reason='fault injection recovery',
        attempt_id=status['attempt_id']))
    assert retry['ok'], retry
    finished = wait(c, run)
    assert finished['execution_status'] == 'completed', finished
    assert len(finished['attempts']) == 2
    assert finished['attempts'][0]['execution_status'] == 'interrupted'
