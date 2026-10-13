"""Public control regressions with real offline workers and owned fault injection."""
from contextlib import contextmanager
import json
import sqlite3
import time

from experiment_to_cpfe.harness.backends.local import probe_process, stop_process
from test_harness_execution import req, setup, wait


def current(client, run):
    response = client.call('task.status', req(run_id=run['run_id']))
    assert response['ok'], response
    return response['data']


def control(client, status, action, key):
    return client.call('task.control', req(idempotency_key=key, run_id=status['run_id'],
        expected_state_version=status['state_version'], action=action,
        attempt_id=status['attempt_id'], reason='controlled integration regression'))


def identity_for(client, attempt_id):
    # Read only: the worker alone writes its execution claim and instance identity.
    with sqlite3.connect(client.root / 'harness.sqlite3') as db:
        row = db.execute('SELECT identity FROM attempts WHERE id=?', (attempt_id,)).fetchone()
    return json.loads(row[0]) if row and row[0] else None


def cleanup(client):
    with sqlite3.connect(client.root / 'harness.sqlite3') as db:
        identities = [json.loads(row[0]) for row in db.execute('SELECT identity FROM attempts WHERE identity IS NOT NULL')]
    for identity in identities:
        if probe_process(identity) == 'running':
            stop_process(identity)
        deadline = time.monotonic() + 5
        while probe_process(identity) == 'running' and time.monotonic() < deadline:
            time.sleep(.02)
        assert probe_process(identity) == 'stopped', 'owned regression worker cleanup was not confirmed'


def test_running_review_pause_resume_preserves_operator_review_gate(tmp_path):
    client, run = setup(tmp_path, require_review=True)
    try:
        running = wait(client, run, states=('running',))
        paused = control(client, running, 'pause', 'pause-review')
        assert paused['ok'], paused
        boundary = wait(client, run, states=('paused', 'failed'))
        assert boundary['execution_status'] == 'paused', boundary
        resumed = control(client, boundary, 'resume', 'resume-review')
        assert resumed['ok'], resumed
        result = wait(client, run)
        assert result['execution_status'] == 'waiting_human', result
        handoffs = client.call('handoffs.list', req(run_id=run['run_id']))['data']['items']
        assert len(handoffs) == 1
        assert handoffs[0]['state'] == 'pending'
        events = client.call('events.list', req(run_id=run['run_id']))['data']['items']
        assert not any(event['kind'] == 'operator_approved' for event in events)
    finally:
        cleanup(client)


def test_waiting_resource_pause_resume_can_dispatch_again_without_overwriting_logs(tmp_path):
    client, first = setup(tmp_path)
    second = None
    try:
        wait(client, first, states=('running',))
        created = client.call('task.create', req(idempotency_key='second-create',
            workflow_id='paramaterial_tensile.v1', replicate=True))
        assert created['ok'], created
        second = created['data']
        started = client.call('task.start', req(idempotency_key='second-start', run_id=second['run_id'],
            expected_state_version=second['state_version']))
        assert started['ok'], started
        waiting = wait(client, second, states=('waiting_resource',))
        original_logs = {path: path.read_bytes() for path in (client.root / 'runs' / second['run_id']).rglob('*.log')}
        assert original_logs
        paused = control(client, waiting, 'pause', 'pause-waiter')
        assert paused['ok'], paused
        identity = identity_for(client, waiting['attempt_id'])
        deadline = time.monotonic() + 10
        while probe_process(identity) == 'running' and time.monotonic() < deadline:
            time.sleep(.02)
        assert probe_process(identity) == 'stopped'
        boundary = current(client, second)
        resumed = control(client, boundary, 'resume', 'resume-waiter')
        assert resumed['ok'], resumed
        # This asserts queue liveness, not a 15-second performance SLA. Include
        # the preceding real job's resource wait using the suite's normal bound.
        finished = wait(client, second)
        assert finished['execution_status'] == 'completed', finished
        assert all(path.read_bytes() == content for path, content in original_logs.items())
        events = client.call('events.list', req(run_id=second['run_id']))['data']['items']
        assert sum(event['kind'] == 'execution_started' for event in events) == 1
    finally:
        cleanup(client)


def test_interrupted_attempt_consumes_frozen_budget_before_retry(tmp_path):
    client, run = setup(tmp_path, budget={'wall_seconds': 3.0})
    try:
        running = wait(client, run, states=('running',))
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            running = current(client, run)
            observed = running['attempts'][-1]['elapsed_seconds']
            if observed >= .15:
                break
            assert running['execution_status'] == 'running', running
            time.sleep(.02)
        assert observed >= .15
        identity = identity_for(client, running['attempt_id'])
        assert stop_process(identity), 'only the registered fixture worker is interrupted'
        reconciled = client.call('task.reconcile', req(idempotency_key='reconcile-budget', run_id=run['run_id']))
        assert reconciled['ok'], reconciled
        interrupted = reconciled['data']
        assert interrupted['execution_status'] == 'interrupted', interrupted
        assert interrupted['consumed_wall_seconds'] >= observed
        assert interrupted['budget']['wall_seconds'] == 3.0
        retried = control(client, interrupted, 'retry', 'retry-budget')
        if interrupted['consumed_wall_seconds'] >= 3.0:
            assert retried['error']['code'] == 'BUDGET_EXCEEDED'
        else:
            assert retried['ok'], retried
            assert retried['data']['consumed_wall_seconds'] >= observed
            terminal = wait(client, run)
            assert terminal['attempts'][0]['execution_status'] == 'interrupted'
            assert terminal['consumed_wall_seconds'] >= sum(attempt['elapsed_seconds'] for attempt in terminal['attempts'])
            assert terminal['execution_status'] in {'completed', 'failed'}
        events = client.call('events.list', req(run_id=run['run_id']))['data']['items']
        assert any(event['kind'] == 'worker_stopped_without_seal' for event in events)
    finally:
        cleanup(client)


@contextmanager
def unpublished_seal(tmp_path, monkeypatch):
    from experiment_to_cpfe.harness.backends import local

    real_spawn = local.spawn_worker
    launched = []

    def fail_at_publication(argv, **kwargs):
        # Fault only in an owned test process, after the actual case and seal are
        # complete but before the SQLite transaction publishes accepted artifacts.
        source = (
            "import os,sys; from pathlib import Path; "
            "from experiment_to_cpfe.harness import worker; "
            "worker._publish=lambda *args,**kwargs: os._exit(37); "
            "worker.execute(Path(sys.argv[1]),sys.argv[2],sys.argv[3])"
        )
        replacement = [argv[0], '-B', '-c', source,
                       argv[argv.index('--workspace') + 1],
                       argv[argv.index('--attempt-id') + 1],
                       argv[argv.index('--nonce') + 1]]
        process = real_spawn(replacement, **kwargs)
        launched.append(process)
        return process

    with monkeypatch.context() as patch:
        patch.setattr(local, 'spawn_worker', fail_at_publication)
        client, run = setup(tmp_path)
    try:
        deadline = time.monotonic() + 45
        seals = []
        identity = None
        while time.monotonic() < deadline:
            seals = list((client.root / 'runs' / run['run_id']).rglob('seal.json'))
            identity = identity_for(client, run['attempt_id'])
            if seals and identity and probe_process(identity) == 'stopped':
                break
            time.sleep(.05)
        assert len(seals) == 1, 'the injected crash must happen after the real seal was written'
        assert identity and probe_process(identity) == 'stopped'
        assert launched[0].wait(timeout=5) == 37
        yield client, run, seals[0]
    finally:
        cleanup(client)
        for process in launched:
            process.wait(timeout=5)


def test_cancel_survives_unknown_probe_after_unpublished_seal(tmp_path, monkeypatch):
    from experiment_to_cpfe.harness.backends import local

    with unpublished_seal(tmp_path, monkeypatch) as (client, run, seal):
        original_seal = seal.read_bytes()
        cancelled = control(client, current(client, run), 'cancel', 'cancel-unpublished')
        assert cancelled['ok'], cancelled
        with monkeypatch.context() as patch:
            patch.setattr(local, 'probe_process', lambda identity: 'unknown')
            uncertain = client.call('task.reconcile', req(idempotency_key='unknown-after-cancel', run_id=run['run_id']))
            assert uncertain['ok'], uncertain
        reconciled = client.call('task.reconcile', req(idempotency_key='stopped-after-cancel', run_id=run['run_id']))
        assert reconciled['ok'], reconciled
        assert reconciled['data']['execution_status'] == 'cancelled', reconciled
        assert reconciled['data']['attempts'][-1]['execution_status'] == 'cancelled'
        assert client.call('artifacts.list', req(run_id=run['run_id']))['data']['items'] == []
        assert seal.read_bytes() == original_seal
        assert list(seal.parent.rglob('sample.h5')), 'cancelled output evidence remains on disk'


def test_corrupt_unpublished_seal_blocks_dead_attempt_and_releases_resource_slot(tmp_path, monkeypatch):
    with unpublished_seal(tmp_path, monkeypatch) as (client, run, seal):
        original_seal = seal.read_bytes()
        output = next(seal.parent.rglob('sample.h5'))
        # Corrupt only this test's new candidate, never a source file or database.
        with output.open('ab') as stream:
            stream.write(b'controlled artifact corruption')
        response = client.call('task.reconcile', req(idempotency_key='corrupt-seal', run_id=run['run_id']))
        assert response['ok'], response
        blocked = response['data']
        assert blocked['execution_status'] == 'blocked', blocked
        assert blocked['attempts'][-1]['execution_status'] == 'interrupted'
        assert blocked['reason_code'] == 'INTEGRITY_MISMATCH'
        assert blocked['consumed_wall_seconds'] > 0
        assert client.call('artifacts.list', req(run_id=run['run_id']))['data']['items'] == []
        assert seal.read_bytes() == original_seal
        assert output.read_bytes().endswith(b'controlled artifact corruption')

        created = client.call('task.create', req(idempotency_key='healthy-create',
            workflow_id='paramaterial_tensile.v1', replicate=True))
        assert created['ok'], created
        healthy = created['data']
        started = client.call('task.start', req(idempotency_key='healthy-start', run_id=healthy['run_id'],
            expected_state_version=healthy['state_version']))
        assert started['ok'], started
        finished = wait(client, healthy, timeout=20)
        assert finished['execution_status'] == 'completed', finished
        assert current(client, run)['execution_status'] == 'blocked'
