"""Loopback HTTP adapter: transport security and parity with the shared public core."""
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from experiment_to_cpfe.harness import HarnessClient, initialize_workspace
from experiment_to_cpfe_harness_ui.server import HarnessUIServer, StartupError, check_interpreter


ROOT = Path(__file__).resolve().parents[3]
CASE = ROOT / 'examples' / 'paramaterial_tensile'
TOKEN = 'test-token-' + 'x' * 40


def request(**fields):
    return dict(schema_version='harness.v1', request_id='ui-test', workspace_id='local', **fields)


@pytest.fixture
def served(tmp_path):
    root = tmp_path / 'workspace'
    initialize_workspace(root, CASE)
    server = HarnessUIServer(root, token=TOKEN)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def send(server, method, path, body=None, *, token=TOKEN, host=None, headers=None, raw=None):
    port = server.server_address[1]
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=60)
    sent = {'Host': f'127.0.0.1:{port}' if host is None else host}
    if token is not None:
        sent['X-Harness-Token'] = token
    payload = raw
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode('utf-8')
        sent['Content-Type'] = 'application/json'
    sent.update(headers or {})
    connection.request(method, path, body=payload, headers=sent, encode_chunked=False)
    response = connection.getresponse()
    data = response.read()
    result = (response.status, dict(response.getheaders()), data)
    connection.close()
    return result


def call(server, tool, **fields):
    status, headers, data = send(server, 'POST', f'/api/tools/{tool}', request(**fields))
    assert status == 200, data
    return json.loads(data)


def test_binds_loopback_only_and_serves_page_with_security_headers(served):
    assert served.server_address[0] == '127.0.0.1'
    status, headers, data = send(served, 'GET', '/', token=None)
    assert status == 200 and b'<html' in data
    assert "frame-ancestors 'none'" in headers['Content-Security-Policy']
    assert headers['X-Content-Type-Options'] == 'nosniff'
    assert not any(key.lower().startswith('access-control-') for key in headers)


def test_session_requires_token_and_never_publishes_operator_commands(served):
    assert send(served, 'GET', '/api/session', token=None)[0] == 403
    assert send(served, 'GET', '/api/session', token='wrong-' + TOKEN)[0] == 403
    status, _, data = send(served, 'GET', '/api/session')
    session = json.loads(data)
    assert status == 200 and session['ok'] is True
    assert session['workspace'] == str(served.root)
    assert 'runs.list' in session['tools'] and 'task.start' in session['tools']
    assert not {'init', 'approve', 'harness.init', 'handoffs.approve'} & set(session['tools'])


def test_tool_calls_return_the_core_envelope_unchanged(served):
    via_http = call(served, 'inputs.validate')
    direct = HarnessClient(served.root).call('inputs.validate', request())
    assert via_http == direct
    assert via_http['ok'] is True and via_http['data']['total_rows'] == 1889
    failure = call(served, 'task.status', run_id='run_' + '0' * 32)
    assert failure['ok'] is False and failure['error']['code'] == 'NOT_FOUND'


def test_create_over_http_is_shared_with_python_and_idempotent(served):
    args = dict(idempotency_key='ui-create', workflow_id='paramaterial_tensile.v1')
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: call(served, 'task.create', **args), range(4)))
    assert all(item['ok'] for item in results), results
    assert len({item['data']['run_id'] for item in results}) == 1
    listed = HarnessClient(served.root).call('runs.list', request())['data']
    assert listed['total'] == 1 and listed['items'][0]['run_id'] == results[0]['data']['run_id']
    assert call(served, 'task.create', **args) == results[0]


@pytest.mark.parametrize('host', ['evil.example:80', 'attacker.localhost', '127.0.0.1', ''])
def test_foreign_or_missing_host_is_denied_before_any_call(served, host):
    status, _, data = send(served, 'POST', '/api/tools/inputs.validate', request(), host=host)
    assert status == 403 and json.loads(data)['transport_error'] == 'HOST_DENIED'


@pytest.mark.parametrize('headers', [{'Origin': 'http://evil.example'}, {'Origin': 'null'},
                                     {'Sec-Fetch-Site': 'cross-site'}])
def test_foreign_origin_is_denied(served, headers):
    status, _, data = send(served, 'POST', '/api/tools/inputs.validate', request(), headers=headers)
    assert status == 403 and json.loads(data)['transport_error'] == 'ORIGIN_DENIED'


def test_same_origin_browser_headers_are_accepted(served):
    port = served.server_address[1]
    status, _, data = send(served, 'POST', '/api/tools/inputs.validate', request(),
                           headers={'Origin': f'http://localhost:{port}', 'Sec-Fetch-Site': 'same-origin'},
                           host=f'localhost:{port}')
    assert status == 200 and json.loads(data)['ok'] is True


def test_side_effect_requests_require_token_and_json(served):
    assert send(served, 'POST', '/api/tools/task.create', request(idempotency_key='k', workflow_id='paramaterial_tensile.v1'),
                token=None)[0] == 403
    status, _, _ = send(served, 'POST', '/api/tools/inputs.validate', raw=json.dumps(request()).encode(),
                        headers={'Content-Type': 'text/plain'})
    assert status == 415
    status, _, _ = send(served, 'POST', '/api/tools/inputs.validate', raw=b'{}',
                        headers={'Content-Type': 'application/json', 'Content-Length': str(1024 * 1024 + 1)})
    assert status == 413
    for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{broken', '{"a":"\ud800"}'.encode('utf-8', 'surrogatepass')):
        status, _, data = send(served, 'POST', '/api/tools/inputs.validate', raw=raw,
                               headers={'Content-Type': 'application/json'})
        assert status == 400 and json.loads(data)['transport_error'] == 'INVALID_JSON'
    assert HarnessClient(served.root).call('runs.list', request())['data']['total'] == 0


@pytest.mark.parametrize('path', ['/api/tools/init', '/api/tools/harness.init', '/api/tools/handoffs.approve',
                                  '/api/tools/inputs.validate/../task.start', '/api/call'])
def test_unregistered_and_operator_operations_are_not_reachable(served, path):
    assert send(served, 'POST', path, request())[0] == 404


def test_denied_requests_with_a_body_still_receive_the_error_response(served):
    # A denial closes the connection; unread request bytes would make Windows reset it before the client reads the reply.
    padded = request(padding='x' * (512 * 1024))
    for _ in range(20):
        status, _, data = send(served, 'POST', '/api/tools/inputs.validate', padded, host='evil.example:80')
        assert status == 403 and json.loads(data)['transport_error'] == 'HOST_DENIED'
        status, _, data = send(served, 'POST', '/api/tools/handoffs.approve', padded)
        assert status == 404 and json.loads(data)['transport_error'] == 'NOT_FOUND'


def test_wrong_methods_and_paths_do_not_leak_files(served):
    assert send(served, 'GET', '/api/tools/inputs.validate')[0] == 405
    assert send(served, 'PUT', '/api/tools/inputs.validate', request())[0] == 405
    for path in ('/static/../server.py', '/static/server.py', '/static/%2e%2e/server.py',
                 '/workspace.json', '/harness.sqlite3', '/static/'):
        assert send(served, 'GET', path)[0] == 404, path


def test_interpreter_mismatch_refuses_to_serve(tmp_path):
    root = tmp_path / 'workspace'
    initialize_workspace(root, CASE)
    policy = json.loads((root / 'workspace.json').read_text(encoding='utf-8'))
    check_interpreter(policy)
    with pytest.raises(StartupError):
        check_interpreter(policy, tmp_path / 'other' / 'python.exe')
    with pytest.raises(StartupError):
        HarnessUIServer(root, token=TOKEN, executable=tmp_path / 'other' / 'python.exe')


def test_short_token_is_refused(tmp_path):
    root = tmp_path / 'workspace'
    initialize_workspace(root, CASE)
    with pytest.raises(StartupError):
        HarnessUIServer(root, token='short')


def test_uninitialized_workspace_prints_operator_guidance_and_creates_nothing(tmp_path):
    missing = tmp_path / 'not-initialized'
    result = subprocess.run([sys.executable, '-B', '-m', 'experiment_to_cpfe_harness_ui', '--workspace', str(missing),
                             '--no-browser'], capture_output=True, text=True, encoding='utf-8', timeout=60,
                            env=dict(os.environ, PYTHONIOENCODING='utf-8'))
    assert result.returncode == 2
    assert 'harness init' in result.stderr and str(missing) in result.stderr
    assert not missing.exists()
