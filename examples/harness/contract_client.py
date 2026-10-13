"""No-model client: the only business interaction is the published tool API."""
import argparse
import json
import time
import uuid

from experiment_to_cpfe.harness import HarnessClient


def run(workspace, key, *, replicate=False, timeout=660):
    client = HarnessClient(workspace)
    catalog = client.tools()
    available = {tool['name'] for tool in catalog}
    required = {'capabilities.get', 'inputs.validate', 'task.plan', 'task.create', 'task.start',
                'task.status', 'task.reconcile', 'events.list', 'artifacts.list', 'artifacts.read', 'reports.get'}
    if not required <= available:
        raise RuntimeError('Required public tool contract is unavailable.')
    calls = []
    evidence = dict(client_kind='no_model_contract_client', tool_catalog=catalog, tool_calls=calls)

    def call(tool, **values):
        request = dict(schema_version='harness.v1', request_id=uuid.uuid4().hex, workspace_id='local', **values)
        result = client.call(tool, request)
        calls.append(dict(tool=tool, request=request, response=result))
        if not result['ok']:
            raise RuntimeError(json.dumps(result['error'], ensure_ascii=False))
        return result['data']

    def pages(tool, run_id):
        items, cursor = [], 0
        while True:
            page = call(tool, run_id=run_id, cursor=cursor, limit=100)
            items.extend(page['items'])
            # Event cursors are also live polling positions. Empty items mean
            # this terminal snapshot is exhausted even if its cursor persists.
            if page['next_cursor'] is None or not page['items']:
                return dict(items=items, next_cursor=None, resume_cursor=page['next_cursor'])
            if page['next_cursor'] <= cursor:
                raise RuntimeError('Public page cursor did not advance.')
            cursor = page['next_cursor']

    evidence['capabilities'] = call('capabilities.get')
    validation = call('inputs.validate')
    evidence['input_validation'] = validation
    if not validation['valid']:
        return dict(evidence, outcome='blocked', issues=validation['issues'])
    plan = call('task.plan', workflow_id='paramaterial_tensile.v1')
    task = call('task.create', workflow_id='paramaterial_tensile.v1', idempotency_key=key,
                expected_plan_digest=plan['plan_digest'], replicate=replicate)
    if task['execution_status'] == 'ready':
        task = call('task.start', run_id=task['run_id'], expected_state_version=task['state_version'], idempotency_key=key + ':start')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = call('task.status', run_id=task['run_id'])
        if status['execution_status'] in {'completed', 'failed', 'interrupted', 'cancelled', 'blocked', 'paused', 'waiting_human'}:
            report = call('reports.get', run_id=task['run_id'])
            artifacts = pages('artifacts.list', task['run_id'])
            source_receipt = next((item for item in artifacts['items'] if item['relative_path'] == 'run.json'), None)
            run_evidence = (call('artifacts.read', artifact_id=source_receipt['artifact_id'], view='json')['data']
                            if source_receipt else None)
            return dict(evidence, task_id=task['task_id'], run_id=task['run_id'], status=status,
                        report=report, artifacts=artifacts, run_evidence=run_evidence,
                        events=pages('events.list', task['run_id']))
        if status.get('required_action') == 'task.reconcile':
            call('task.reconcile', run_id=task['run_id'], idempotency_key=key + ':reconcile:' + str(status['state_version']))
        time.sleep(.2)
    return dict(evidence, run_id=task['run_id'], outcome='client_timeout', execution_may_continue=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--idempotency-key', required=True)
    parser.add_argument('--replicate', action='store_true')
    args = parser.parse_args()
    result = run(args.workspace, args.idempotency_key, replicate=args.replicate)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    completed = result.get('status', {}).get('execution_status') == 'completed'
    accepted = result.get('report', {}).get('overall_acceptance') == 'accepted'
    return 0 if completed and accepted else 1


if __name__ == '__main__':
    raise SystemExit(main())
