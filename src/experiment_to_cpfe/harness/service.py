"""One business boundary shared by Python, structured CLI and optional MCP."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
import sys
import time

from pydantic import ValidationError

from .contracts import Budget, HarnessError, TOOLS, tools, validate_response
from .policy import budget_within, digest, execution_environment, read_policy
from .store import Store, dumps, event, identifier, now, transition


TERMINAL = {'completed', 'failed', 'cancelled', 'interrupted'}
ACTIVE = {'queued', 'waiting_resource', 'running', 'pause_requested', 'cancel_requested', 'reconciling'}


def initialize_workspace(root, case_dir, *, limits=None):
    """Operator-only initialization. No corresponding agent tool is registered."""
    from .artifacts import atomic_json
    root, case_dir = Path(root).resolve(), Path(case_dir).resolve(strict=True)
    if root == case_dir or root.is_relative_to(case_dir) or case_dir.is_relative_to(root):
        raise ValueError('workspace and read-only case root must be disjoint')
    if not (case_dir / 'workflow.py').is_file():
        raise ValueError('registered Paramaterial source case is required')
    budget = Budget.model_validate(limits or {}).model_dump()
    root.mkdir(parents=True, exist_ok=False)
    (root / 'runs').mkdir()
    atomic_json(root / 'workspace.json', dict(schema_version='harness.workspace.v1',
        workspace_id='local', case_dir=str(case_dir), python_executable=str(Path(sys.executable).resolve()),
        limits=budget, max_concurrency=1, created_at=now()))
    Store(root).initialize()
    return {'workspace_id': 'local', 'root': str(root)}


def _run(db, run_id):
    row = db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
    if row is None:
        raise HarnessError('NOT_FOUND', 'Registered run does not exist.')
    return row


def _status(db, row):
    attempts = [dict(a) for a in db.execute('SELECT * FROM attempts WHERE run_id=? ORDER BY number', (row['id'],))]
    return dict(task_id=row['task_id'], run_id=row['id'], attempt_id=row['attempt_id'],
        execution_status=row['state'], state_version=row['version'], reason_code=row['error'],
        consumed_wall_seconds=row['elapsed'] + sum(a['elapsed'] for a in attempts if a['state'] not in TERMINAL), budget=json.loads(row['snapshot'])['budget'],
        attempts=[dict(attempt_id=a['id'], number=a['number'], stage=a['stage'],
                       execution_status=a['state'], elapsed_seconds=a['elapsed'], reason_code=a['error']) for a in attempts],
        progress={'kind': 'stage', 'fraction': None, 'source': 'durable_worker_events'},
        acceptance_status=json.loads(row['report'])['overall_acceptance'] if row['report'] else 'not_assessed')


def _check_version(row, expected):
    if row['version'] != expected:
        raise HarnessError('STATE_CONFLICT', 'State changed; read current status before requesting this action.')


def _settle_interrupted(db, row, attempt, state, code):
    # A dead worker cannot report its final stopwatch. Charge the interval since
    # its known start conservatively, including the unobserved interval.
    elapsed = max(attempt['elapsed'], max(0, time.time() - attempt['started']) if attempt['started'] else 0)
    if attempt['state'] not in TERMINAL:
        db.execute('UPDATE attempts SET state=?,error=?,elapsed=? WHERE id=?', (state, code, elapsed, attempt['id']))
        db.execute('UPDATE runs SET elapsed=elapsed+? WHERE id=?', (elapsed, row['id']))
        event(db, row['id'], 'budget_settled', {'elapsed_seconds': elapsed, 'accounting': 'conservative_observation_interval'}, attempt['id'])


def _snapshot(policy, request):
    from .workflows.paramaterial import inspect_case
    if request.workflow_id != 'paramaterial_tensile.v1':
        raise HarnessError('UNSUPPORTED', 'This release supports only the registered Paramaterial workflow.')
    budget = budget_within(request.budget.model_dump(), policy['limits'])
    case = inspect_case(Path(policy['case_dir']))
    if not case['valid']:
        issue = case['issues'][0]
        raise HarnessError(issue['code'], issue.get('safe_message', 'Registered input validation failed.'), field=issue.get('field'))
    environment = execution_environment()
    if not environment['dependencies']['available']:
        raise HarnessError('PRECONDITION_FAILED', 'Registered case dependencies are unavailable or changed.')
    return dict(workflow_id=request.workflow_id, case=case, environment=environment,
                budget=budget, require_review=request.require_review,
                protocol={'id': 'paramaterial-consistency.v1', 'atol': 1e-7, 'rtol': 0,
                          'sample_count': 3, 'row_count': 1889, 'science': 'not_established'},
                backend='local_process.v1', policy_sha256=digest(policy))


def check_snapshot(policy, snapshot):
    """Admission never changes an old snapshot or signs changed inputs again."""
    from .workflows.paramaterial import inspect_case
    current = inspect_case(Path(policy['case_dir']))
    if not current['valid'] or current['files'] != snapshot['case']['files']:
        raise HarnessError('INPUT_CHANGED', 'Registered inputs or case code changed; create a new approved run.')
    if execution_environment() != snapshot['environment']:
        raise HarnessError('ENVIRONMENT_CHANGED', 'Executing code or dependency identity changed; create a new run.')
    if digest(policy) != snapshot['policy_sha256']:
        raise HarnessError('POLICY_CHANGED', 'Operator policy changed; this frozen run cannot be resumed.')


def _allocate(db, row, stage='paramaterial_case'):
    number = db.execute('SELECT count(*) FROM attempts WHERE run_id=?', (row['id'],)).fetchone()[0] + 1
    attempt_id = identifier('attempt')
    directory = f"runs/{row['id']}/attempts/{number:04d}-{stage}"
    db.execute('INSERT INTO attempts(id,run_id,number,stage,state,nonce,directory) VALUES(?,?,?,?,?,?,?)',
               (attempt_id, row['id'], number, stage, 'queued', identifier('nonce'), directory))
    # Old acceptance remains available as a bound historical artifact, never as
    # the active result of a new attempt.
    db.execute('UPDATE runs SET attempt_id=?,report=NULL WHERE id=?', (attempt_id, row['id']))
    transition(db, row['id'], 'queued')
    event(db, row['id'], 'attempt_queued', {'number': number, 'stage': stage}, attempt_id)
    return _status(db, _run(db, row['id']))


class HarnessClient:
    """Public model-independent client; all business calls use the same schemas."""
    def __init__(self, workspace):
        self.root = Path(workspace).resolve(strict=True)
        self.policy = read_policy(self.root)
        self.store = Store(self.root)

    def tools(self):
        return tools()

    def call(self, tool, arguments):
        request_id = arguments.get('request_id', '') if isinstance(arguments, dict) else ''
        request_id = request_id if isinstance(request_id, str) else ''
        try:
            if not isinstance(arguments, dict):
                raise HarnessError('INVALID_REQUEST', 'Request must be a JSON object.')
            if arguments.get('workspace_id') != 'local':
                raise HarnessError('WORKSPACE_DENIED', 'Workspace is not authorized.')
            if tool not in TOOLS:
                raise HarnessError('UNSUPPORTED', 'Operation is not registered.')
            model, writes, _ = TOOLS[tool]
            request = model.model_validate(arguments)
            # Reload policy, so changed local configuration never silently inherits authority.
            self.policy = read_policy(self.root)
            if writes:
                payload = request.model_dump(exclude={'request_id'})
                fingerprint = digest(payload)
                # Heavy but bounded inspection stays outside the transaction.
                prepared = _snapshot(self.policy, request) if tool == 'task.create' else None
                with self.store.transaction() as db:
                    old = db.execute('SELECT * FROM requests WHERE tool=? AND key=?', (tool, request.idempotency_key)).fetchone()
                    if old:
                        if old['digest'] != fingerprint:
                            raise HarnessError('IDEMPOTENCY_CONFLICT', 'Idempotency key already belongs to a different request.')
                        data = json.loads(old['response'])
                    else:
                        data = self._mutate(db, tool, request, prepared)
                        self._validated(tool, request_id, data)
                        db.execute('INSERT INTO requests VALUES(?,?,?,?)', (tool, request.idempotency_key, fingerprint, dumps(data)))
                if tool in {'task.start', 'task.control', 'task.reconcile', 'evaluation.start', 'handoffs.submit'}:
                    self._dispatch(data.get('run_id'))
            else:
                data = self._read(tool, request)
            return self._validated(tool, request_id, data)
        except ValidationError as exc:
            fields = '.'.join(str(x) for x in exc.errors(include_input=False)[0]['loc'])
            error = HarnessError('INVALID_REQUEST', 'Request does not match the published schema.', field=fields)
        except HarnessError as exc:
            error = exc
        except sqlite3.Error:
            error = HarnessError('STORE_UNAVAILABLE', 'Task persistence is unavailable; operator diagnosis is required.')
        except (FileNotFoundError, PermissionError):
            error = HarnessError('FILE_UNAVAILABLE', 'An authorized file is absent or inaccessible.')
        except (ValueError, OSError, RuntimeError):
            error = HarnessError('INTEGRITY_MISMATCH', 'The requested evidence failed validation; inspect local operator diagnostics.')
        except Exception:
            error = HarnessError('INTERNAL_ERROR', 'The operation could not produce a verified result.')
        return dict(schema_version='harness.v1', request_id=request_id, ok=False, data=None, error=error.record())

    @staticmethod
    def _validated(tool, request_id, data):
        try:
            return validate_response(tool, dict(schema_version='harness.v1', request_id=request_id, ok=True, data=data, error=None))
        except ValidationError:
            raise HarnessError('INTERNAL_RESPONSE_INVALID', 'The service produced a result outside its published schema.') from None

    def _read(self, tool, request):
        from .workflows.paramaterial import inspect_case
        if tool == 'capabilities.get':
            return dict(workflows=['paramaterial_tensile.v1'], backends=['local_process.v1'],
                formats=['csv', 'json', 'hdf5'], environment=execution_environment(),
                unsupported=['abaqus', 'training', 'checkpoint_resume', 'model_calls', 'remote_execution'],
                transports=['python', 'json_cli', 'mcp_stdio_optional'],
                controls={'pause': 'stage_boundary', 'cancel': 'owned_process_tree', 'retry': 'new_attempt'},
                resource_enforcement={'cpu': 'inherited_affinity_and_thread_limits', 'storage': 'monitored_not_filesystem_quota',
                                      'wall_time': 'worker_monotonic_deadline', 'gpu': 'unsupported'},
                execution_platforms=['windows'], platform_verification={'windows': 'tested', 'linux': 'unverified', 'macos': 'unsupported'},
                limits=self.policy['limits'], access_boundary='trusted_operator_config; agent tools cannot modify it')
        if tool == 'inputs.validate':
            return inspect_case(Path(self.policy['case_dir']))
        if tool == 'task.plan':
            snapshot = _snapshot(self.policy, request)
            return dict(dry_run=True, plan_digest=digest(snapshot), workflow_id=request.workflow_id,
                stages=[{'id': 'paramaterial_case', 'depends_on': []}, {'id': 'acceptance', 'depends_on': ['paramaterial_case']}],
                budget=snapshot['budget'], confirmations=['operator_review'] if request.require_review else [],
                estimates={'cpu': 1, 'gpu': 0, 'model_calls': 0, 'wall_seconds': None, 'basis': 'not_benchmarked'})
        if tool == 'artifacts.read':
            from .artifacts import read_view, resolve_within
            with self.store.connection() as db:
                row = db.execute('SELECT * FROM artifacts WHERE id=?', (request.artifact_id,)).fetchone()
                if row is None:
                    raise HarnessError('NOT_FOUND', 'Artifact is not registered.')
                directory = resolve_within(self.root, row['directory'])
                return read_view(directory, json.loads(row['record']), view=request.view, offset=request.offset,
                    limit=request.limit, columns=request.columns, dataset=request.dataset)
        if tool == 'runs.list':
            return self._runs(request)
        with self.store.connection() as db:
            row = _run(db, request.run_id)
            if tool == 'task.status':
                result = _status(db, row)
                attempt = db.execute('SELECT identity FROM attempts WHERE id=?', (row['attempt_id'],)).fetchone()
                if attempt and attempt['identity'] and row['state'] in ACTIVE:
                    from .backends.local import probe_process
                    result['worker_observation'] = probe_process(json.loads(attempt['identity']))
                    result['required_action'] = 'task.reconcile' if result['worker_observation'] != 'running' else None
                return result
            if tool == 'reports.get':
                if not row['report']:
                    return dict(execution_status=row['state'], overall_acceptance='not_assessed')
                from .artifacts import resolve_within, digest_file
                for artifact in db.execute('SELECT * FROM artifacts WHERE attempt_id=?', (row['attempt_id'],)):
                    record = json.loads(artifact['record'])
                    path = resolve_within(self.root, Path(artifact['directory']) / record['relative_path'])
                    if digest_file(path) != record['sha256']:
                        raise HarnessError('INTEGRITY_MISMATCH', 'Current report evidence no longer matches the sealed artifacts.')
                return dict(json.loads(row['report']), run_id=row['id'], attempt_id=row['attempt_id'], evidence_integrity='verified_now',
                            acceptance_scope='frozen_run', task_execution_status=row['state'])
            if tool == 'events.list':
                records = [dict(r) for r in db.execute('SELECT * FROM events WHERE run_id=? AND seq>? ORDER BY seq LIMIT ?',
                                                     (row['id'], request.cursor, request.limit))]
                for item in records:
                    item['data'] = json.loads(item['data'])
                return {'items': records, 'next_cursor': records[-1]['seq'] if records else request.cursor}
            if tool == 'artifacts.list':
                records = db.execute('SELECT * FROM artifacts WHERE run_id=? ORDER BY id LIMIT ? OFFSET ?',
                                     (row['id'], request.limit, request.cursor)).fetchall()
                items = [dict(artifact_id=r['id'], attempt_id=r['attempt_id'], **json.loads(r['record'])) for r in records]
                return {'items': items, 'next_cursor': request.cursor + len(items) if len(items) == request.limit else None}
            if tool == 'handoffs.list':
                records = db.execute('SELECT * FROM handoffs WHERE run_id=? ORDER BY id LIMIT ? OFFSET ?',
                                     (row['id'], request.limit, request.cursor)).fetchall()
                return {'items': [dict(handoff_id=r['id'], attempt_id=r['attempt_id'], state=r['state'],
                                       binding=r['binding'], required_evidence='registered_artifact_ids', quiesced=True) for r in records],
                        'next_cursor': request.cursor + len(records) if len(records) == request.limit else None}
        raise HarnessError('UNSUPPORTED', 'Operation is not implemented.')

    def _runs(self, request):
        with self.store.connection() as db:
            total = db.execute('SELECT count(*) FROM runs').fetchone()[0]
            rows = db.execute('SELECT r.*, a.stage AS current_stage, '
                              '(SELECT count(*) FROM attempts WHERE run_id=r.id) AS attempt_count '
                              'FROM runs r LEFT JOIN attempts a ON a.id=r.attempt_id '
                              'ORDER BY r.created DESC, r.rowid DESC LIMIT ? OFFSET ?',
                              (request.limit, request.cursor)).fetchall()
        items = [dict(task_id=r['task_id'], run_id=r['id'], workflow_id=json.loads(r['snapshot'])['workflow_id'],
                      created_at=r['created'], execution_status=r['state'], state_version=r['version'],
                      reason_code=r['error'],
                      acceptance_status=json.loads(r['report'])['overall_acceptance'] if r['report'] else 'not_assessed',
                      attempt_count=r['attempt_count'], current_attempt_id=r['attempt_id'],
                      current_stage=r['current_stage'], review_required=bool(r['review_required'])) for r in rows]
        end = request.cursor + len(items)
        return dict(items=items, next_cursor=end if items and end != total else None, total=total)

    def _mutate(self, db, tool, request, prepared):
        if tool == 'task.create':
            if request.expected_plan_digest and request.expected_plan_digest != digest(prepared):
                raise HarnessError('PLAN_STALE', 'Inputs or environment changed since planning.')
            fingerprint = digest(prepared)
            if not request.replicate:
                existing = db.execute('SELECT * FROM runs WHERE fingerprint=? ORDER BY created LIMIT 1', (fingerprint,)).fetchone()
                if existing:
                    return dict(_status(db, existing), deduplicated=True)
            run_id, task_id = identifier('run'), identifier('task')
            db.execute('INSERT INTO runs(id,task_id,fingerprint,snapshot,state,created,review_required) VALUES(?,?,?,?,?,?,?)',
                       (run_id, task_id, fingerprint, dumps(prepared), 'ready', now(), int(request.require_review)))
            event(db, run_id, 'task_frozen', {'fingerprint': fingerprint, 'budget': prepared['budget']})
            return dict(_status(db, _run(db, run_id)), deduplicated=False)
        if tool == 'inputs.register':
            from .artifacts import resolve_within, digest_file
            path = resolve_within(Path(self.policy['case_dir']), request.relative_path)
            if digest_file(path) != request.expected_sha256:
                raise HarnessError('HASH_MISMATCH', 'Input digest does not match its declaration.')
            old = db.execute('SELECT id,sha256 FROM inputs WHERE path=?', (request.relative_path,)).fetchone()
            if old and old['sha256'] != request.expected_sha256:
                raise HarnessError('INPUT_CHANGED', 'Registered input revision changed.')
            input_id = old['id'] if old else identifier('input')
            db.execute('INSERT OR IGNORE INTO inputs VALUES(?,?,?)', (input_id, request.relative_path, request.expected_sha256))
            return dict(input_id=input_id, sha256=request.expected_sha256, size_bytes=path.stat().st_size)
        row = _run(db, request.run_id)
        if hasattr(request, 'expected_state_version'):
            _check_version(row, request.expected_state_version)
        if tool == 'task.reconcile':
            return self._reconcile(db, row)
        if tool == 'task.start':
            if os.name != 'nt':
                raise HarnessError('UNSUPPORTED', 'Worker containment and recovery are verified only on Windows in this release.')
            if row['state'] != 'ready':
                raise HarnessError('PRECONDITION_FAILED', 'Start requires a ready run.')
            check_snapshot(self.policy, json.loads(row['snapshot']))
            return _allocate(db, row)
        if tool == 'evaluation.start':
            if row['state'] != 'completed':
                raise HarnessError('PRECONDITION_FAILED', 'Evaluation requires completed frozen candidate outputs.')
            check_snapshot(self.policy, json.loads(row['snapshot']))
            return _allocate(db, row, 'acceptance')
        if tool == 'handoffs.submit':
            return self._submit_handoff(db, row, request)
        if tool == 'task.control':
            return self._control(db, row, request)
        raise HarnessError('UNSUPPORTED', 'Operation is not implemented.')

    def _control(self, db, row, request):
        state = row['state']
        if request.action == 'pause':
            if state in {'ready', 'queued', 'waiting_resource'}:
                transition(db, row['id'], 'paused')
            elif state == 'running':
                transition(db, row['id'], 'pause_requested')
            else:
                raise HarnessError('PRECONDITION_FAILED', 'Pause is not available in this state.')
        elif request.action == 'cancel':
            if state in TERMINAL:
                raise HarnessError('PRECONDITION_FAILED', 'A terminal run is immutable.')
            attempt = db.execute('SELECT * FROM attempts WHERE id=?', (row['attempt_id'],)).fetchone()
            if attempt and attempt['identity'] and attempt['state'] not in TERMINAL:
                from .backends.local import stop_process
                if not stop_process(json.loads(attempt['identity'])):
                    transition(db, row['id'], 'cancel_requested', error='STOP_UNCONFIRMED')
                    return _status(db, _run(db, row['id']))
            if attempt:
                _settle_interrupted(db, row, attempt, 'cancelled', 'CANCELLED_BY_REQUEST')
            transition(db, row['id'], 'cancelled')
        elif request.action == 'resume':
            if state != 'paused':
                raise HarnessError('PRECONDITION_FAILED', 'Resume requires a paused stage boundary.')
            check_snapshot(self.policy, json.loads(row['snapshot']))
            attempt = db.execute('SELECT * FROM attempts WHERE id=?', (row['attempt_id'],)).fetchone()
            if attempt and attempt['state'] == 'completed':
                if row['review_required'] and not db.execute("SELECT 1 FROM handoffs WHERE run_id=? AND state IN ('approved','verified','revalidating')", (row['id'],)).fetchone():
                    pending = db.execute("SELECT 1 FROM handoffs WHERE run_id=? AND state='pending'", (row['id'],)).fetchone()
                    if not pending:
                        hid = identifier('handoff')
                        db.execute('INSERT INTO handoffs(id,run_id,attempt_id,state,binding) VALUES(?,?,?,?,?)',
                                   (hid, row['id'], attempt['id'], 'pending', attempt['receipt']))
                        event(db, row['id'], 'handoff_opened', {'handoff_id': hid, 'quiesced': True, 'reason': 'review_obligation_after_pause'}, attempt['id'])
                    transition(db, row['id'], 'waiting_human')
                    return _status(db, _run(db, row['id']))
                return _allocate(db, row, 'acceptance')
            if attempt and attempt['identity']:
                from .backends.local import probe_process
                if probe_process(json.loads(attempt['identity'])) != 'stopped':
                    raise HarnessError('EXECUTION_UNCERTAIN', 'Previous worker must be confirmed stopped before resume.')
            if attempt:
                db.execute("UPDATE attempts SET identity=NULL,state='queued' WHERE id=? AND state IN ('queued','waiting_resource')", (attempt['id'],))
                transition(db, row['id'], 'queued')
            else:
                transition(db, row['id'], 'ready')
        elif request.action == 'retry':
            if state not in {'failed', 'interrupted', 'blocked'}:
                raise HarnessError('RETRY_NOT_ALLOWED', 'Retry requires a failed or interrupted execution.')
            previous = db.execute('SELECT * FROM attempts WHERE id=?', (row['attempt_id'],)).fetchone()
            if previous is None or request.attempt_id != previous['id'] or request.stage != previous['stage']:
                raise HarnessError('PRECONDITION_FAILED', 'Retry must name the exact failed attempt and stage.')
            if previous['state'] not in {'failed', 'interrupted'}:
                raise HarnessError('RETRY_NOT_ALLOWED', 'Uncertain or active execution cannot be retried.')
            snapshot = json.loads(row['snapshot'])
            check_snapshot(self.policy, snapshot)
            count = db.execute('SELECT count(*) FROM attempts WHERE run_id=? AND stage=?', (row['id'], request.stage)).fetchone()[0]
            if count > snapshot['budget']['retries'] or row['elapsed'] >= snapshot['budget']['wall_seconds']:
                raise HarnessError('BUDGET_EXCEEDED', 'Retry allowance or active wall-time budget exhausted.')
            return _allocate(db, row, request.stage)
        event(db, row['id'], 'control_requested', {'action': request.action, 'reason': request.reason})
        return _status(db, _run(db, row['id']))

    def _reconcile(self, db, row):
        attempt = db.execute('SELECT * FROM attempts WHERE id=?', (row['attempt_id'],)).fetchone()
        if not attempt or row['state'] not in ACTIVE:
            return _status(db, row)
        if not attempt['identity']:
            # No child acquired execution rights. Redispatching the nonce cannot repeat computation.
            return _status(db, row)
        from .backends.local import probe_process
        observed = probe_process(json.loads(attempt['identity']))
        if observed == 'running':
            return _status(db, row)
        if observed == 'unknown':
            # Observation uncertainty must not erase an already requested control.
            state = row['state'] if row['state'] in {'cancel_requested', 'pause_requested'} else 'reconciling'
            transition(db, row['id'], state, error='EXECUTION_UNCERTAIN')
        else:
            from .worker import recover_sealed
            if row['state'] == 'cancel_requested':
                _settle_interrupted(db, row, attempt, 'cancelled', 'CANCELLED_BY_REQUEST')
                transition(db, row['id'], 'cancelled')
                return _status(db, _run(db, row['id']))
            try:
                recovered = recover_sealed(self.root, db, row, attempt)
            except (HarnessError, ValueError, OSError, KeyError, TypeError) as exc:
                code = exc.code if isinstance(exc, HarnessError) else 'INTEGRITY_MISMATCH'
                _settle_interrupted(db, row, attempt, 'interrupted', code)
                transition(db, row['id'], 'blocked', error=code)
                event(db, row['id'], 'recovery_rejected', {'code': code, 'seal_retained': True}, attempt['id'])
                return _status(db, _run(db, row['id']))
            if not recovered:
                _settle_interrupted(db, row, attempt, 'interrupted', 'CHECKPOINT_UNSUPPORTED')
                transition(db, row['id'], 'interrupted', error='CHECKPOINT_UNSUPPORTED')
                event(db, row['id'], 'worker_stopped_without_seal', {'checkpoint_resume': False}, attempt['id'])
        return _status(db, _run(db, row['id']))

    def _submit_handoff(self, db, row, request):
        handoff = db.execute('SELECT * FROM handoffs WHERE id=? AND run_id=?', (request.handoff_id, row['id'])).fetchone()
        if row['state'] != 'waiting_human' or handoff is None or handoff['attempt_id'] != request.attempt_id:
            raise HarnessError('EVIDENCE_STALE', 'Handoff does not match the quiescent current attempt.')
        if handoff['state'] != 'approved' or handoff['approval_id'] != request.approval_id:
            raise HarnessError('APPROVAL_REQUIRED', 'An operator-approved structured evidence receipt is required.')
        if sorted(json.loads(handoff['evidence'])) != sorted(request.evidence_ids):
            raise HarnessError('EVIDENCE_STALE', 'Submitted evidence differs from operator-approved evidence.')
        check_snapshot(self.policy, json.loads(row['snapshot']))
        db.execute("UPDATE handoffs SET state='revalidating' WHERE id=?", (handoff['id'],))
        event(db, row['id'], 'handoff_submitted', {'handoff_id': handoff['id'], 'evidence_ids': request.evidence_ids})
        return _allocate(db, row, 'acceptance')

    def _dispatch(self, run_id):
        if not run_id:
            return
        with self.store.connection() as db:
            row = _run(db, run_id)
            attempt = db.execute('SELECT * FROM attempts WHERE id=?', (row['attempt_id'],)).fetchone()
            if row['state'] != 'queued' or not attempt or attempt['identity']:
                return
        from .backends.local import spawn_worker
        from .artifacts import resolve_within
        directory = resolve_within(self.root, attempt['directory'], must_exist=False)
        directory.mkdir(parents=True, exist_ok=True)
        # Explicit environment; no solver-command overrides or credentials are forwarded.
        env = {key: os.environ[key] for key in ('SystemRoot', 'WINDIR', 'TEMP', 'TMP', 'PATH', 'HOME', 'USERPROFILE') if key in os.environ}
        env.update(PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', OMP_NUM_THREADS='1',
                   OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1',
                   MPLCONFIGDIR=str(directory / 'matplotlib'))
        argv = [self.policy['python_executable'], '-B', '-m', 'experiment_to_cpfe.harness.worker',
                '--workspace', str(self.root), '--attempt-id', attempt['id'], '--nonce', attempt['nonce']]
        try:
            launch_id = identifier('launch')
            spawn_worker(argv, cwd=self.root, stdout=directory / (launch_id + '.stdout.log'),
                         stderr=directory / (launch_id + '.stderr.log'), env=env)
        except OSError:
            # Outbox remains queued. Reconcile can retry dispatch; no execution has been inferred.
            with self.store.transaction() as db:
                event(db, run_id, 'dispatch_unconfirmed', {'code': 'WORKER_LAUNCH_UNCONFIRMED'}, attempt['id'])


def approve_handoff(workspace, handoff_id, evidence_ids, *, reviewer, basis):
    """Trusted operator API, deliberately not callable through the tool registry.

    OS access to the workspace is the authority boundary; agent clients must not
    be granted arbitrary filesystem/shell write access to the operator store.
    """
    if not reviewer.strip() or not basis.strip() or not evidence_ids:
        raise ValueError('reviewer, basis and evidence are required')
    root = Path(workspace).resolve(strict=True)
    with Store(root).transaction() as db:
        handoff = db.execute('SELECT * FROM handoffs WHERE id=?', (handoff_id,)).fetchone()
        if handoff is None or handoff['state'] != 'pending':
            raise ValueError('handoff is not pending')
        row = _run(db, handoff['run_id'])
        if row['state'] != 'waiting_human' or row['attempt_id'] != handoff['attempt_id']:
            raise ValueError('handoff no longer matches a quiescent run')
        from .artifacts import digest_file, resolve_within
        for aid in evidence_ids:
            artifact = db.execute('SELECT * FROM artifacts WHERE id=? AND run_id=?', (aid, row['id'])).fetchone()
            if artifact is None:
                raise ValueError('evidence is not registered for this run')
            record = json.loads(artifact['record'])
            path = resolve_within(root, Path(artifact['directory']) / record['relative_path'])
            if digest_file(path) != record['sha256']:
                raise ValueError('evidence hash changed')
        approval_id = identifier('approval')
        db.execute("UPDATE handoffs SET state='approved',approval_id=?,evidence=? WHERE id=?", (approval_id, dumps(evidence_ids), handoff_id))
        event(db, row['id'], 'operator_approved', {'handoff_id': handoff_id, 'reviewer': reviewer, 'basis': basis, 'evidence_ids': evidence_ids})
        return {'approval_id': approval_id, 'handoff_id': handoff_id}
