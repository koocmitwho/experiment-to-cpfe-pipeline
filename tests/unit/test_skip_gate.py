"""Run real child pytest sessions to exercise collection and runtime skips."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


def run_child(tmp_path, code, *, profile="offline", filename="test_probe.py", environment=None):
    shutil.copyfile(Path(__file__).resolve().parents[1] / "conftest.py", tmp_path / "conftest.py")
    target = tmp_path / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(code, encoding="utf-8")
    (tmp_path / "test_pass.py").write_text("def test_pass():\n    assert 2 + 2 == 4\n")
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTEST_ADDOPTS="",
               EXP2CPFE_TEST_PROFILE=profile)
    for key in ("EXP2CPFE_RUN_ABAQUS", "EXP2CPFE_WHEEL_DIR"):
        env.pop(key, None)
    env.update(environment or {})
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-rs", "--strict-markers"],
                          cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)


@pytest.mark.parametrize("code", [
    "import pytest\ndef test_probe():\n    pytest.skip('intentional gate probe')\n",
    "import pytest\n@pytest.mark.skip(reason='intentional gate probe')\ndef test_probe():\n    pass\n",
    "import pytest\npytest.skip('intentional gate probe', allow_module_level=True)\n",
    "import pytest\npytest.importorskip('exp2cpfe_deliberately_absent_dependency')\n",
])
def test_unexpected_skips_fail_real_pytest_sessions(tmp_path, code):
    result = run_child(tmp_path, code)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Unexpected skips" in result.stdout
    assert "test_probe.py" in result.stdout


MISSING_TORCH = """
import importlib.abc
import sys
import pytest
class MissingTorch(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'torch':
            raise ModuleNotFoundError("No module named 'torch'", name='torch')
sys.meta_path.insert(0, MissingTorch())
def test_probe():
    pytest.importorskip('torch')
"""


@pytest.mark.parametrize("profile,expected", [("offline", 0), ("cpu-training", 1), ("ml", 1)])
def test_missing_torch_is_allowed_only_in_offline_sessions(tmp_path, profile, expected):
    result = run_child(tmp_path, MISSING_TORCH, profile=profile)
    assert result.returncode == expected, result.stdout + result.stderr
    assert "1 skipped" in result.stdout


@pytest.mark.parametrize("filename,name,reason", [
    ("tests/integration/test_abaqus_optional.py", "test_user_supplied_real_abaqus_roundtrip",
     "real Abaqus integration is opt-in via EXP2CPFE_RUN_ABAQUS=1"),
    ("tests/integration/test_installed_wheel.py", "test_wheel_installation_outside_checkout",
     "set EXP2CPFE_WHEEL_DIR after building the wheel"),
])
def test_disabled_opt_in_integration_checks_are_allowed(tmp_path, filename, name, reason):
    code = f"import pytest\ndef {name}():\n    pytest.skip({reason!r})\n"
    result = run_child(tmp_path, code, filename=filename, profile="ml")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 skipped" in result.stdout


def test_a_random_skip_cannot_borrow_an_opt_in_reason(tmp_path):
    result = run_child(tmp_path, "import pytest\ndef test_probe():\n    pytest.skip('set EXP2CPFE_WHEEL_DIR after building the wheel')\n")
    assert result.returncode == 1, result.stdout + result.stderr


def test_enabled_solver_check_must_execute(tmp_path):
    result = run_child(tmp_path,
        "import pytest\ndef test_user_supplied_real_abaqus_roundtrip():\n    pytest.skip('real Abaqus integration is opt-in via EXP2CPFE_RUN_ABAQUS=1')\n",
        filename="tests/integration/test_abaqus_optional.py", environment={"EXP2CPFE_RUN_ABAQUS": "1"})
    assert result.returncode == 1, result.stdout + result.stderr
