"""Real owned processes expose backend identity, lifecycle and resource mistakes."""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import pytest


def backend():
    return importlib.import_module("experiment_to_cpfe.harness.backends.local")


def wait_for(path: Path, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(.02)
    assert path.exists(), f"owned fixture did not publish {path.name}"


def child_env() -> dict[str, str]:
    return {**os.environ, "PYTHONPATH": str(Path("src").resolve())}


def launch(tmp_path: Path, source: str):
    return backend().spawn_worker(
        [sys.executable, "-c", source], cwd=tmp_path,
        stdout=tmp_path / "stdout.txt", stderr=tmp_path / "stderr.txt", env=child_env(),
    )


def cleanup(process) -> None:
    if process.poll() is None:
        identity = backend().process_identity(process.pid)
        assert backend().stop_process(identity), "owned test process could not be stopped"
    process.wait(timeout=10)


def test_identity_detects_real_exit_and_rejects_pid_reuse(tmp_path):
    process = launch(tmp_path, "import time; time.sleep(30)")
    try:
        identity = backend().process_identity(process.pid)
        assert identity["pid"] == process.pid
        assert identity["host"] == socket.gethostname()
        assert identity["started"]
        assert backend().probe_process(identity) == "running"
        wrong = {**identity, "started": identity["started"] + "-different-instance"}
        assert backend().probe_process(wrong) == "stopped"
        assert backend().stop_process(wrong) is False
        assert process.poll() is None
        assert backend().stop_process(identity) is True
        process.wait(timeout=10)
        assert backend().probe_process(identity) == "stopped"
        with pytest.raises(ProcessLookupError):
            backend().process_identity(process.pid)
    finally:
        cleanup(process)


def test_unreachable_or_malformed_identity_is_unknown_and_never_stopped():
    identity = backend().process_identity(os.getpid())
    for other in ({**identity, "host": "unreachable-other-host"}, {},
                  {**identity, "pid": True}, {**identity, "started": ""}):
        assert backend().probe_process(other) == "unknown"
        assert backend().stop_process(other) is False


def test_stop_refuses_a_live_process_not_owned_by_this_backend():
    identity = backend().process_identity(os.getpid())
    assert backend().stop_process(identity) is False
    assert backend().probe_process(identity) == "running"


def test_spawn_is_nonblocking_and_preserves_literal_argv_environment_and_streams(tmp_path):
    source = (
        "import os,sys,time,pathlib; "
        "print(sys.argv[1],flush=True); print(os.environ['HARNESS_TEST_VALUE'],file=sys.stderr,flush=True); "
        "pathlib.Path('ready').write_text(os.getcwd()); time.sleep(30)"
    )
    started = time.monotonic()
    process = backend().spawn_worker(
        [sys.executable, "-c", source, "literal & $HOME; | > value"], cwd=tmp_path,
        stdout=tmp_path / "out.txt", stderr=tmp_path / "err.txt",
        env={**child_env(), "HARNESS_TEST_VALUE": "inherited-explicit-value"},
    )
    try:
        assert time.monotonic() - started < 5
        wait_for(tmp_path / "ready")
        assert Path((tmp_path / "ready").read_text()) == tmp_path
        assert (tmp_path / "out.txt").read_text().strip() == "literal & $HOME; | > value"
        assert (tmp_path / "err.txt").read_text().strip() == "inherited-explicit-value"
        assert process.poll() is None
    finally:
        cleanup(process)


def test_spawn_does_not_overwrite_existing_logs(tmp_path):
    output = tmp_path / "stdout.txt"
    output.write_text("previous attempt evidence")
    with pytest.raises(FileExistsError):
        launch(tmp_path, "raise RuntimeError('must not launch')")
    assert output.read_text() == "previous attempt evidence"


def test_stop_confirms_entire_owned_tree_has_stopped(tmp_path):
    child_code = "import pathlib,time; pathlib.Path('child-ready').write_text('ready'); time.sleep(30)"
    parent_code = (
        "import json,pathlib,subprocess,sys,time; "
        f"child=subprocess.Popen([sys.executable,'-c',{child_code!r}]); "
        "pathlib.Path('child.json').write_text(json.dumps({'pid':child.pid})); time.sleep(30)"
    )
    process = launch(tmp_path, parent_code)
    try:
        wait_for(tmp_path / "child-ready")
        child_pid = json.loads((tmp_path / "child.json").read_text())["pid"]
        child_identity = backend().process_identity(child_pid)
        assert backend().probe_process(child_identity) == "running"
        assert backend().stop_process(backend().process_identity(process.pid)) is True
        assert backend().probe_process(child_identity) == "stopped"
    finally:
        cleanup(process)


def test_owned_worker_survives_launcher_exit_and_can_be_stopped_from_new_caller(tmp_path):
    code = (
        "import json,os,pathlib,sys; from experiment_to_cpfe.harness.backends.local import spawn_worker,process_identity; "
        "p=spawn_worker([sys.executable,'-c','import time; time.sleep(30)'],cwd=pathlib.Path.cwd(),"
        "stdout=pathlib.Path('worker-out.txt'),stderr=pathlib.Path('worker-err.txt'),env=dict(os.environ)); "
        "pathlib.Path('identity.json').write_text(json.dumps(process_identity(p.pid)))"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=child_env(),
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    identity = json.loads((tmp_path / "identity.json").read_text())
    try:
        assert backend().probe_process(identity) == "running"
        assert backend().stop_process(identity) is True
        assert backend().probe_process(identity) == "stopped"
    finally:
        if backend().probe_process(identity) == "running":
            assert backend().stop_process(identity)


def test_cpu_limit_is_applied_in_worker_and_inherited_by_child(tmp_path):
    source = (
        "import json,os,pathlib,subprocess,sys; "
        "from experiment_to_cpfe.harness.backends.local import constrain_cpu; "
        "report=constrain_cpu(); "
        "child=subprocess.check_output([sys.executable,'-c',"
        "'import os,json; print(json.dumps({k:os.environ.get(k) for k in (\"OMP_NUM_THREADS\",\"OPENBLAS_NUM_THREADS\",\"MKL_NUM_THREADS\")}))'],text=True); "
        "pathlib.Path('limits.json').write_text(json.dumps({'report':report,'child':json.loads(child)}))"
    )
    process = launch(tmp_path, source)
    try:
        assert process.wait(timeout=15) == 0, (tmp_path / "stderr.txt").read_text()
        limits = json.loads((tmp_path / "limits.json").read_text())
        assert limits["report"]["cpu_count"] == 1
        assert limits["report"]["enforcement"] == "affinity"
        assert limits["report"]["scope"] == "current_process_and_inheriting_children"
        assert limits["report"]["observed_cpu_count"] == 1
        assert set(limits["child"].values()) == {"1"}
    finally:
        cleanup(process)


def test_claimed_worker_identity_can_stop_its_tree_even_with_interpreter_launcher(tmp_path):
    source = (
        "import json,os,pathlib,time; "
        "from experiment_to_cpfe.harness.backends.local import constrain_cpu,process_identity; "
        "constrain_cpu(); pathlib.Path('claimed.json').write_text(json.dumps(process_identity(os.getpid()))); "
        "time.sleep(30)"
    )
    process = launch(tmp_path, source)
    try:
        wait_for(tmp_path / "claimed.json")
        identity = json.loads((tmp_path / "claimed.json").read_text())
        assert backend().stop_process(identity) is True
        assert backend().probe_process(identity) == "stopped"
        process.wait(timeout=10)
    finally:
        cleanup(process)


def test_worker_exit_does_not_leave_a_computing_child(tmp_path):
    child_code = "import pathlib,time; pathlib.Path('child-ready').write_text('ready'); time.sleep(30)"
    source = (
        "import json,pathlib,subprocess,sys,time; "
        f"p=subprocess.Popen([sys.executable,'-c',{child_code!r}]); "
        "pathlib.Path('child.json').write_text(json.dumps({'pid':p.pid})); "
        "time.sleep(1)"
    )
    process = launch(tmp_path, source)
    child_identity = None
    try:
        wait_for(tmp_path / "child-ready")
        child_identity = backend().process_identity(json.loads((tmp_path / "child.json").read_text())["pid"])
        process.wait(timeout=10)
        deadline = time.monotonic() + 5
        while backend().probe_process(child_identity) == "running" and time.monotonic() < deadline:
            time.sleep(.02)
        if os.name == "nt":
            assert backend().probe_process(child_identity) == "stopped"
        else:
            pytest.skip("Linux session backend has no parent-death containment; supervisor must remain alive")
    finally:
        cleanup(process)
        if child_identity and backend().probe_process(child_identity) == "running":
            # Only the exact child instance created above is eligible for test cleanup.
            if backend().process_identity(child_identity["pid"])["started"] == child_identity["started"]:
                os.kill(child_identity["pid"], 9)
