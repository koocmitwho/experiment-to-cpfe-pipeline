"""CLI is an encoding adapter, not a separate scheduler."""
import json
from pathlib import Path
import subprocess
import sys


def test_cli_discovers_tools_and_returns_structured_usage_errors(tmp_path):
    command = [sys.executable, '-B', '-m', 'experiment_to_cpfe.cli', 'harness']
    result = subprocess.run([*command, 'tools', 'list', '--json'], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    tools = json.loads(result.stdout)
    assert 'task.start' in {item['name'] for item in tools}
    bad = subprocess.run([*command, 'call', 'task.start', '--workspace', str(tmp_path), '--request-json', '-'],
        input='{broken', capture_output=True, text=True)
    assert bad.returncode != 0
    failure = json.loads(bad.stdout)
    assert failure['error']['code'] == 'INVALID_REQUEST'
    assert str(tmp_path) not in failure['error']['safe_message']


def test_cli_init_and_python_share_persistent_task(tmp_path):
    root = Path(__file__).resolve().parents[3]
    workspace = tmp_path / 'workspace'
    command = [sys.executable, '-B', '-m', 'experiment_to_cpfe.cli', 'harness']
    result = subprocess.run([*command, 'init', '--workspace', str(workspace), '--case-dir', str(root / 'examples/paramaterial_tensile')], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    args = dict(schema_version='harness.v1', workspace_id='local', request_id='cli',
                idempotency_key='same', workflow_id='paramaterial_tensile.v1')
    created = subprocess.run([*command, 'call', 'task.create', '--workspace', str(workspace), '--request-json', '-'],
        input=json.dumps(args), capture_output=True, text=True)
    assert created.returncode == 0, created.stdout + created.stderr
    from experiment_to_cpfe.harness import HarnessClient
    again = HarnessClient(workspace).call('task.create', args)
    assert again['data']['task_id'] == json.loads(created.stdout)['data']['task_id']
