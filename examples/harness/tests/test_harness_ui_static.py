"""Static front end: served safely, calls only published tools, and sends requests the core accepts."""
import http.client
import json
from pathlib import Path
import re
import threading

import pytest

from experiment_to_cpfe.harness import initialize_workspace
from experiment_to_cpfe_harness_ui.server import STATIC_DIR, HarnessUIServer


ROOT = Path(__file__).resolve().parents[3]
CASE = ROOT / 'examples' / 'paramaterial_tensile'
TOKEN = 'test-token-' + 'y' * 40
APP = (STATIC_DIR / 'app.js').read_text(encoding='utf-8')
INDEX = (STATIC_DIR / 'index.html').read_text(encoding='utf-8')
STYLE = (STATIC_DIR / 'style.css').read_text(encoding='utf-8')


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


def get(server, path):
    port = server.server_address[1]
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=60)
    connection.request('GET', path, headers={'Host': f'127.0.0.1:{port}'})
    response = connection.getresponse()
    result = response.status, dict(response.getheaders()), response.read()
    connection.close()
    return result


def call(server, tool, **fields):
    """Same envelope and headers as app.js api()."""
    port = server.server_address[1]
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=120)
    body = json.dumps(dict(schema_version='harness.v1', request_id='ui-static', workspace_id='local', **fields)).encode('utf-8')
    connection.request('POST', f'/api/tools/{tool}', body=body, headers={
        'Host': f'127.0.0.1:{port}', 'Origin': f'http://127.0.0.1:{port}', 'Sec-Fetch-Site': 'same-origin',
        'Content-Type': 'application/json', 'X-Harness-Token': TOKEN})
    response = connection.getresponse()
    data = response.read()
    connection.close()
    assert response.status == 200, data
    return json.loads(data)


@pytest.mark.parametrize('path, kind', [('/', 'text/html'), ('/static/app.js', 'text/javascript'),
                                        ('/static/style.css', 'text/css'), ('/static/icon.svg', 'image/svg+xml')])
def test_every_page_asset_is_served_with_security_headers(served, path, kind):
    status, headers, data = get(served, path)
    assert status == 200 and data
    assert headers['Content-Type'].startswith(kind)
    assert "script-src 'self'" in headers['Content-Security-Policy']
    assert headers['X-Content-Type-Options'] == 'nosniff'


def test_page_has_no_inline_code_or_external_resources():
    # CSP forbids inline script and style; anything inline would silently not run.
    assert not re.search(r'<script(?![^>]*\bsrc=)[^>]*>', INDEX)
    assert not re.search(r'\son[a-z]+\s*=', INDEX) and 'style=' not in INDEX and '<style' not in INDEX
    referenced = set(re.findall(r'(?:src|href)="(/static/[^"]+)"', INDEX))
    assert referenced == {'/static/app.js', '/static/style.css', '/static/icon.svg'}
    # The SVG namespace URI is an identifier for createElementNS, never fetched.
    assert APP.count("'http://www.w3.org/2000/svg'") == 1
    for text in (INDEX, APP.replace("'http://www.w3.org/2000/svg'", ''), STYLE):
        assert not re.search(r'https?://', text), 'no external resources or endpoints'
        assert '@import' not in text and 'url(' not in text


def test_script_builds_dom_without_html_injection_or_eval():
    for forbidden in ('innerHTML', 'outerHTML', 'insertAdjacentHTML', 'document.write', 'eval(', 'new Function',
                      "setAttribute('style'", '.style.', 'localStorage'):
        assert forbidden not in APP, forbidden


def test_script_calls_only_published_non_operator_tools(served):
    used = set(re.findall(r"api\('([a-z]+\.[a-z]+)'", APP)) | set(re.findall(r"tool = '([a-z]+\.[a-z]+)'", APP))
    assert used == {'capabilities.get', 'inputs.validate', 'runs.list', 'task.plan', 'task.create', 'task.start',
                    'task.status', 'events.list', 'task.control', 'task.reconcile', 'evaluation.start',
                    'artifacts.list', 'artifacts.read', 'reports.get', 'handoffs.list', 'handoffs.submit'}
    session = json.loads(get_with_token(served, '/api/session'))
    assert used <= set(session['tools'])
    assert 'inputs.register' not in APP and 'approve_handoff' not in APP and 'harness init' not in APP


def get_with_token(server, path):
    port = server.server_address[1]
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=60)
    connection.request('GET', path, headers={'Host': f'127.0.0.1:{port}', 'X-Harness-Token': TOKEN})
    data = connection.getresponse().read()
    connection.close()
    return data


def test_unsupported_capabilities_have_no_clickable_entry():
    # These words appear only in the read-only "unsupported" glossary shown in the capabilities dialog.
    block = APP[APP.index('const UNSUPPORTED = {'):APP.index('};', APP.index('const UNSUPPORTED = {'))]
    for word in ('Abaqus', '训练', '远程执行'):
        assert APP.count(word) == block.count(word) == 1, word
    assert 'GPU 不支持' in APP


def test_mutation_keys_are_bound_to_run_and_state_version():
    for action in ('start', 'evaluate', 'reconcile'):
        assert f'`ui:{action}:${{s.run_id}}:v${{v}}`' in APP
    assert '`ui:control:${name}:${s.run_id}:v${v}`' in APP
    assert "randomId('ui:create:')" in APP and 'sessionStorage' in APP
    assert '`ui:handoff:${s.run_id}:v${v}:${fingerprint(' in APP


def test_review_panel_only_generates_the_operator_command():
    # Approval stays an operator CLI action; the page prints the command with reviewer and basis left for the operator.
    assert "'pipeline harness approve'" in APP and '--reviewer "<审核人>"' in APP and '--basis "<审核依据>"' in APP
    assert 'approve_handoff' not in APP and "api('handoffs.approve'" not in APP


def test_request_shapes_sent_by_the_page_are_accepted_by_the_core(served):
    """Mirror app.js payloads without starting any computation (task.start is never called here)."""
    assert call(served, 'capabilities.get')['ok']
    assert call(served, 'inputs.validate')['data']['valid'] is True
    listed = call(served, 'runs.list', limit=200)
    assert listed['ok'] and listed['data']['total'] == 0
    budget = dict(wall_seconds=600, storage_bytes=1024 * 1048576, retries=1)  # integers, as the form sends them
    plan = call(served, 'task.plan', workflow_id='paramaterial_tensile.v1', budget=budget, require_review=False)
    assert plan['ok'], plan
    lowered = call(served, 'task.plan', workflow_id='paramaterial_tensile.v1',
                   budget=dict(wall_seconds=120.5, storage_bytes=10 * 1048576, retries=0), require_review=True)
    assert lowered['ok'] and lowered['data']['confirmations'] == ['operator_review'], lowered
    args = dict(workflow_id='paramaterial_tensile.v1', budget=budget, require_review=False,
                expected_plan_digest=plan['data']['plan_digest'], replicate=False)
    created = call(served, 'task.create', idempotency_key='ui:create:abc', **args)
    assert created['ok'] and created['data']['deduplicated'] is False, created
    run = created['data']
    again = call(served, 'task.create', idempotency_key='ui:create:def', **args)
    assert again['data']['run_id'] == run['run_id'] and again['data']['deduplicated'] is True
    status = call(served, 'task.status', run_id=run['run_id'])
    assert status['ok'] and status['data']['execution_status'] == 'ready'
    events = call(served, 'events.list', run_id=run['run_id'], cursor=0, limit=500)
    assert events['ok'] and events['data']['items'][0]['kind'] == 'task_frozen'
    v = run['state_version']
    assert call(served, 'artifacts.list', run_id=run['run_id'], cursor=0, limit=500)['data'] == {'items': [], 'next_cursor': None}
    report = call(served, 'reports.get', run_id=run['run_id'])
    assert report['ok'] and report['data']['overall_acceptance'] == 'not_assessed', report
    assert call(served, 'handoffs.list', run_id=run['run_id'], limit=100)['data']['items'] == []
    missing = 'artifact_' + '0' * 32
    for view in (dict(view='csv', columns=['original_strain', 'corrected_strain', 'engineering_stress_MPa']),
                 dict(view='json', limit=1), dict(view='text', limit=200),
                 dict(view='hdf5', dataset='measured/measured_observations/columns/Strain', limit=100)):
        read = call(served, 'artifacts.read', artifact_id=missing, offset=0, **dict(dict(limit=500), **view))
        assert read['ok'] is False and read['error']['code'] == 'NOT_FOUND', read
    submit = call(served, 'handoffs.submit', run_id=run['run_id'], idempotency_key=f"ui:handoff:{run['run_id']}:v{v}:0badc0de",
                  expected_state_version=v, handoff_id='handoff_' + '0' * 32, attempt_id='attempt_' + '0' * 32,
                  approval_id='approval_x', evidence_ids=[missing])
    assert submit['ok'] is False and submit['error']['code'] != 'INVALID_REQUEST', submit
    assert call(served, 'task.status', run_id=run['run_id'])['data']['state_version'] == v
    reconcile = call(served, 'task.reconcile', run_id=run['run_id'], idempotency_key=f"ui:reconcile:{run['run_id']}:v{v}")
    assert reconcile['ok'] and reconcile['data']['execution_status'] == 'ready'
    evaluate = call(served, 'evaluation.start', run_id=run['run_id'], idempotency_key=f"ui:evaluate:{run['run_id']}:v{v}",
                    expected_state_version=v)
    assert evaluate['ok'] is False and evaluate['error']['code'] == 'PRECONDITION_FAILED'
    paused = call(served, 'task.control', run_id=run['run_id'], idempotency_key=f"ui:control:pause:{run['run_id']}:v{v}",
                  expected_state_version=v, action='pause', reason='界面请求暂停')
    assert paused['ok'] and paused['data']['execution_status'] == 'paused', paused
    stale = call(served, 'task.control', run_id=run['run_id'], idempotency_key=f"ui:control:cancel:{run['run_id']}:v{v}",
                 expected_state_version=v, action='cancel', reason='旧窗口')
    assert stale['ok'] is False and stale['error']['code'] == 'STATE_CONFLICT'
    v = paused['data']['state_version']
    cancelled = call(served, 'task.control', run_id=run['run_id'], idempotency_key=f"ui:control:cancel:{run['run_id']}:v{v}",
                     expected_state_version=v, action='cancel', reason='测试取消')
    assert cancelled['ok'] and cancelled['data']['execution_status'] == 'cancelled', cancelled
    repeat = call(served, 'task.control', run_id=run['run_id'], idempotency_key=f"ui:control:cancel:{run['run_id']}:v{v}",
                  expected_state_version=v, action='cancel', reason='测试取消')
    assert repeat['data'] == cancelled['data']
    changed = call(served, 'task.control', run_id=run['run_id'], idempotency_key=f"ui:control:cancel:{run['run_id']}:v{v}",
                   expected_state_version=v, action='cancel', reason='改了原因')
    assert changed['ok'] is False and changed['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    final = call(served, 'runs.list', limit=200)['data']
    assert final['total'] == 1 and final['items'][0]['execution_status'] == 'cancelled'
    assert final['items'][0]['attempt_count'] == 0
