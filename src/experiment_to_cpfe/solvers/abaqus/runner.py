"""Staged Abaqus execution with artifact and status-file evidence."""

from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
import re
import json
import os
import shutil
import subprocess
import signal
from experiment_to_cpfe.solvers.abaqus.bundle import stage_input_bundle
from experiment_to_cpfe.provenance.solver_fingerprint import capture_solver_fingerprint


class SolverStage(str, Enum):
    DATACHECK = "datacheck"
    ANALYSIS = "analysis"


@dataclass(frozen=True)
class AbaqusRunRequest:
    abaqus_command: tuple[str, ...]
    job_name: str
    inp_path: Path
    work_dir: Path
    stage: SolverStage
    user_subroutine: Path | None
    cpus: int
    timeout_seconds: int
    input_bundle_root: Path | None = None
    input_bundle_manifest: Path | None = None
    input_bundle_destination: Path | None = None
    version_probe_args: tuple[str, ...] = ()


@dataclass(frozen=True)
class SolverRunResult:
    stage: SolverStage
    status: str
    command: tuple[str, ...]
    return_code: int | None
    stdout_path: Path
    stderr_path: Path
    artifacts: tuple[Path, ...]
    compile_link_status: str
    limitations: tuple[str, ...]
    compile_status: str = "unverified"
    link_status: str = "unverified"
    solver_fingerprint: dict[str, object] | None = None


def _compiler_evidence(output: str) -> tuple[str, str]:
    """Recognize ordered Abaqus driver markers, not test-only success text.

    English Standard/Explicit driver output and Intel diagnostics are supported.
    Unrecognized/localized output stays missing_evidence, never completed.
    """
    text = output.upper()
    statuses = []
    for action, errors in (
        ("COMPILING", r"(?:FATAL\s+)?ERROR\s+#\d+|PROBLEM DURING COMPILATION"),
        ("LINKING", r"(?:FATAL\s+)?ERROR\s+LNK\d+|PROBLEM DURING LINKING"),
    ):
        begin = re.search(rf"BEGIN {action} ABAQUS/(?:STANDARD|EXPLICIT) USER SUBROUTINES", text)
        end = re.search(rf"END {action} ABAQUS/(?:STANDARD|EXPLICIT) USER SUBROUTINES", text)
        if re.search(errors, text):
            statuses.append("failed")
        elif begin and end and begin.start() < end.start():
            statuses.append("completed")
        else:
            statuses.append("missing_evidence")
    # A link phase must follow a completed compilation phase in this invocation.
    if statuses == ["completed", "completed"]:
        if text.index("BEGIN LINKING") < text.index("END COMPILING"):
            statuses[1] = "missing_evidence"
    return statuses[0], statuses[1]


def _output_text(value: str | bytes | None) -> str:
    # TimeoutExpired may carry bytes even with subprocess text=True.
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def _execute_process(command, *, cwd, timeout, **ignored):
    """Own a local process group so timeout also stops child solver processes."""
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    with subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, errors="replace", **options) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
            else:
                os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate(timeout=10)
            raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr) from exc
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def expected_artifacts(job_name: str, stage: SolverStage) -> tuple[str, ...]:
    if stage is SolverStage.DATACHECK:
        return (f"{job_name}.dat", f"{job_name}.msg")
    return (
        f"{job_name}.odb",
        f"{job_name}.sta",
        f"{job_name}.dat",
        f"{job_name}.msg",
    )


def _is_ascii_path(path: Path) -> bool:
    try:
        str(path.resolve()).encode("ascii")
    except UnicodeEncodeError:
        return False
    return True


def wrap_batch_command(command: tuple[str, ...]) -> tuple[str, ...]:
    """Treat data arguments literally; cmd metacharacters are unsupported."""
    if not command:
        raise ValueError("Abaqus command is not configured")
    if command[0].lower().endswith((".bat", ".cmd")):
        if any(re.search(r'[&|<>^%!"\r\n]', part) for part in command):
            raise ValueError("batch command arguments contain unsupported shell metacharacters")
        return ("cmd.exe", "/d", "/c", *command)
    return command


def _command(request: AbaqusRunRequest, staged_inp: Path) -> tuple[str, ...]:
    arguments = [
        f"job={request.job_name}",
        f"input={os.path.relpath(staged_inp, request.work_dir)}",
        f"cpus={request.cpus}",
        "interactive",
    ]
    if request.stage is SolverStage.DATACHECK:
        arguments.append("datacheck")
    if request.user_subroutine is not None:
        arguments.append(f"user={request.user_subroutine}")
    return wrap_batch_command((*request.abaqus_command, *arguments))


def _prepare_native(request: AbaqusRunRequest) -> tuple[Path, Path, Path | None, tuple[Path, ...]]:
    root = Path(request.input_bundle_root).resolve()
    manifest_path = Path(request.input_bundle_manifest).resolve() if request.input_bundle_manifest else None
    if manifest_path is None or not manifest_path.is_file() or not manifest_path.is_relative_to(root):
        raise ValueError("native input bundle manifest is required within its root")
    receipt = json.loads(manifest_path.read_text(encoding="utf-8"))
    if receipt.get("schema_version") != "input-bundle-1":
        raise ValueError("unsupported input bundle manifest")
    def relative(value):
        from pathlib import PureWindowsPath
        p = Path(value)
        if p.is_absolute() or PureWindowsPath(value).drive or ".." in p.parts:
            raise ValueError("bundle manifest path must be confined and relative")
        return p
    submit = relative(receipt["submission_dir"])
    entry = relative(receipt["entrypoint"])
    work = Path(request.work_dir).resolve()
    target = Path(request.input_bundle_destination).resolve() if request.input_bundle_destination else work
    if request.input_bundle_destination is None:
        for _ in submit.parts:
            target = target.parent
    if (target / submit).resolve() != work or (root / entry).resolve() != Path(request.inp_path).resolve():
        raise ValueError("native input entrypoint or submission directory disagrees with receipt")
    children = [a for a in receipt["assets"] if a["parent_asset_id"] is not None]
    expected = {str((root / relative(a["relative_path"])).resolve()): a["sha256"] for a in children}
    if len(expected) != len(children) or not expected:
        raise ValueError("bundle manifest has duplicate or empty file entries")
    auxiliary = tuple(Path(p) for p in expected)
    staged_user = None
    if request.user_subroutine is not None:
        user = Path(request.user_subroutine).resolve()
        if str(user) not in expected:
            raise ValueError("user subroutine is not bound in native bundle")
        staged_user = target / user.relative_to(root)
    staged = stage_input_bundle(root / entry, source_root=root, submission_dir=root / submit,
        destination=target, license=children[0].get("license") or "unknown",
        auxiliary_files=auxiliary, expected_hashes=expected)
    copied = tuple(target / Path(p).relative_to(root) for p in expected)
    return staged.entrypoint, staged.manifest_path, staged_user, copied


def run_abaqus(request: AbaqusRunRequest) -> SolverRunResult:
    """Run one local stage; accept success only with stage-specific evidence."""
    work_dir = Path(request.work_dir)
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]*", request.job_name):
        raise ValueError("job name must use ASCII letters, digits, underscores or hyphens")
    stdout_path = work_dir / f"{request.job_name}.{request.stage.value}.stdout.txt"
    stderr_path = work_dir / f"{request.job_name}.{request.stage.value}.stderr.txt"
    compile_link_status = (
        "not_required" if request.user_subroutine is None else "unverified"
    )
    compile_status = link_status = compile_link_status
    command = request.abaqus_command
    inputs = ()
    fingerprint = None
    def result(status, limitations=(), return_code=None, artifacts=()):
        return SolverRunResult(stage=request.stage, status=status, command=command,
            return_code=return_code, stdout_path=stdout_path, stderr_path=stderr_path,
            artifacts=tuple(artifacts), compile_link_status=compile_link_status,
            limitations=tuple(limitations), compile_status=compile_status, link_status=link_status,
            solver_fingerprint=fingerprint)

    if not request.abaqus_command:
        return result("blocked", ["Abaqus command is not configured"])
    if not _is_ascii_path(work_dir):
        return result("blocked", ["solver work directory must be ASCII-only"])

    inp_path = Path(request.inp_path).resolve()
    if any(p.exists() for p in (stdout_path, stderr_path, *(work_dir / n for n in expected_artifacts(request.job_name, request.stage)))):
        return result("blocked", ["solver stage artifacts already exist; choose a new directory"])
    if request.input_bundle_root is not None:
        try:
            staged_inp, bundle_receipt, staged_user, inputs = _prepare_native(request)
            inputs = (*inputs, bundle_receipt)
            request = replace(request, user_subroutine=staged_user)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return result("blocked", [f"native bundle integrity/staging: {exc}"])
    else:
        staged_inp = work_dir / inp_path.name
        work_dir.mkdir(parents=True, exist_ok=True)
        if inp_path != staged_inp.resolve():
            if staged_inp.exists():
                return result("blocked", [f"staged input already exists: {staged_inp}"])
            shutil.copy2(inp_path, staged_inp)
    try:
        command = _command(request, staged_inp)
    except ValueError as exc:
        return result("blocked", [str(exc)], artifacts=inputs)

    fingerprint = capture_solver_fingerprint(
        request.abaqus_command, cwd=work_dir, version_probe_args=request.version_probe_args,
    )
    try:
        completed = _execute_process(
            command,
            cwd=work_dir,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=request.timeout_seconds,
            check=False,
        )
    except FileNotFoundError as exc:
        return result("blocked", [f"solver command is unavailable: {exc}"], artifacts=inputs)
    except subprocess.TimeoutExpired as exc:
        stdout_path.write_text(_output_text(exc.stdout), encoding="utf-8")
        stderr_path.write_text(_output_text(exc.stderr), encoding="utf-8")
        return result("failed", [f"solver timeout after {request.timeout_seconds} seconds"], artifacts=inputs)

    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    expected = tuple(work_dir / name for name in expected_artifacts(
        request.job_name,
        request.stage,
    ))
    artifacts = tuple(path for path in expected if path.is_file())
    limitations: list[str] = []
    missing = [path.name for path in expected if not path.is_file()]
    if missing:
        limitations.append(f"expected artifact is missing: {', '.join(missing)}")
    if completed.returncode != 0:
        limitations.append(f"solver process returned {completed.returncode}")
    evidence = completed.stdout + "\n" + completed.stderr
    for path in artifacts:
        if path.suffix in {".dat", ".msg", ".sta"}:
            evidence += "\n" + path.read_text(encoding="utf-8", errors="replace")
    if re.search(r"(?im)^\s*\*{2,3}\s*ERROR\b|ABAQUS ERROR:|ERROR IN INPUT FILE", evidence):
        limitations.append("solver diagnostic files report an error")
    if request.stage is SolverStage.DATACHECK:
        dat = work_dir / f"{request.job_name}.dat"
        if not dat.is_file() or "DATACHECK COMPLETE" not in dat.read_text(encoding="utf-8", errors="replace").upper():
            limitations.append("DAT does not confirm datacheck completion")

    if request.user_subroutine is not None:
        compile_status, link_status = _compiler_evidence(
            completed.stdout + "\n" + completed.stderr
        )
        if compile_status == link_status == "completed":
            compile_link_status = "completed"
        else:
            compile_link_status = (
                "failed" if "failed" in (compile_status, link_status)
                else "missing_evidence"
            )
            limitations.append(
                f"Fortran compile/link not confirmed: compile={compile_status}, link={link_status}"
            )

    if request.stage is SolverStage.ANALYSIS:
        sta_path = work_dir / f"{request.job_name}.sta"
        if sta_path.is_file():
            sta = sta_path.read_text(encoding="utf-8", errors="replace").upper()
            if "ABORTED" in sta or "COMPLETED SUCCESSFULLY" not in sta:
                limitations.append("STA does not confirm successful analysis completion")

    status = "completed" if not limitations else "failed"
    if re.search(r"(?im)^.*(?:license|licensing).*(?:failed|denied|unavailable|not available|cannot|unable).*$", evidence):
        status = "blocked"
        limitations.append("Abaqus license is unavailable")
    return result(status, limitations, completed.returncode, (*artifacts, *inputs))
