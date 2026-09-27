import sys
import os
import pytest
from pathlib import Path


def request(tmp_path, *, command=None, stage="analysis", user_subroutine=None):
    from experiment_to_cpfe.solvers.abaqus.runner import (
        AbaqusRunRequest,
        SolverStage,
    )

    work_dir = tmp_path / "solver"
    work_dir.mkdir()
    inp = work_dir / "model.inp"
    inp.write_text("*HEADING\n", encoding="utf-8")
    return AbaqusRunRequest(
        abaqus_command=command
        or (sys.executable, str(Path("tests/fixtures/fake_solver.py").resolve())),
        job_name="synthetic",
        inp_path=inp,
        work_dir=work_dir,
        stage=SolverStage(stage),
        user_subroutine=user_subroutine,
        cpus=1,
        timeout_seconds=10,
    )


def test_runner_records_completed_analysis_with_artifact_evidence(tmp_path):
    from experiment_to_cpfe.solvers.abaqus.runner import run_abaqus

    result = run_abaqus(request(tmp_path))

    assert result.status == "completed"
    assert result.return_code == 0
    assert result.compile_link_status == "not_required"
    assert {path.suffix for path in result.artifacts} == {
        ".odb",
        ".sta",
        ".dat",
        ".msg",
    }


def test_runner_marks_missing_output_as_failure(tmp_path, monkeypatch):
    from experiment_to_cpfe.solvers.abaqus.runner import run_abaqus

    monkeypatch.setenv("FAKE_SOLVER_NO_OUTPUT", "1")
    result = run_abaqus(request(tmp_path))

    assert result.status == "failed"
    assert any("expected artifact" in item for item in result.limitations)


def test_runner_marks_aborted_sta_as_failure(tmp_path, monkeypatch):
    from experiment_to_cpfe.solvers.abaqus.runner import run_abaqus

    monkeypatch.setenv("FAKE_SOLVER_ABORT", "1")
    result = run_abaqus(request(tmp_path))

    assert result.status == "failed"
    assert any("STA" in item for item in result.limitations)


def test_runner_marks_missing_command_as_blocked(tmp_path):
    from experiment_to_cpfe.solvers.abaqus.runner import run_abaqus

    result = run_abaqus(
        request(tmp_path, command=("definitely-not-an-abaqus-command",))
    )

    assert result.status == "blocked"
    assert result.return_code is None


def test_datacheck_does_not_require_odb(tmp_path):
    from experiment_to_cpfe.solvers.abaqus.runner import run_abaqus

    result = run_abaqus(request(tmp_path, stage="datacheck"))

    assert result.status == "completed"
    assert all(path.suffix != ".odb" for path in result.artifacts)


def test_user_subroutine_requires_compile_and_link_evidence(tmp_path):
    from experiment_to_cpfe.solvers.abaqus.runner import run_abaqus

    user = tmp_path / "umat.for"
    user.write_text("C synthetic fixture\n", encoding="ascii")
    result = run_abaqus(request(tmp_path, user_subroutine=user))

    assert result.status == "failed"
    assert result.compile_link_status == "missing_evidence"


def test_user_subroutine_records_compile_and_link_success(tmp_path, monkeypatch):
    from experiment_to_cpfe.solvers.abaqus.runner import run_abaqus

    user = tmp_path / "umat.for"
    user.write_text("C synthetic fixture\n", encoding="ascii")
    monkeypatch.setenv("FAKE_SOLVER_COMPILE_SUCCESS", "1")
    result = run_abaqus(request(tmp_path, user_subroutine=user))

    assert result.status == "completed"
    assert result.compile_link_status == "completed"
    assert result.compile_status == "completed"
    assert result.link_status == "completed"


def test_link_failure_preserves_successful_compile_evidence(tmp_path, monkeypatch):
    from experiment_to_cpfe.solvers.abaqus.runner import run_abaqus

    user = tmp_path / "umat.for"
    user.write_text("C synthetic fixture\n", encoding="ascii")
    monkeypatch.setenv("FAKE_SOLVER_LINK_FAILURE", "1")
    result = run_abaqus(request(tmp_path, user_subroutine=user))

    assert result.status == "failed"
    assert result.compile_status == "completed"
    assert result.link_status == "failed"
    assert result.compile_link_status == "failed"


def test_compile_end_marker_does_not_override_compiler_error(tmp_path, monkeypatch):
    from experiment_to_cpfe.solvers.abaqus.runner import run_abaqus

    user = tmp_path / "umat.for"
    user.write_text("C synthetic fixture\n", encoding="ascii")
    monkeypatch.setenv("FAKE_SOLVER_COMPILE_FAILURE", "1")
    result = run_abaqus(request(tmp_path, user_subroutine=user))

    assert result.status == "failed"
    assert result.compile_status == "failed"
    assert result.link_status == "missing_evidence"


def test_timeout_retains_partial_binary_output(tmp_path, monkeypatch):
    import subprocess
    from experiment_to_cpfe.solvers.abaqus.runner import run_abaqus

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 10, output=b"compiler started\xff", stderr=b"partial error")

    monkeypatch.setattr("experiment_to_cpfe.solvers.abaqus.runner._execute_process", timeout)
    result = run_abaqus(request(tmp_path))

    assert result.status == "failed"
    assert result.stdout_path.read_text(encoding="utf-8").startswith("compiler started")
    assert result.stderr_path.read_text(encoding="utf-8") == "partial error"


def test_datacheck_error_files_cannot_count_as_success(tmp_path, monkeypatch):
    import subprocess
    from experiment_to_cpfe.solvers.abaqus.runner import run_abaqus
    req = request(tmp_path, stage="datacheck")
    def execute(command, **kwargs):
        (req.work_dir/'synthetic.dat').write_text('***ERROR: MISSING MATERIAL\nDATACHECK COMPLETE')
        (req.work_dir/'synthetic.msg').write_text('ERROR IN INPUT FILE')
        return subprocess.CompletedProcess(command,0,'','')
    monkeypatch.setattr('experiment_to_cpfe.solvers.abaqus.runner._execute_process',execute)
    assert run_abaqus(req).status == 'failed'


def test_datacheck_needs_positive_completion_marker(tmp_path, monkeypatch):
    import subprocess
    from experiment_to_cpfe.solvers.abaqus.runner import run_abaqus
    req = request(tmp_path, stage="datacheck")
    def execute(command, **kwargs):
        (req.work_dir/'synthetic.dat').write_text('processing started')
        (req.work_dir/'synthetic.msg').write_text('no final state')
        return subprocess.CompletedProcess(command,0,'','')
    monkeypatch.setattr('experiment_to_cpfe.solvers.abaqus.runner._execute_process',execute)
    assert run_abaqus(req).status == 'failed'


def test_license_failure_is_blocked(tmp_path, monkeypatch):
    import subprocess
    from experiment_to_cpfe.solvers.abaqus.runner import run_abaqus
    monkeypatch.setattr('experiment_to_cpfe.solvers.abaqus.runner._execute_process', lambda cmd, **kwargs: subprocess.CompletedProcess(cmd,1,'','License checkout failed'))
    assert run_abaqus(request(tmp_path)).status == 'blocked'


TIMEOUT_SECONDS = 1
CHILD_SLEEP_SECONDS = 6
MIN_TIMEOUT_FRACTION = 0.5


def test_timeout_stops_owned_child_process(tmp_path):
    import subprocess
    import csv
    from dataclasses import replace
    from experiment_to_cpfe.solvers.abaqus.runner import run_abaqus
    import time
    child_code = f"import time;time.sleep({CHILD_SLEEP_SECONDS})"
    code = (
        "import subprocess,sys,time;"
        f"p=subprocess.Popen([sys.executable,'-c',{child_code!r}]);"
        "print(p.pid,flush=True);"
        f"time.sleep({CHILD_SLEEP_SECONDS})"
    )
    req=replace(request(tmp_path,command=(sys.executable,'-c',code)),timeout_seconds=TIMEOUT_SECONDS)
    started=time.monotonic()
    result=run_abaqus(req)
    elapsed=time.monotonic()-started
    pid=int(result.stdout_path.read_text().splitlines()[0])
    if os.name == 'nt':
        probe=subprocess.run(['tasklist','/FI',f'PID eq {pid}','/FO','CSV','/NH'],capture_output=True,text=True)
        alive=any(len(row)>1 and row[1]==str(pid) for row in csv.reader(probe.stdout.splitlines()))
    else:
        probe=subprocess.run(['ps','-o','stat=','-p',str(pid)],capture_output=True,text=True)
        # A killed child may remain a zombie until the host reaps it.
        alive=bool(probe.stdout.strip()) and not probe.stdout.strip().startswith('Z')
    try:
        assert result.status=='failed'
        assert not alive, 'timeout left the owned child process running'
        # Detect an immediate return, allowing clock/scheduling variation.
        assert elapsed >= TIMEOUT_SECONDS * MIN_TIMEOUT_FRACTION, 'timeout returned before the requested wait'
        # Give CI scheduling and process-tree cleanup headroom after the timeout,
        # while keeping a full timeout interval before the child's natural exit.
        assert elapsed < CHILD_SLEEP_SECONDS - TIMEOUT_SECONDS, 'timeout waited for the un-terminated child to exit naturally'
    finally:
        if alive:
            if os.name == 'nt':
                subprocess.run(['taskkill','/PID',str(pid),'/T','/F'],capture_output=True,check=False)
            else:
                import signal
                os.kill(pid, signal.SIGKILL)
