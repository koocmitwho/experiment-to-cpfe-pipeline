"""Resolve a configured solver launcher and optionally query its version."""

from collections.abc import Sequence
import os
from pathlib import Path
import shutil
import subprocess

from experiment_to_cpfe.provenance.hashing import sha256_file


VERSION_PROBE_TIMEOUT_SECONDS = 3


def _resolve_command_file(program: str, cwd: Path) -> Path | None:
    path = Path(program)
    if path.is_absolute() or os.path.dirname(program):
        candidate = path if path.is_absolute() else cwd / path
        return candidate.absolute() if candidate.is_file() else None
    directories = [cwd] if os.name == "nt" else []
    directories.extend(Path(entry) if Path(entry).is_absolute() else cwd / entry
                       for entry in os.get_exec_path())
    for directory in directories:
        resolved = shutil.which(str(directory / program))
        if resolved is not None:
            return Path(resolved).absolute()
    return None


def capture_solver_fingerprint(
    command: Sequence[str],
    *,
    cwd: Path,
    version_probe_args: Sequence[str] = (),
) -> dict[str, object]:
    """Snapshot the command file; version probing is explicitly configured.

    Relative executables/PATH entries resolve against the invocation directory.
    A batch-launcher digest describes that file's bytes. Resolution, hashing
    and probe failures are diagnostics, leaving the surrounding stage's status
    to its own execution/data checks. The probe has a three-second execution
    timeout and reuses the runner's owned-process cleanup.
    """
    argv = list(command)
    args = list(version_probe_args)
    directory = Path(cwd).resolve()
    probe: dict[str, object] = {
        "args": args, "command": None,
        "timeout_seconds": VERSION_PROBE_TIMEOUT_SECONDS,
        "status": "not_configured" if not args else "unavailable",
        "return_code": None, "reason": None,
    }
    record: dict[str, object] = {
        "command": argv, "resolution_cwd": str(directory),
        "executable_path": None, "executable_sha256": None,
        "command_file_kind": None, "resolution_error": None,
        "hash_error": None, "version": None, "probe": probe,
    }
    if not argv:
        record["resolution_error"] = "command_not_configured"
        probe["reason"] = "command_not_configured"
        return record
    try:
        executable = _resolve_command_file(argv[0], directory)
        if executable is not None:
            record["executable_path"] = str(executable.resolve())
    except (OSError, ValueError) as exc:
        record["resolution_error"] = f"{type(exc).__name__}: {exc}"
        probe["reason"] = "command_resolution_failed"
        return record
    if executable is None:
        record["resolution_error"] = "command_not_found"
        probe["reason"] = "command_not_found"
        return record
    batch = executable.suffix.lower() in {".bat", ".cmd"}
    record["command_file_kind"] = "batch_launcher" if batch else "executable"
    try:
        record["executable_sha256"] = sha256_file(executable)
    except (OSError, ValueError) as exc:
        record["hash_error"] = f"{type(exc).__name__}: {exc}"
    if not args:
        return record
    if batch and os.name != "nt":
        probe.update(status="unsupported", reason="batch_probe_requires_windows")
        return record

    # Resolve lazily: the runner also records fingerprints at its process boundary.
    from experiment_to_cpfe.solvers.abaqus.runner import _execute_process, _output_text, wrap_batch_command

    try:
        # Execute the selected launcher path: resolving a virtual-environment
        # symlink before launch changes the environment selected by Python.
        invocation = wrap_batch_command((str(executable), *argv[1:], *args))
        probe["command"] = list(invocation)
        completed = _execute_process(invocation, cwd=directory,
                                     timeout=VERSION_PROBE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        probe.update(status="timeout", reason="version_probe_timeout")
        return record
    except (OSError, ValueError) as exc:
        probe.update(status="failed", reason=f"{type(exc).__name__}: {exc}")
        return record
    probe["return_code"] = completed.returncode
    if completed.returncode:
        probe.update(status="failed", reason=f"version_probe_exit_code_{completed.returncode}")
        return record
    version_text = _output_text(completed.stdout).strip() or _output_text(completed.stderr).strip()
    if not version_text:
        probe.update(status="empty", reason="empty_version_output")
        return record
    record["version"] = version_text
    probe["status"] = "completed"
    return record
