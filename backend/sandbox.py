"""Local process sandbox used by agent tools.

This is deliberately a defense-in-depth sandbox.  On Windows it places child
processes in a Job Object with memory/process/time limits.  It is not a VM and
cannot be treated as a hostile-code security boundary.
"""
from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

MAX_OUTPUT = 12_000
DEFAULT_TIMEOUT = 20
MAX_MEMORY_BYTES = 512 * 1024 * 1024


@dataclass
class Result:
    returncode: int
    stdout: str
    stderr: str


def _trim(value: str) -> str:
    value = value or ""
    return value[-MAX_OUTPUT:]


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION = 9
    JobObjectExtendedLimitInformation = 9
    JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x100
    JOB_OBJECT_LIMIT_PROCESS_TIME = 0x2
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class LARGE_INTEGER(ctypes.Structure):
        _fields_ = [("QuadPart", ctypes.c_longlong)]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", LARGE_INTEGER),
            ("PerJobUserTimeLimit", LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION_STRUCT(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, wintypes.INT, wintypes.LPVOID, wintypes.DWORD]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    def _job_for_process(proc: subprocess.Popen):
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION_STRUCT()
        info.BasicLimitInformation.LimitFlags = (
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_PROCESS_MEMORY
        )
        info.ProcessMemoryLimit = MAX_MEMORY_BYTES
        ok = kernel32.SetInformationJobObject(
            job, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)
        )
        if not ok or not kernel32.AssignProcessToJobObject(job, wintypes.HANDLE(proc._handle)):
            kernel32.CloseHandle(job)
            return None
        return job
else:
    def _job_for_process(proc):
        return None


def run_isolated(
    args: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: int = DEFAULT_TIMEOUT,
) -> Result:
    kwargs = dict(
        cwd=str(cwd), env=dict(env), stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        shell=False,
    )
    if os.name != "nt":
        def limits():
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (MAX_MEMORY_BYTES, MAX_MEMORY_BYTES))
            resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
        kwargs["preexec_fn"] = limits
    else:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    proc = subprocess.Popen(list(args), **kwargs)
    job = _job_for_process(proc)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return Result(proc.returncode, _trim(stdout), _trim(stderr))
    except subprocess.TimeoutExpired:
        try:
            if os.name == "nt" and job:
                kernel32.TerminateJobObject(job, 124)
            else:
                proc.kill()
        except Exception:
            proc.kill()
        stdout, stderr = proc.communicate()
        return Result(124, _trim(stdout), _trim(stderr or "Execution timed out."))
    finally:
        if job:
            kernel32.CloseHandle(job)
