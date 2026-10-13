"""The UI ships as part of the wheel: a console entry point and every static file."""
from fnmatch import fnmatch
from pathlib import Path
import tomllib

from experiment_to_cpfe_harness_ui import server


ROOT = Path(__file__).resolve().parents[3]
PROJECT = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))


def test_console_entry_point_runs_the_server_main():
    target = PROJECT['project']['scripts']['pipeline-harness-ui']
    module, _, attribute = target.partition(':')
    assert module == server.__name__
    assert getattr(server, attribute) is server.main


def test_package_data_covers_every_static_file():
    patterns = PROJECT['tool']['setuptools']['package-data']['experiment_to_cpfe_harness_ui']
    files = sorted(p.relative_to(server.STATIC_DIR.parent).as_posix()
                   for p in server.STATIC_DIR.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    assert {'static/index.html', 'static/app.js', 'static/style.css', 'static/icon.svg'} <= set(files)
    missing = [f for f in files if not any(fnmatch(f, pattern) for pattern in patterns)]
    assert missing == []
