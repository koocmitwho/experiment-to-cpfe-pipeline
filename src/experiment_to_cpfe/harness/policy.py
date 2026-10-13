"""Operator configuration is deliberately absent from the agent tool registry."""
import hashlib
import json
from pathlib import Path
import sys

from .contracts import Budget, HarnessError
from .store import dumps


def digest(value):
    return hashlib.sha256(dumps(value).encode('utf-8')).hexdigest()


def read_policy(root):
    root = Path(root).resolve(strict=True)
    path = root / 'workspace.json'
    if path.resolve().parent != root:
        raise HarnessError('WORKSPACE_DENIED', 'Workspace configuration escapes its registered root.')
    return json.loads(path.read_text(encoding='utf-8'))


def budget_within(requested, authorized):
    requested = Budget.model_validate(requested).model_dump()
    for key, value in requested.items():
        if value > authorized[key]:
            raise HarnessError('BUDGET_EXCEEDED', 'Requested budget exceeds the operator-authorized limit.', field='budget.' + key)
    return requested


def source_identity():
    root = Path(__file__).resolve().parents[1]
    files = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(root.rglob('*')) if p.is_file() and p.suffix in {'.py', '.yaml'}}
    return digest(files)


def execution_environment():
    from .workflows.paramaterial import environment_identity
    return {'python_executable': str(Path(sys.executable).resolve()),
            'python_version': list(sys.version_info[:3]),
            'dependencies': environment_identity(), 'package_code_sha256': source_identity()}
