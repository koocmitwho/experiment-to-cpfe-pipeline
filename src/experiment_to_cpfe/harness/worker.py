"""Owned asynchronous worker. Acquire durable execution rights before computing."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time

from .backends.local import constrain_cpu, process_identity, spawn_worker, stop_process
from .store import Store, dumps, event, identifier, transition


def _claim(root, attempt_id, nonce):
    identity = process_identity(os.getpid())
    store = Store(root)
    with store.transaction() as db:
        attempt = db.execute('SELECT * FROM attempts WHERE id=? AND nonce=?', (attempt_id, nonce)).fetchone()
        if attempt is None or attempt['identity'] is not None or attempt['state'] != 'queued':
            return None
        run = db.execute('SELECT * FROM runs WHERE id=?', (attempt['run_id'],)).fetchone()
        if run['state'] != 'queued' or run['attempt_id'] != attempt_id:
            return None
        db.execute('UPDATE attempts SET identity=? WHERE id=?', (dumps(identity), attempt_id))
        event(db, run['id'], 'worker_registered', {'identity': identity}, attempt_id)
    while True:
        with store.transaction() as db:
            run = db.execute('SELECT * FROM runs WHERE id=?', (attempt['run_id'],)).fetchone()
            if run['state'] not in {'queued', 'waiting_resource'}:
                return None
            occupied = db.execute("SELECT count(*) FROM attempts WHERE state='running'").fetchone()[0]
            if occupied == 0:
                db.execute("UPDATE attempts SET state='running',started=? WHERE id=?", (time.time(), attempt_id))
                transition(db, run['id'], 'running')
                event(db, run['id'], 'execution_started', {'stage': attempt['stage']}, attempt_id)
                return dict(attempt), dict(run)
            if run['state'] != 'waiting_resource':
                transition(db, run['id'], 'waiting_resource')
                db.execute("UPDATE attempts SET state='waiting_resource' WHERE id=?", (attempt_id,))
        time.sleep(.15)


def _records(root, artifact_root):
    from .artifacts import inventory
    result = []
    for record in inventory(artifact_root):
        record['acceptance_status'] = 'candidate'
        if record['relative_path'].endswith('sample.h5'):
            record['datasets'] = ['measured/measured_observations/columns/' + name
                                  for name in ('Strain', 'Stress_MPa', 'source_row')]
        result.append({'directory': artifact_root.relative_to(root).as_posix(), 'record': record})
    return result


def _publish(db, run, attempt, seal, receipt_hash):
    """Exactly one publication; filesystem seal is verified before this transaction."""
    current = db.execute('SELECT * FROM attempts WHERE id=?', (attempt['id'],)).fetchone()
    if current['state'] in {'completed', 'failed', 'cancelled', 'interrupted'}:
        return
    current_run = db.execute('SELECT * FROM runs WHERE id=?', (run['id'],)).fetchone()
    if current_run['attempt_id'] != attempt['id'] or current_run['state'] not in {'running', 'pause_requested', 'reconciling'}:
        raise ValueError('publication does not own the current run state')
    elapsed = seal['elapsed_seconds']
    db.execute("UPDATE attempts SET state='completed',elapsed=?,receipt=? WHERE id=?", (elapsed, receipt_hash, attempt['id']))
    db.execute('UPDATE runs SET elapsed=elapsed+?,report=? WHERE id=?', (elapsed, dumps(seal['report']), run['id']))
    for entry in seal['artifacts']:
        record = dict(entry['record'], acceptance_status=seal['report']['overall_acceptance'])
        db.execute('INSERT INTO artifacts VALUES(?,?,?,?,?)',
                   (identifier('artifact'), run['id'], attempt['id'], entry['directory'], dumps(record)))
    state = 'paused' if current_run['state'] == 'pause_requested' else seal['final_state']
    transition(db, run['id'], state)
    event(db, run['id'], 'acceptance_completed', {'overall_acceptance': seal['report']['overall_acceptance'],
        'scientific_claim_status': seal['report']['scientific_claim_status'], 'receipt_sha256': receipt_hash}, attempt['id'])
    if state == 'waiting_human':
        handoff_id = identifier('handoff')
        db.execute('INSERT INTO handoffs(id,run_id,attempt_id,state,binding) VALUES(?,?,?,?,?)',
                   (handoff_id, run['id'], attempt['id'], 'pending', receipt_hash))
        event(db, run['id'], 'handoff_opened', {'handoff_id': handoff_id, 'quiesced': True,
            'reason': 'operator_review_requested', 'evidence_binding': receipt_hash}, attempt['id'])
    elif state == 'completed':
        db.execute("UPDATE handoffs SET state='verified' WHERE run_id=? AND state='revalidating'", (run['id'],))


def recover_sealed(root, db, run, attempt):
    """Recover the seal-publication crash window, never regenerate a receipt."""
    from .artifacts import resolve_within, digest_file
    from .policy import digest, read_policy
    from .service import check_snapshot
    path = resolve_within(root, Path(attempt['directory']) / 'seal.json', must_exist=False)
    if not path.is_file():
        return False
    snapshot = json.loads(run['snapshot'])
    check_snapshot(read_policy(root), snapshot)
    seal = json.loads(path.read_text(encoding='utf-8'))
    if (seal['attempt_id'] != attempt['id'] or seal['nonce'] != attempt['nonce']
            or seal['snapshot_sha256'] != digest(snapshot) or run['attempt_id'] != attempt['id']):
        raise ValueError('seal identity does not match frozen execution')
    for entry in seal['artifacts']:
        file = resolve_within(root, Path(entry['directory']) / entry['record']['relative_path'])
        if digest_file(file) != entry['record']['sha256']:
            raise ValueError('sealed artifact changed')
    from .acceptance import accept_case
    report = accept_case(Path(read_policy(root)['case_dir']), resolve_within(root, seal['candidate_directory']))
    if report != seal['report']:
        raise ValueError('independent acceptance differs from unpublished seal')
    _publish(db, run, attempt, seal, digest_file(path))
    return True


def _failed(root, run, attempt, code, elapsed):
    from .artifacts import atomic_json, digest_file, resolve_within
    directory = resolve_within(root, attempt['directory'])
    failure = dict(format='harness.failure.v1', attempt_id=attempt['id'], run_id=run['id'],
                   code=code, elapsed_seconds=elapsed, retained=True, checkpoint_resume=False)
    atomic_json(directory / 'failure.json', failure)
    with Store(root).transaction() as db:
        current = db.execute('SELECT state FROM attempts WHERE id=?', (attempt['id'],)).fetchone()
        if current['state'] in {'cancelled', 'completed', 'failed', 'interrupted'}:
            return
        current_run = db.execute('SELECT state FROM runs WHERE id=?', (run['id'],)).fetchone()
        terminal = 'cancelled' if current_run['state'] == 'cancel_requested' else 'failed'
        db.execute('UPDATE attempts SET state=?,error=?,elapsed=? WHERE id=?', (terminal, code, elapsed, attempt['id']))
        db.execute('UPDATE runs SET elapsed=elapsed+? WHERE id=?', (elapsed, run['id']))
        transition(db, run['id'], terminal, error=code)
        event(db, run['id'], 'attempt_failed', failure, attempt['id'])
        db.execute('INSERT INTO artifacts VALUES(?,?,?,?,?)', (identifier('artifact'), run['id'], attempt['id'],
            attempt['directory'], dumps(dict(relative_path='failure.json', sha256=digest_file(directory / 'failure.json'),
                size_bytes=(directory / 'failure.json').stat().st_size, media_type='application/json', acceptance_status='failed_evidence'))))


def _size(root):
    from .artifacts import resolve_within
    total = 0
    for path in root.rglob('*'):
        try:
            # Core receipt writers legitimately rename/remove temporary files
            # between enumeration and stat. Links still fail closed.
            checked = resolve_within(root, path, must_exist=False)
            if checked.is_file():
                total += checked.stat().st_size
        except FileNotFoundError:
            continue
    return total


def _candidate_for_evaluation(root, run):
    from .artifacts import resolve_within, digest_file
    with Store(root).connection() as db:
        previous = db.execute("SELECT * FROM attempts WHERE run_id=? AND stage='paramaterial_case' AND state='completed' ORDER BY number DESC LIMIT 1", (run['id'],)).fetchone()
        if previous is None:
            raise ValueError('completed candidate attempt is required')
        for artifact in db.execute('SELECT * FROM artifacts WHERE attempt_id=?', (previous['id'],)):
            record = json.loads(artifact['record'])
            if digest_file(resolve_within(root, Path(artifact['directory']) / record['relative_path'])) != record['sha256']:
                raise ValueError('upstream candidate evidence changed')
    return resolve_within(root, Path(previous['directory']) / 'output')


def execute(root, attempt_id, nonce):
    # This runs before importing NumPy/Paramaterial, and after the launch Job owns us.
    enforcement = constrain_cpu()
    claimed = _claim(root, attempt_id, nonce)
    if claimed is None:
        return
    attempt, run = claimed
    started = time.monotonic()
    child = None
    child_identity = None
    from .artifacts import atomic_json, digest_file, resolve_within
    from .contracts import HarnessError
    from .policy import read_policy, digest
    from .service import check_snapshot
    from .workflows.paramaterial import case_command
    from .acceptance import accept_case
    root = Path(root).resolve(strict=True)
    policy = read_policy(root)
    snapshot = json.loads(run['snapshot'])
    directory = resolve_within(root, attempt['directory'])
    try:
        if enforcement['enforcement'] != 'affinity' or enforcement['observed_cpu_count'] != 1 or enforcement['process_tree_enforcement'] != 'windows_job_object':
            raise HarnessError('PRECONDITION_FAILED', 'Required process containment or CPU enforcement is unavailable.')
        check_snapshot(policy, snapshot)
        budget = snapshot['budget']
        remaining = budget['wall_seconds'] - run['elapsed']
        with Store(root).transaction() as db:
            event(db, run['id'], 'resource_enforcement', enforcement, attempt_id)
        if attempt['stage'] == 'paramaterial_case':
            output = directory / 'output'
            # Popen argv is entirely produced by the registered adapter, never a tool argument.
            argv = case_command(Path(policy['case_dir']), output, policy['python_executable'])
            child = spawn_worker(argv, cwd=directory, stdout=directory / 'computation.stdout.log',
                                 stderr=directory / 'computation.stderr.log', env=dict(os.environ))
            child_identity = process_identity(child.pid)
            while child.poll() is None:
                elapsed = time.monotonic() - started
                with Store(root).transaction() as db:
                    db.execute('UPDATE attempts SET elapsed=? WHERE id=?', (elapsed, attempt_id))
                if elapsed >= remaining or _size(root / 'runs' / run['id']) > budget['storage_bytes']:
                    # Child inherits this worker's containment. Do not publish partial output.
                    if not stop_process(child_identity):
                        raise HarnessError('EXECUTION_UNCERTAIN', 'Computation stop could not be confirmed.')
                    child.wait(timeout=10)
                    raise HarnessError('BUDGET_EXCEEDED', 'Active execution budget exhausted.')
                time.sleep(.05)
            if child.returncode:
                raise HarnessError('COMPUTATION_FAILED', 'Registered computation failed; original output is retained.')
        else:
            output = _candidate_for_evaluation(root, run)
        check_snapshot(policy, snapshot)
        report = accept_case(Path(policy['case_dir']), output)
        elapsed = time.monotonic() - started
        if elapsed >= remaining or _size(root / 'runs' / run['id']) > budget['storage_bytes']:
            raise HarnessError('BUDGET_EXCEEDED', 'Active execution budget exhausted.')
        atomic_json(directory / 'acceptance.json', report)
        lines = ['# 材料工作流验收', '', f"执行：{report['execution_status']}",
                 f"验收：{report['overall_acceptance']}", f"科学结论：{report['scientific_claim_status']}",
                 '', '本次为 Paramaterial 固定三试样处理复现，无训练、求解或模型调用。',
                 '数值参考容差为 1e-7，不代表实验真值精度或跨材料泛化。']
        (directory / 'REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
        records = _records(root, output)
        for name in ('acceptance.json', 'REPORT.md'):
            file = directory / name
            records.append({'directory': attempt['directory'], 'record': dict(relative_path=name,
                sha256=digest_file(file), size_bytes=file.stat().st_size,
                media_type='application/json' if name.endswith('.json') else 'text/markdown')})
        with Store(root).transaction() as db:
            current = db.execute('SELECT * FROM runs WHERE id=?', (run['id'],)).fetchone()
            if current['state'] not in {'running', 'pause_requested'}:
                raise HarnessError('STATE_CONFLICT', 'Run was stopped before result publication.')
            final_state = 'paused' if current['state'] == 'pause_requested' else (
                'waiting_human' if run['review_required'] and attempt['stage'] == 'paramaterial_case' else 'completed')
            seal = dict(format='harness.seal.v1', attempt_id=attempt_id, nonce=nonce,
                        snapshot_sha256=digest(snapshot), artifacts=records, report=report,
                        candidate_directory=output.relative_to(root).as_posix(),
                        elapsed_seconds=elapsed, final_state=final_state)
            atomic_json(directory / 'seal.json', seal)
            _publish(db, run, attempt, seal, digest_file(directory / 'seal.json'))
    except BaseException as exc:
        if child is not None and child.poll() is None:
            if child_identity is None or not stop_process(child_identity):
                with Store(root).transaction() as db:
                    current_run = db.execute('SELECT state FROM runs WHERE id=?', (run['id'],)).fetchone()
                    state = current_run['state'] if current_run['state'] in {'cancel_requested', 'pause_requested'} else 'reconciling'
                    transition(db, run['id'], state, error='STOP_UNCONFIRMED')
                    event(db, run['id'], 'stop_unconfirmed', {'requires_reconciliation': True}, attempt['id'])
                return
            child.wait(timeout=10)
        code = exc.code if isinstance(exc, HarnessError) else 'EVIDENCE_INVALID'
        _failed(root, run, attempt, code, time.monotonic() - started)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--attempt-id', required=True)
    parser.add_argument('--nonce', required=True)
    args = parser.parse_args(argv)
    execute(args.workspace, args.attempt_id, args.nonce)


if __name__ == '__main__':
    main()
