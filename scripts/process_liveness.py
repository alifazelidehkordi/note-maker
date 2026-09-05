from __future__ import annotations

import os
from pathlib import Path


def _windows_pid_is_alive(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    still_active = 259
    error_access_denied = 5

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return ctypes.get_last_error() == error_access_denied
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _windows_process_start_identity(pid: int) -> str | None:
    """Return the Windows process creation FILETIME when it can be queried."""
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return None
    try:
        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return None
        value = (int(creation.dwHighDateTime) << 32) | int(creation.dwLowDateTime)
        return f"windows-filetime:{value}"
    finally:
        kernel32.CloseHandle(handle)


def _linux_process_start_identity(pid: int, *, proc_root: Path = Path("/proc")) -> str | None:
    """Return boot identity plus /proc start ticks for a Linux process."""
    try:
        stat_text = (proc_root / str(pid) / "stat").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    # Field 2 (comm) may contain spaces and parentheses. Everything following
    # its final ')' starts at field 3; field 22 (starttime) is therefore index
    # 19 in the remaining fields.
    closing = stat_text.rfind(")")
    if closing < 0:
        return None
    fields = stat_text[closing + 1 :].strip().split()
    if len(fields) <= 19:
        return None
    start_ticks = fields[19]
    try:
        int(start_ticks)
    except ValueError:
        return None

    boot_id = ""
    try:
        boot_id = (proc_root / "sys" / "kernel" / "random" / "boot_id").read_text(
            encoding="utf-8"
        ).strip()
    except (OSError, UnicodeDecodeError):
        pass
    return f"linux:{boot_id}:{start_ticks}" if boot_id else f"linux:{start_ticks}"


def process_start_identity(pid: int, *, platform_name: str | None = None) -> str | None:
    """Return a stable process-start identity without signaling the process.

    The identity is intentionally opaque to callers. It is used together with
    a PID so a reused PID cannot make an old ownership record appear current.
    Unsupported or inaccessible platforms return ``None`` and callers must
    treat ownership as unverifiable rather than stale.
    """
    if pid <= 0:
        return None
    platform = os.name if platform_name is None else platform_name
    if platform == "nt":
        return _windows_process_start_identity(pid)
    if platform == "posix":
        return _linux_process_start_identity(pid)
    return None


def pid_is_alive(pid: int) -> bool:
    """Return whether *pid* exists without signaling or disturbing it."""
    if pid <= 0:
        return False
    if os.name == "nt":
        return _windows_pid_is_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True
