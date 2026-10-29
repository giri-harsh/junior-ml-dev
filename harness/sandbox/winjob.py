"""Windows Job Object limits for the subprocess sandbox (best effort, NOT isolation).

Limits: per-process memory, active process count (contains fork bombs), kill-on-close so the whole
tree dies with the job handle. It does NOT restrict the filesystem or the network; use the Docker
or E2B backends for that. No-ops (returns None) on non-Windows platforms.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
DEFAULT_MEMORY_BYTES = 2 * 1024**3
# venv python.exe is a launcher that starts the real interpreter: 2 = launcher + python.
DEFAULT_MAX_PROCESSES = 2


class JobHandle:
    def __init__(self, handle: Any, kernel32: Any) -> None:
        self._h, self._k = handle, kernel32

    def terminate(self) -> None:
        if self._h:
            self._k.TerminateJobObject(self._h, 1)

    def close(self) -> None:
        if self._h:
            self._k.CloseHandle(self._h)  # KILL_ON_JOB_CLOSE kills anything still running
            self._h = None


def assign(
    proc: subprocess.Popen[Any],
    memory_bytes: int = DEFAULT_MEMORY_BYTES,
    max_processes: int = DEFAULT_MAX_PROCESSES,
) -> JobHandle | None:
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class BASIC(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IOC(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ("r", "w", "o", "rb", "wb", "ob")]

    class EXT(ctypes.Structure):
        _fields_ = [
            ("Basic", BASIC),
            ("Io", IOC),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    k = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined,unused-ignore]
    k.CreateJobObjectW.restype = wintypes.HANDLE
    k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    job = k.CreateJobObjectW(None, None)
    if not job:
        return None
    info = EXT()
    info.Basic.LimitFlags = (
        JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        | JOB_OBJECT_LIMIT_PROCESS_MEMORY
        | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    )
    info.Basic.ActiveProcessLimit = max_processes
    info.ProcessMemoryLimit = memory_bytes
    ok = k.SetInformationJobObject(
        job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info)
    )
    if not ok or not k.AssignProcessToJobObject(job, int(proc._handle)):  # type: ignore[attr-defined,unused-ignore]
        k.CloseHandle(job)
        return None
    return JobHandle(job, k)
