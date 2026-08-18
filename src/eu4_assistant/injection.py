from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .config import PROJECT_ROOT

if os.name == "nt":
    import ctypes
    from ctypes import wintypes


def find_process_id(
    executable_name: str = "eu4.exe",
    *,
    expected_path: str | Path | None = None,
) -> int | None:
    if os.name != "nt":
        return None

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    expected = (
        os.path.normcase(os.path.abspath(str(expected_path)))
        if expected_path is not None
        else None
    )

    def process_path(pid: int) -> str | None:
        process = kernel32.OpenProcess(0x1000, False, pid)
        if not process:
            return None
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            length = wintypes.DWORD(len(buffer))
            if not kernel32.QueryFullProcessImageNameW(
                process, 0, buffer, ctypes.byref(length)
            ):
                return None
            return buffer.value[: length.value]
        finally:
            kernel32.CloseHandle(process)

    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    invalid = wintypes.HANDLE(-1).value
    if snapshot == invalid:
        return None
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(entry)
    try:
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return None
        while True:
            if entry.szExeFile.lower() == executable_name.lower():
                pid = int(entry.th32ProcessID)
                if expected is None:
                    return pid
                actual = process_path(pid)
                if actual is not None and os.path.normcase(os.path.abspath(actual)) == expected:
                    return pid
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                return None
    finally:
        kernel32.CloseHandle(snapshot)


def native_binary_dir() -> Path:
    release_native = PROJECT_ROOT / "native"
    if (release_native / "EU4BridgeInjector.exe").is_file():
        return release_native
    return PROJECT_ROOT / "build" / "native"


def inject_bridge(pid: int) -> str:
    root = native_binary_dir()
    injector = root / "EU4BridgeInjector.exe"
    bridge = root / "EU4AutoSaveBridge.dll"
    if not injector.is_file() or not bridge.is_file():
        raise FileNotFoundError("原生桥或注入器尚未构建。")
    completed = subprocess.run(
        [str(injector), str(pid), str(bridge)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        check=False,
        creationflags=0x08000000 if os.name == "nt" else 0,
    )
    if completed.returncode:
        raise RuntimeError((completed.stderr or completed.stdout).strip())
    return completed.stdout.strip()
