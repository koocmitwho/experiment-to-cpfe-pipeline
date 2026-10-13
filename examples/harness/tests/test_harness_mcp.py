"""Transport contract tests: the MCP boundary must preserve core semantics."""
import asyncio
import importlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

from experiment_to_cpfe.harness.contracts import tools
from experiment_to_cpfe.harness.service import HarnessClient, initialize_workspace


CASE = Path(__file__).resolve().parents[2] / 'paramaterial_tensile'
MODULE = 'experiment_to_cpfe.harness.mcp'


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / 'MCP 工作区 with spaces'
    initialize_workspace(root, CASE)
    return root


def adapter():
    assert importlib.util.find_spec(MODULE) is not None, 'Missing the optional MCP adapter'
    return importlib.import_module(MODULE)


def request(**fields):
    return dict(schema_version='harness.v1', request_id='测试-request', workspace_id='local', **fields)


def test_discovery_preserves_core_contracts_and_operator_boundary(workspace):
    module = adapter()
    from mcp import Client

    async def check():
        async with Client(module.create_server(workspace)) as client:
            published = (await client.list_tools()).tools
        assert len(published) == 17
        by_name = {item.name: item for item in published}
        for core in tools():
            name = 'harness_' + core['name'].replace('.', '_')
            item = by_name[name]
            assert re.fullmatch(r'[A-Za-z0-9_-]{1,64}', name)
            assert item.input_schema == core['input_schema']
            assert item.output_schema == dict(core['output_schema'], type='object')
            assert item.annotations.read_only_hint == core['read_only']
            assert item.annotations.idempotent_hint is True
            assert item.annotations.open_world_hint is False
        assert by_name['harness_task_control'].annotations.destructive_hint is True
        assert by_name['harness_task_reconcile'].annotations.read_only_hint is False
        assert 'harness_init' not in by_name and 'harness_approve' not in by_name
        assert not any((workspace / 'runs').iterdir())

    asyncio.run(check())


@pytest.mark.parametrize(('name', 'arguments', 'code'), [
    ('harness_task_plan', request(workflow_id='abaqus'), 'UNSUPPORTED'),
    ('harness_task_plan', request(workflow_id='paramaterial_tensile.v1', budget={'model_calls': 1}), 'INVALID_REQUEST'),
    ('harness_inputs_validate', {}, 'WORKSPACE_DENIED'),
    ('harness_inputs_validate', request(workspace='/somewhere'), 'INVALID_REQUEST'),
    ('harness_inputs_validate', dict(request(), workspace_id='elsewhere'), 'WORKSPACE_DENIED'),
    ('harness_approve', request(), 'UNSUPPORTED'),
    ('inputs.validate', request(), 'UNSUPPORTED'),
    ('harness_task_status', request(run_id='run_' + 'a' * 32), 'NOT_FOUND'),
    ('harness_inputs_register', request(relative_path='../outside.csv', expected_sha256='0' * 64,
                                      idempotency_key='outside'), 'INTEGRITY_MISMATCH'),
])
def test_errors_keep_structured_business_codes(workspace, name, arguments, code):
    module = adapter()
    from mcp import Client

    async def check():
        async with Client(module.create_server(workspace)) as client:
            result = await client.call_tool(name, arguments)
        envelope = result.structured_content
        assert result.is_error is True
        assert envelope['ok'] is False
        assert envelope['error']['code'] == code
        assert envelope['data'] is None
        assert json.loads(result.content[0].text) == envelope
        assert envelope['request_id'] == arguments.get('request_id', '')
        assert not any((workspace / 'runs').iterdir())

    asyncio.run(check())


def test_mcp_and_python_share_persisted_idempotency_and_versions(workspace):
    module = adapter()
    from mcp import Client

    async def check():
        args = request(workflow_id='paramaterial_tensile.v1', idempotency_key='same-core')
        async with Client(module.create_server(workspace)) as client:
            first = await client.call_tool('harness_task_create', args)
            assert first.is_error is False
            envelope = first.structured_content
            assert json.loads(first.content[0].text) == envelope
            replay = HarnessClient(workspace).call('task.create', args)
            assert replay == envelope
            run = envelope['data']
            conflict = await client.call_tool('harness_task_start', request(
                run_id=run['run_id'], expected_state_version=999, idempotency_key='stale'))
            assert conflict.structured_content['error']['code'] == 'STATE_CONFLICT'
            status = HarnessClient(workspace).call('task.status', request(run_id=run['run_id']))
            assert status['data']['execution_status'] == 'ready'
            assert status['data']['attempts'] == []

    asyncio.run(check())


def test_core_capabilities_describe_optional_stdio_transport(workspace):
    data = HarnessClient(workspace).call('capabilities.get', request())['data']
    assert 'mcp' not in data['unsupported']
    assert data['transports'] == ['python', 'json_cli', 'mcp_stdio_optional']
    assert {'abaqus', 'training', 'model_calls', 'remote_execution'} <= set(data['unsupported'])


def test_startup_rejects_missing_workspace_without_stdout_or_creation(tmp_path):
    adapter()
    root = tmp_path / 'missing'
    result = subprocess.run([sys.executable, '-I', '-B', '-m', MODULE, '--workspace', str(root)],
                            capture_output=True, text=True, encoding='utf-8', timeout=20)
    assert result.returncode == 2
    assert result.stdout == ''
    assert 'workspace' in result.stderr.lower()
    assert not root.exists()


def test_base_cli_import_does_not_require_optional_mcp(tmp_path):
    # A subprocess import guard represents the supported installation without the extra.
    code = '''
import importlib.abc, sys
class NoMCP(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'mcp' or fullname.startswith('mcp.'):
            raise ModuleNotFoundError("No module named 'mcp'", name='mcp')
sys.meta_path.insert(0, NoMCP())
from experiment_to_cpfe.harness.cli import main
raise SystemExit(main(['tools', 'list', '--json']))
'''
    result = subprocess.run([sys.executable, '-I', '-B', '-c', code], cwd=tmp_path,
                            capture_output=True, text=True, encoding='utf-8', timeout=20)
    assert result.returncode == 0, result.stderr
    assert len(json.loads(result.stdout)) == 17


def test_missing_optional_dependency_has_actionable_stderr(tmp_path):
    adapter()
    code = '''
import importlib.abc, sys
class NoMCP(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'mcp' or fullname.startswith('mcp.'):
            raise ModuleNotFoundError("No module named 'mcp'", name='mcp')
sys.meta_path.insert(0, NoMCP())
from experiment_to_cpfe.harness.mcp import main
raise SystemExit(main(['--workspace', sys.argv[1]]))
'''
    result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(tmp_path)],
                            capture_output=True, text=True, encoding='utf-8', timeout=20)
    assert result.returncode == 2
    assert result.stdout == ''
    assert '[mcp]' in result.stderr
    assert 'Traceback' not in result.stderr


@pytest.mark.parametrize('version', ['2024-11-05', '2025-06-18', '2025-11-25'])
def test_stdio_legacy_handshake_and_clean_protocol_output(workspace, version):
    adapter()

    async def check():
        process = await asyncio.create_subprocess_exec(
            sys.executable, '-I', '-B', '-m', MODULE, '--workspace', str(workspace),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, cwd=workspace.parent, limit=1024 * 1024)
        async def send(message):
            process.stdin.write((json.dumps(message, ensure_ascii=False) + '\n').encode('utf-8'))
            await process.stdin.drain()

        async def receive(identifier):
            while True:
                line = await asyncio.wait_for(process.stdout.readline(), timeout=20)
                assert line, 'MCP server closed stdout before replying'
                value = json.loads(line)
                assert value['jsonrpc'] == '2.0'
                if value.get('id') == identifier:
                    return value

        try:
            await send(dict(jsonrpc='2.0', id=1, method='initialize', params={
                'protocolVersion': version, 'capabilities': {},
                'clientInfo': {'name': 'offline-legacy-check', 'version': '1'}}))
            initialized = (await receive(1))['result']
            assert initialized['protocolVersion'] == version
            assert 'tools' in initialized['capabilities']
            assert 'prompts' not in initialized['capabilities']
            await send(dict(jsonrpc='2.0', method='notifications/initialized'))
            await send(dict(jsonrpc='2.0', id=2, method='tools/list', params={}))
            listing = (await receive(2))['result']['tools']
            assert len(listing) == 17
            await send(dict(jsonrpc='2.0', id=3, method='tools/call', params={
                'name': 'harness_inputs_validate', 'arguments': request()}))
            result = (await receive(3))['result']
            assert result.get('isError') is not True
            envelope = json.loads(result['content'][0]['text'])
            assert envelope['request_id'] == '测试-request'
            assert envelope['data']['valid'] is True
            assert envelope['data']['total_rows'] == 1889
            await send(dict(jsonrpc='2.0', id=4, method='not/a/method', params={}))
            assert (await receive(4))['error']['code'] == -32601
            await send(dict(jsonrpc='2.0', id=5, method='ping'))
            assert 'result' in await receive(5)
            process.stdin.close()
            assert await asyncio.wait_for(process.wait(), timeout=20) == 0
            # stdout must not contain banners or stray diagnostics after the last reply.
            for line in (await process.stdout.read()).splitlines():
                assert json.loads(line)['jsonrpc'] == '2.0'
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()

    asyncio.run(check())
