"""Local worker identity and owned process lifecycle without a shell or psutil.

Callers must supply identities obtained from their trusted attempt store. These
primitives are not an authorization boundary against the same OS user. Windows
workers enter an owned Job Object before their first instruction; the child owns
its job handle, so closing a CLI does not cancel work. Linux uses a new session
and checks /proc identity; deliberately escaping that session is unsupported.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import signal
import socket
import subprocess
import time


_STOP_TIMEOUT = 5.0
_THREAD_VARIABLES = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                     "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "BLIS_NUM_THREADS")
_CURRENT_JOB_HANDLES: dict[int, int] = {}


def _windows():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = wintypes.HANDLE
    dword = wintypes.DWORD
    signatures = {
        "OpenProcess": ([dword, wintypes.BOOL, dword], handle),
        "CloseHandle": ([handle], wintypes.BOOL),
        "GetCurrentProcess": ([], handle),
        "GetProcessTimes": ([handle, *([ctypes.POINTER(wintypes.FILETIME)] * 4)], wintypes.BOOL),
        "WaitForSingleObject": ([handle, dword], dword),
        "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], handle),
        "OpenJobObjectW": ([dword, wintypes.BOOL, wintypes.LPCWSTR], handle),
        "AssignProcessToJobObject": ([handle, handle], wintypes.BOOL),
        "SetInformationJobObject": ([handle, ctypes.c_int, ctypes.c_void_p, dword], wintypes.BOOL),
        "QueryInformationJobObject": ([handle, ctypes.c_int, ctypes.c_void_p, dword, ctypes.c_void_p], wintypes.BOOL),
        "IsProcessInJob": ([handle, handle, ctypes.POINTER(wintypes.BOOL)], wintypes.BOOL),
        "TerminateJobObject": ([handle, wintypes.UINT], wintypes.BOOL),
        "DuplicateHandle": ([handle, handle, handle, ctypes.POINTER(handle), dword, wintypes.BOOL, dword], wintypes.BOOL),
        "CreateToolhelp32Snapshot": ([dword, dword], handle),
        "Thread32First": ([handle, ctypes.c_void_p], wintypes.BOOL),
        "Thread32Next": ([handle, ctypes.c_void_p], wintypes.BOOL),
        "OpenThread": ([dword, wintypes.BOOL, dword], handle),
        "ResumeThread": ([handle], dword),
        "GetProcessAffinityMask": ([handle, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)], wintypes.BOOL),
        "SetProcessAffinityMask": ([handle, ctypes.c_size_t], wintypes.BOOL),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = arguments, result
    return kernel


def _checked(value):
    if not value:
        raise ctypes.WinError(ctypes.get_last_error())
    return value


def _win_identity(pid: int) -> dict:
    kernel = _windows()
    process = kernel.OpenProcess(0x1000 | 0x100000, False, pid)
    if not process:
        error = ctypes.get_last_error()
        if error == 87:
            raise ProcessLookupError(pid)
        raise ctypes.WinError(error)
    try:
        if kernel.WaitForSingleObject(process, 0) == 0:
            raise ProcessLookupError(pid)
        created, exited, system, user = (wintypes.FILETIME() for _ in range(4))
        _checked(kernel.GetProcessTimes(process, ctypes.byref(created), ctypes.byref(exited),
                                        ctypes.byref(system), ctypes.byref(user)))
        start = (created.dwHighDateTime << 32) | created.dwLowDateTime
        return {"pid": pid, "started": f"windows:{start}", "host": socket.gethostname()}
    finally:
        kernel.CloseHandle(process)


def _linux_stat(pid: int):
    try:
        content = Path(f"/proc/{pid}/stat").read_text()
    except FileNotFoundError as exc:
        raise ProcessLookupError(pid) from exc
    # comm may itself contain spaces or parentheses; fields start after its last ).
    fields = content[content.rfind(")") + 2:].split()
    if fields[0] in {"Z", "X"}:
        raise ProcessLookupError(pid)
    return fields


def process_identity(pid: int) -> dict:
    """Return an OS instance identity, never just a potentially reused PID."""
    if type(pid) is not int or pid <= 0:
        raise ProcessLookupError(pid)
    if os.name == "nt":
        return _win_identity(pid)
    if not Path("/proc/sys/kernel/random/boot_id").is_file():
        raise NotImplementedError("local identity requires Windows or Linux /proc")
    fields = _linux_stat(pid)
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    return {"pid": pid, "started": f"linux:{boot}:{fields[19]}", "host": socket.gethostname()}


def _valid_identity(identity) -> bool:
    return (isinstance(identity, dict) and type(identity.get("pid")) is int
            and identity["pid"] > 0 and isinstance(identity.get("started"), str)
            and bool(identity["started"]) and identity.get("host") == socket.gethostname())


def probe_process(identity: dict) -> str:
    """An unreachable host or unreadable identity is unknown, not an exit."""
    if not _valid_identity(identity):
        return "unknown"
    try:
        current = process_identity(identity["pid"])
    except ProcessLookupError:
        return "stopped"
    except (OSError, ValueError, NotImplementedError):
        return "unknown"
    return "running" if current["started"] == identity["started"] else "stopped"


def _job_name(identity: dict) -> str:
    digest = hashlib.sha256(f'{identity["host"]}:{identity["pid"]}:{identity["started"]}'.encode()).hexdigest()
    return "Local\\experiment-to-cpfe-worker-" + digest


class _JobLimits(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD)]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in
                ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                 "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _ExtendedJobLimits(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _JobLimits), ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


class _ThreadEntry(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ThreadID", wintypes.DWORD), ("th32OwnerProcessID", wintypes.DWORD),
                ("tpBasePri", wintypes.LONG), ("tpDeltaPri", wintypes.LONG), ("dwFlags", wintypes.DWORD)]


class _JobAccounting(ctypes.Structure):
    _fields_ = [("TotalUserTime", ctypes.c_int64), ("TotalKernelTime", ctypes.c_int64),
                ("ThisPeriodTotalUserTime", ctypes.c_int64), ("ThisPeriodTotalKernelTime", ctypes.c_int64),
                ("TotalPageFaultCount", wintypes.DWORD), ("TotalProcesses", wintypes.DWORD),
                ("ActiveProcesses", wintypes.DWORD), ("TotalTerminatedProcesses", wintypes.DWORD)]


def _resume_suspended(kernel, pid):
    snapshot = kernel.CreateToolhelp32Snapshot(0x4, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = _ThreadEntry()
        entry.dwSize = ctypes.sizeof(entry)
        present = kernel.Thread32First(snapshot, ctypes.byref(entry))
        threads = []
        while present:
            if entry.th32OwnerProcessID == pid:
                threads.append(entry.th32ThreadID)
            present = kernel.Thread32Next(snapshot, ctypes.byref(entry))
        if len(threads) != 1:
            raise RuntimeError("suspended worker must have exactly one initial thread")
        thread = _checked(kernel.OpenThread(0x2, False, threads[0]))
        try:
            if kernel.ResumeThread(thread) == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            kernel.CloseHandle(thread)
    finally:
        kernel.CloseHandle(snapshot)


def _attach_and_resume(process):
    kernel = _windows()
    identity = process_identity(process.pid)
    job = _checked(kernel.CreateJobObjectW(None, _job_name(identity)))
    try:
        if ctypes.get_last_error() == 183:
            raise RuntimeError("worker job identity already exists")
        limits = _ExtendedJobLimits()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        _checked(kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
        _checked(kernel.AssignProcessToJobObject(job, int(process._handle)))
        remote_handle = wintypes.HANDLE()
        # The child keeps the job alive after the creating CLI exits. It is closed
        # by the OS when the worker exits, terminating any remaining descendants.
        _checked(kernel.DuplicateHandle(kernel.GetCurrentProcess(), job, int(process._handle),
                                        ctypes.byref(remote_handle), 0, False, 2))
        _resume_suspended(kernel, process.pid)
    finally:
        kernel.CloseHandle(job)


def _claim_current_windows_job():
    """Give a redirector's actual interpreter its own durable cancellation ID."""
    pid = os.getpid()
    if pid in _CURRENT_JOB_HANDLES:
        return
    kernel = _windows()
    job = _checked(kernel.CreateJobObjectW(None, _job_name(process_identity(pid))))
    existed = ctypes.get_last_error() == 183
    try:
        current = kernel.GetCurrentProcess()
        if existed:
            belongs = wintypes.BOOL()
            _checked(kernel.IsProcessInJob(current, job, ctypes.byref(belongs)))
            if not belongs.value:
                raise RuntimeError("current worker job identity is already owned elsewhere")
        else:
            limits = _ExtendedJobLimits()
            limits.BasicLimitInformation.LimitFlags = 0x2000
            _checked(kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
            _checked(kernel.AssignProcessToJobObject(job, current))
    except BaseException:
        kernel.CloseHandle(job)
        raise
    # Intentionally live until OS process teardown; this is also the parent-death
    # containment handle for children of the interpreter behind a venv redirector.
    _CURRENT_JOB_HANDLES[pid] = job


def spawn_worker(argv: list[str], cwd: Path, stdout: Path, stderr: Path,
                 env: dict[str, str]) -> subprocess.Popen:
    """Start a registered worker asynchronously, keeping existing logs intact.

    The service supplies fixed argv and sanitized environment. On Windows a
    suspended process joins its job before it can execute or spawn a child.
    """
    if not isinstance(argv, list) or not argv or any(not isinstance(arg, str) or "\0" in arg for arg in argv):
        raise ValueError("worker argv must be a nonempty list of literal strings")
    cwd, stdout, stderr = Path(cwd).resolve(), Path(stdout).resolve(), Path(stderr).resolve()
    if not cwd.is_dir():
        raise NotADirectoryError(cwd)
    options = ({"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP | 0x4}
               if os.name == "nt" else {"start_new_session": True})
    with stdout.open("xb") as output, stderr.open("xb") as error:
        process = subprocess.Popen(argv, cwd=cwd, stdout=output, stderr=error,
                                   stdin=subprocess.DEVNULL, env=env, shell=False, close_fds=True, **options)
    if os.name == "nt":
        try:
            _attach_and_resume(process)
        except BaseException:
            # A failed attachment leaves a suspended child; only that Popen's
            # OS handle is terminated, never a process guessed from a PID.
            process.kill()
            process.wait(timeout=_STOP_TIMEOUT)
            raise
    return process


def _stop_windows(identity: dict) -> bool:
    kernel = _windows()
    job = kernel.OpenJobObjectW(0x4 | 0x8, False, _job_name(identity))
    if not job:
        return False
    handles = []
    try:
        # Recheck the same instance immediately before using its owned job.
        if probe_process(identity) != "running":
            return False
        process = kernel.OpenProcess(0x1000, False, identity["pid"])
        if not process:
            return False
        try:
            belongs = wintypes.BOOL()
            _checked(kernel.IsProcessInJob(process, job, ctypes.byref(belongs)))
            if not belongs.value:
                return False
        finally:
            kernel.CloseHandle(process)
        # Job accounting can drop a terminating process before its kernel object
        # is signaled. Keep stable handles to the observed members and wait for
        # those as well, rather than treating ActiveProcesses=0 as confirmation.
        capacity = 16
        while True:
            class Members(ctypes.Structure):
                _fields_ = [("assigned", wintypes.DWORD), ("count", wintypes.DWORD),
                            ("pids", ctypes.c_size_t * capacity)]
            members = Members()
            if kernel.QueryInformationJobObject(job, 3, ctypes.byref(members), ctypes.sizeof(members), None):
                break
            if ctypes.get_last_error() != 234 or capacity >= 65536:
                raise ctypes.WinError(ctypes.get_last_error())
            capacity *= 2
        for pid in members.pids[:members.count]:
            handle = kernel.OpenProcess(0x100000, False, pid)
            if handle:
                handles.append(handle)
            elif ctypes.get_last_error() != 87:
                return False
        _checked(kernel.TerminateJobObject(job, 1))
        deadline = time.monotonic() + _STOP_TIMEOUT
        while time.monotonic() < deadline:
            accounting = _JobAccounting()
            _checked(kernel.QueryInformationJobObject(job, 1, ctypes.byref(accounting),
                                                     ctypes.sizeof(accounting), None))
            if accounting.ActiveProcesses == 0 and all(kernel.WaitForSingleObject(handle, 0) == 0 for handle in handles):
                return True
            time.sleep(.02)
        return False
    finally:
        for handle in handles:
            kernel.CloseHandle(handle)
        kernel.CloseHandle(job)


def _stop_linux(identity: dict) -> bool:
    pid = identity["pid"]
    # A worker must be its own session/process-group leader. Do not signal an
    # arbitrary process's inherited group (which could contain the calling UI).
    if os.getsid(pid) != pid or os.getpgid(pid) != pid or probe_process(identity) != "running":
        return False
    os.killpg(pid, signal.SIGKILL)
    deadline = time.monotonic() + _STOP_TIMEOUT
    while time.monotonic() < deadline:
        live = False
        for path in Path("/proc").iterdir():
            if path.name.isdecimal():
                try:
                    fields = _linux_stat(int(path.name))
                    if int(fields[2]) == pid:
                        live = True
                        break
                except ProcessLookupError:
                    continue
        if not live:
            return True
        time.sleep(.02)
    return False


def stop_process(identity: dict) -> bool:
    """Stop a verified owned worker tree; uncertainty is never reported stopped."""
    if not _valid_identity(identity) or probe_process(identity) != "running":
        return False
    if identity["pid"] == os.getpid():
        return False
    try:
        return _stop_windows(identity) if os.name == "nt" else _stop_linux(identity)
    except (OSError, ValueError, NotImplementedError):
        return False


def constrain_cpu() -> dict:
    """Constrain this worker to one available CPU; return observed enforcement.

    Affinity and environment are inherited by ordinary child processes. This is
    not a quota or a security boundary against a child resetting its affinity.
    Call before importing numerical libraries; already-initialized pools may
    retain threads, although the process still has just one schedulable CPU.
    """
    for name in _THREAD_VARIABLES:
        os.environ[name] = "1"
    report = {"cpu_count": 1, "observed_cpu_count": None,
              "scope": "current_process_and_inheriting_children", "enforcement": "unavailable",
              "process_tree_enforcement": "unavailable",
              "thread_environment": {name: "1" for name in _THREAD_VARIABLES},
              "limitations": ["Affinity is not a CPU-time quota; trusted children must not reset it."]}
    try:
        if os.name == "nt":
            _claim_current_windows_job()
            report["process_tree_enforcement"] = "windows_job_object"
            kernel = _windows()
            handle = kernel.GetCurrentProcess()
            process_mask, system_mask = ctypes.c_size_t(), ctypes.c_size_t()
            _checked(kernel.GetProcessAffinityMask(handle, ctypes.byref(process_mask), ctypes.byref(system_mask)))
            if not process_mask.value:
                raise OSError("no single processor-group affinity is available")
            selected = process_mask.value & -process_mask.value
            _checked(kernel.SetProcessAffinityMask(handle, selected))
            _checked(kernel.GetProcessAffinityMask(handle, ctypes.byref(process_mask), ctypes.byref(system_mask)))
            observed = process_mask.value.bit_count()
        elif hasattr(os, "sched_setaffinity"):
            available = os.sched_getaffinity(0)
            os.sched_setaffinity(0, {min(available)})
            observed = len(os.sched_getaffinity(0))
            report["process_tree_enforcement"] = "linux_session_requires_live_supervisor"
        else:
            raise NotImplementedError("CPU affinity is not available on this platform")
        report.update(observed_cpu_count=observed, enforcement="affinity" if observed == 1 else "unavailable")
    except (OSError, ValueError, NotImplementedError) as exc:
        report["limitations"].append(f"CPU affinity not confirmed: {type(exc).__name__}")
    return report
