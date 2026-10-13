"""Workspace task listing and creation dedup flag through the shared public core."""
import json
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import ValidationError

from experiment_to_cpfe.harness import HarnessClient, initialize_workspace
from experiment_to_cpfe.harness.contracts import tools, validate_response


ROOT = Path(__file__).resolve().parents[3]
CASE = ROOT / 'examples' / 'paramaterial_tensile'


def request(**args):
    return dict(schema_version='harness.v1', request_id='runs-list', workspace_id='local', **args)


def workspace(tmp_path):
    initialize_workspace(tmp_path / 'workspace', CASE)
    return HarnessClient(tmp_path / 'workspace')


def create(client, key, **spec):
    result = client.call('task.create', request(idempotency_key=key, workflow_id='paramaterial_tensile.v1', **spec))
    assert result['ok'], result
    return result['data']


def listing(client, **page):
    result = client.call('runs.list', request(**page))
    assert result['ok'], result
    assert validate_response('runs.list', result) == result
    return result['data']


def test_runs_list_is_a_published_readonly_tool_without_run_id():
    published = {item['name']: item for item in tools()}
    item = published['runs.list']
    assert item['read_only'] is True
    assert item['side_effects'] == []
    assert 'run_id' not in item['input_schema'].get('required', [])
    assert 'run_id' not in item['input_schema']['properties']
    assert 'items' in str(item['output_schema'])


def test_empty_workspace_lists_nothing_and_writes_nothing(tmp_path):
    client = workspace(tmp_path)
    before = (tmp_path / 'workspace' / 'harness.sqlite3').read_bytes()
    data = listing(client)
    assert data == {'items': [], 'next_cursor': None, 'total': 0}
    assert not list((tmp_path / 'workspace' / 'runs').iterdir())
    assert (tmp_path / 'workspace' / 'harness.sqlite3').read_bytes() == before


def test_runs_are_listed_newest_first_with_durable_state(tmp_path):
    client = workspace(tmp_path)
    first = create(client, 'first')
    second = create(client, 'second', replicate=True, require_review=True)
    paused = client.call('task.control', request(idempotency_key='pause', run_id=second['run_id'], action='pause',
                                                reason='list state', expected_state_version=second['state_version']))
    assert paused['ok'], paused
    items = listing(client)['items']
    assert [item['run_id'] for item in items] == [second['run_id'], first['run_id']]
    newest, oldest = items
    assert newest['task_id'] == second['task_id']
    assert newest['workflow_id'] == 'paramaterial_tensile.v1'
    assert newest['execution_status'] == 'paused'
    assert newest['state_version'] == paused['data']['state_version']
    assert newest['review_required'] is True
    assert newest['acceptance_status'] == 'not_assessed'
    assert newest['attempt_count'] == 0
    assert newest['current_attempt_id'] is None and newest['current_stage'] is None
    assert newest['created_at'] >= oldest['created_at']
    assert oldest['execution_status'] == 'ready' and oldest['review_required'] is False
    assert oldest['reason_code'] is None


def test_runs_list_pages_with_offset_cursor_and_bounds(tmp_path):
    client = workspace(tmp_path)
    runs = [create(client, f'replicate-{index}', replicate=True)['run_id'] for index in range(3)]
    first = listing(client, limit=2)
    assert first['total'] == 3 and first['next_cursor'] == 2 and len(first['items']) == 2
    rest = listing(client, limit=2, cursor=first['next_cursor'])
    assert rest['next_cursor'] is None and len(rest['items']) == 1
    assert [item['run_id'] for item in first['items'] + rest['items']] == runs[::-1]
    for bad in ({'limit': 0}, {'limit': 501}, {'cursor': -1}, {'run_id': runs[0]}):
        result = client.call('runs.list', request(**bad))
        assert result['error']['code'] == 'INVALID_REQUEST', result


def test_create_reports_whether_an_equivalent_frozen_run_was_reused(tmp_path):
    client = workspace(tmp_path)
    original = create(client, 'original')
    assert original['deduplicated'] is False
    reused = create(client, 'new-key-same-request')
    assert reused['deduplicated'] is True and reused['run_id'] == original['run_id']
    # Idempotent replay returns the stored original response unchanged.
    assert create(client, 'original') == original
    replicate = create(client, 'replicate', replicate=True)
    assert replicate['deduplicated'] is False and replicate['run_id'] != original['run_id']
    assert listing(client)['total'] == 2


def test_runs_list_output_contract_rejects_missing_identity():
    item = dict(task_id='task_' + 'a' * 32, run_id='run_' + 'a' * 32, workflow_id='paramaterial_tensile.v1',
                created_at='2026-10-11T00:00:00+00:00', execution_status='ready', state_version=1,
                reason_code=None, acceptance_status='not_assessed', attempt_count=0,
                current_attempt_id=None, current_stage=None, review_required=False)
    envelope = dict(schema_version='harness.v1', request_id='r', ok=True, error=None,
                    data=dict(items=[item], next_cursor=None, total=1))
    assert validate_response('runs.list', envelope)['data']['items'] == [item]
    item.pop('run_id')
    with pytest.raises(ValidationError):
        validate_response('runs.list', envelope)


def test_cli_lists_runs_created_through_python(tmp_path):
    client = workspace(tmp_path)
    created = create(client, 'python-create')
    command = [sys.executable, '-B', '-m', 'experiment_to_cpfe.cli', 'harness', 'call', 'runs.list',
               '--workspace', str(tmp_path / 'workspace'), '--request-json', '-']
    result = subprocess.run(command, input=json.dumps(request()), capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stdout + result.stderr
    assert [item['run_id'] for item in json.loads(result.stdout)['data']['items']] == [created['run_id']]
