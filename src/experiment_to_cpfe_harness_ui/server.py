"""Loopback-only HTTP adapter. Every business call goes through HarnessClient.call.

The browser never receives file paths to open: artifacts are read only by
registered artifact_id through artifacts.read. Operator init and approval are
not reachable here. This is not an operating-system sandbox: any process of the
same account can still reach the workspace directly.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import sys
import threading
import webbrowser

MAX_BODY = 1024 * 1024
STATIC_DIR = Path(__file__).resolve().parent / 'static'
STATIC_TYPES = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
                '.css': 'text/css; charset=utf-8', '.svg': 'image/svg+xml'}
SECURITY_HEADERS = {
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Referrer-Policy': 'no-referrer',
    'Content-Security-Policy': ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
                                "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"),
}
TOOL_PATH = re.compile(r'^/api/tools/([a-z]+\.[a-z]+)$')


class StartupError(Exception):
    """Configuration that must be fixed by the operator before serving."""


def check_interpreter(policy, executable=None):
    """Snapshots record the caller's interpreter; workers use policy python_executable."""
    current = Path(executable or sys.executable).resolve()
    registered = Path(policy['python_executable']).resolve()
    if os.path.normcase(str(current)) != os.path.normcase(str(registered)):
        raise StartupError(f'当前解释器 {current} 与工作区登记的解释器 {registered} 不一致。'
                           '请用登记的 python.exe 启动界面，否则新任务会因环境身份不一致而无法执行。')


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate request field')
        result[key] = value
    return result


def _reject_constant(_):
    raise ValueError('nonfinite request value')


def _static_files():
    if not STATIC_DIR.is_dir():
        return {}
    return {path.name: path for path in STATIC_DIR.iterdir()
            if path.is_file() and not path.is_symlink() and path.suffix in STATIC_TYPES}


class HarnessUIServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, workspace, *, token, port=0, client=None, executable=None):
        from experiment_to_cpfe.harness.policy import read_policy
        root = Path(workspace).resolve(strict=True)
        check_interpreter(read_policy(root), executable)
        if client is None:
            from experiment_to_cpfe.harness import HarnessClient
            client = HarnessClient(root)
        if not isinstance(token, str) or len(token) < 32:
            raise StartupError('访问令牌过短。')
        self.root, self.client, self.token = root, client, token
        self.tools = frozenset(item['name'] for item in client.tools())
        self.lock = threading.Lock()
        self.static = _static_files()
        self.started_at = datetime.now(timezone.utc).isoformat()
        super().__init__(('127.0.0.1', port), Handler)
        bound = self.server_address[1]
        self.hosts = frozenset({f'127.0.0.1:{bound}', f'localhost:{bound}'})
        self.origins = frozenset('http://' + host for host in self.hosts)

    @property
    def url(self):
        return f'http://127.0.0.1:{self.server_address[1]}/'

    def call(self, tool, arguments):
        # Same serialization as the MCP adapter; cross-process safety is SQLite's job.
        with self.lock:
            return self.client.call(tool, arguments)


class Handler(BaseHTTPRequestHandler):
    server_version = 'HarnessUI'
    sys_version = ''
    protocol_version = 'HTTP/1.1'

    def log_message(self, format, *args):
        sys.stderr.write('[界面服务] %s %s\n' % (self.command, self.path.split('?')[0]))

    def _send(self, status, body, content_type='application/json; charset=utf-8'):
        payload = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(payload)))
        for key, value in SECURITY_HEADERS.items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(payload)

    def _deny(self, status, code, message):
        self.close_connection = True
        self._discard_body()
        self._send(status, dict(schema_version='harness.v1', ok=False, transport_error=code, safe_message=message))

    def _discard_body(self):
        # Closing a socket with unread request bytes makes the OS reset it (always on Windows), and the
        # client then loses the error reply. Read and drop a bounded body that has not been consumed yet.
        if getattr(self, '_body_consumed', True):
            return
        self._body_consumed = True
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            return
        if 0 < length <= MAX_BODY:
            try:
                self.connection.settimeout(5)
                self.rfile.read(length)
            except OSError:
                pass

    def _trusted_origin(self):
        host = self.headers.get('Host', '')
        if host not in self.server.hosts:
            self._deny(403, 'HOST_DENIED', '仅接受本机地址访问。')
            return False
        origin = self.headers.get('Origin')
        if origin is not None and origin not in self.server.origins:
            self._deny(403, 'ORIGIN_DENIED', '请求来源不是本界面。')
            return False
        if self.headers.get('Sec-Fetch-Site', 'same-origin') not in {'same-origin', 'none'}:
            self._deny(403, 'ORIGIN_DENIED', '请求来源不是本界面。')
            return False
        return True

    def _authorized(self):
        supplied = self.headers.get('X-Harness-Token', '')
        if not hmac.compare_digest(supplied.encode('utf-8'), self.server.token.encode('utf-8')):
            self._deny(403, 'TOKEN_DENIED', '访问令牌无效。请使用启动时打印的地址重新打开界面。')
            return False
        return True

    def do_GET(self):
        self._body_consumed = False
        if not self._trusted_origin():
            return
        path = self.path.split('?', 1)[0]
        if path == '/api/session':
            if self._authorized():
                self._send(200, dict(schema_version='harness.v1', ok=True, workspace=str(self.server.root),
                                     started_at=self.server.started_at, server_pid=os.getpid(),
                                     platform=os.name, tools=sorted(self.server.tools)))
            return
        if path.startswith('/api/'):
            self._deny(405 if TOOL_PATH.match(path) else 404, 'NOT_FOUND', '接口不存在或不支持该方法。')
            return
        name = 'index.html' if path == '/' else path[len('/static/'):] if path.startswith('/static/') else None
        file = self.server.static.get(name) if name else None
        if file is None:
            self._deny(404, 'NOT_FOUND', '页面不存在。')
            return
        self._send(200, file.read_bytes(), STATIC_TYPES[file.suffix])

    def do_POST(self):
        self._body_consumed = False
        if not self._trusted_origin() or not self._authorized():
            return
        match = TOOL_PATH.match(self.path)
        if match is None or match.group(1) not in self.server.tools:
            self._deny(404, 'NOT_FOUND', '工具未注册。')
            return
        if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
            self._deny(415, 'CONTENT_TYPE_DENIED', '请求必须是 application/json。')
            return
        try:
            length = int(self.headers.get('Content-Length', ''))
        except ValueError:
            self._deny(411, 'LENGTH_REQUIRED', '请求缺少长度。')
            return
        if length < 0 or length > MAX_BODY:
            self._deny(413, 'REQUEST_TOO_LARGE', '请求超过 1 MiB。')
            return
        body = self.rfile.read(length)
        self._body_consumed = True
        try:
            arguments = json.loads(body.decode('utf-8'), object_pairs_hook=_unique_object,
                                   parse_constant=_reject_constant)
        except (UnicodeError, ValueError, RecursionError):
            self._deny(400, 'INVALID_JSON', '请求不是合法 JSON。')
            return
        self._send(200, self.server.call(match.group(1), arguments))

    def do_PUT(self):
        self._body_consumed = False
        self._deny(405, 'METHOD_DENIED', '不支持该方法。')

    do_DELETE = do_PATCH = do_PUT


def _guidance(workspace):
    case = Path.cwd() / 'examples' / 'paramaterial_tensile'
    return ('工作区不存在或尚未初始化。初始化是操作者操作，请先在终端执行：\n'
            f'  "{sys.executable}" -m experiment_to_cpfe.cli harness init --workspace "{workspace}" --case-dir "{case}"\n'
            '然后重新启动界面。')


def main(argv=None):
    parser = argparse.ArgumentParser(prog='experiment_to_cpfe_harness_ui', description='本地中文任务界面（仅本机访问）。')
    parser.add_argument('--workspace', required=True, type=Path, help='已由操作者初始化的工作区绝对路径。')
    parser.add_argument('--port', type=int, default=0, help='监听端口，默认随机。只监听 127.0.0.1。')
    parser.add_argument('--no-browser', action='store_true', help='不自动打开浏览器。')
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        print('端口超出范围。', file=sys.stderr)
        return 2
    workspace = args.workspace.absolute()
    if not (workspace / 'workspace.json').is_file():
        print(_guidance(workspace), file=sys.stderr)
        return 2
    try:
        server = HarnessUIServer(workspace, token=secrets.token_urlsafe(32), port=args.port)
    except StartupError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (OSError, ValueError):
        print(_guidance(workspace), file=sys.stderr)
        return 2
    address = server.url + '#token=' + server.token
    print(f'本地任务界面已启动：{address}\n'
          '只接受本机访问。关闭此窗口或按 Ctrl+C 会停止界面服务；'
          '服务停止时正在运行的计算是否继续取决于启动方式，请保持窗口打开直到任务结束。', flush=True)
    if not args.no_browser:
        webbrowser.open(address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
