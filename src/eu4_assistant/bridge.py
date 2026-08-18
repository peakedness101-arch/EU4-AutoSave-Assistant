from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

from .versioning import VersionStatus, detect_game_version
from .injection import find_process_id, inject_bridge
from .savefiles import is_managed_autosave


PIPE_NAME = r"\\.\pipe\EU4AutoSave491d"
PROTOCOL_VERSION = 1


@dataclass(slots=True)
class BridgeStatus:
    version: VersionStatus
    connected: bool
    game_loaded: bool = False
    synchronized: bool = False
    saving: bool = False
    game_date: str | None = None
    message: str = ""


class BridgeClient:
    def __init__(
        self,
        game_dir: str | Path,
        *,
        allow_unsupported_version: bool = False,
    ):
        self.game_dir = Path(game_dir)
        self.version = detect_game_version(self.game_dir)
        self.allow_unsupported_version = allow_unsupported_version
        self._connection = None
        self._lock = threading.RLock()

    @property
    def version_allowed(self) -> bool:
        return self.version.supported or self.allow_unsupported_version

    def connect(self) -> BridgeStatus:
        with self._lock:
            if not self.version_allowed:
                return BridgeStatus(self.version, False, message=self.version.reason)
            try:
                if self._connection is not None:
                    self._connection.close()
                self._connection = _NamedPipeTransport(PIPE_NAME)
                response = self._request("hello", {"protocol": PROTOCOL_VERSION})
                return self._status_from_response(response)
            except (OSError, EOFError, ValueError) as exc:
                self._connection = None
                return BridgeStatus(
                    self.version,
                    False,
                    message=(
                        f"{'风险兼容模式' if self.allow_unsupported_version and not self.version.supported else '491d 已通过'}，"
                        f"但原生桥尚未连接：{exc}"
                    ),
                )

    def status(self) -> BridgeStatus:
        with self._lock:
            if self._connection is None:
                return self.connect()
            try:
                return self._status_from_response(self._request("status", {}))
            except (OSError, EOFError, ValueError) as exc:
                self._connection = None
                return BridgeStatus(self.version, False, message=f"桥接连接中断：{exc}")

    def ensure_injected(self) -> BridgeStatus:
        with self._lock:
            status = self.connect()
            if status.connected or not self.version_allowed:
                return status
            pid = find_process_id(expected_path=self.game_dir / "eu4.exe")
            if pid is None:
                return BridgeStatus(self.version, False, message="未发现正在运行的 eu4.exe。")
            try:
                inject_bridge(pid)
            except Exception as exc:
                return BridgeStatus(self.version, False, message=f"原生桥加载失败：{exc}")
            for _ in range(100):
                time.sleep(0.1)
                status = self.connect()
                if status.connected:
                    return status
            return BridgeStatus(self.version, False, message="DLL 已加载，但命名管道没有就绪。")

    def request_save(self) -> dict[str, Any]:
        with self._lock:
            if not self.version_allowed:
                raise RuntimeError(self.version.reason)
            if self._connection is None:
                status = self.connect()
                if not status.connected:
                    raise RuntimeError(status.message)
            return self._request("request_save", {})

    def request_save_and_wait(
        self,
        save_dir: str | Path,
        *,
        timeout: float = 120.0,
        poll_interval: float = 0.25,
        stable_checks: int = 3,
    ) -> dict[str, Any]:
        """Request a native save and only succeed after a parseable file lands."""
        from .parser import parse_save

        directory = Path(save_dir)
        before = _save_snapshot(directory)
        response = self.request_save()
        dispatch_ok = bool(response.get("ok"))
        if not dispatch_ok:
            response["dispatch_ok"] = False
            response["file_created"] = False
            return response

        deadline = time.monotonic() + timeout
        observed: dict[Path, tuple[tuple[int, int], int]] = {}
        last_parse_error: str | None = None
        while time.monotonic() < deadline:
            current = _save_snapshot(directory)
            changed = {
                path: signature
                for path, signature in current.items()
                if before.get(path) != signature and is_managed_autosave(path)
            }
            for path in list(observed):
                if path not in changed:
                    observed.pop(path, None)
            for path, signature in sorted(
                changed.items(), key=lambda item: item[1][0], reverse=True
            ):
                previous_signature, count = observed.get(path, (signature, 0))
                count = count + 1 if previous_signature == signature else 1
                observed[path] = (signature, count)
                if count < stable_checks:
                    continue
                try:
                    record = parse_save(path)
                except (OSError, ValueError) as exc:
                    last_parse_error = str(exc)
                    continue
                return {
                    **response,
                    "ok": True,
                    "dispatch_ok": True,
                    "file_created": True,
                    "save_path": str(path),
                    "save_date": record.game_date,
                    "message": f"存档已落盘并通过解析：{path.name}",
                }
            time.sleep(poll_interval)

        detail = f"；最后解析错误：{last_parse_error}" if last_parse_error else ""
        return {
            **response,
            "ok": False,
            "dispatch_ok": True,
            "file_created": False,
            "message": f"游戏已返回保存请求，但 {timeout:g} 秒内没有检测到可解析的新存档{detail}",
        }

    def cancel(self) -> dict[str, Any]:
        with self._lock:
            if self._connection is None:
                return {"ok": False, "message": "桥接未连接"}
            return self._request("cancel", {})

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def _request(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self._connection is None:
            raise RuntimeError("桥接未连接。")
        request = {"protocol": PROTOCOL_VERSION, "command": command, "payload": payload}
        return self._connection.request(request)

    def _status_from_response(self, response: dict[str, Any]) -> BridgeStatus:
        payload = response.get("payload") or response
        bridge_build = str(payload.get("build_id") or "")
        if (
            bridge_build
            and bridge_build != self.version.detected_build_id
            and not self.allow_unsupported_version
        ):
            return BridgeStatus(
                version=self.version,
                connected=False,
                message=f"原生桥目标为 {bridge_build}，当前游戏为 {self.version.detected_build_id}。",
            )
        return BridgeStatus(
            version=self.version,
            connected=bool(response.get("ok")),
            game_loaded=bool(payload.get("game_loaded")),
            synchronized=bool(payload.get("synchronized")),
            saving=bool(payload.get("saving")),
            game_date=payload.get("game_date"),
            message=str(response.get("message") or ""),
        )


class _NamedPipeTransport:
    """Small Win32 message-pipe transport shared with the native bridge."""

    def __init__(self, name: str):
        if os.name != "nt":
            raise OSError("原生桥仅支持 Windows。")
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
        self._kernel32.WaitNamedPipeW.restype = wintypes.BOOL
        self._kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        self._kernel32.CreateFileW.restype = wintypes.HANDLE
        self._kernel32.WriteFile.argtypes = [
            wintypes.HANDLE,
            wintypes.LPCVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        ]
        self._kernel32.ReadFile.argtypes = [
            wintypes.HANDLE,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        ]
        if not self._kernel32.WaitNamedPipeW(name, 1500):
            raise OSError(ctypes.get_last_error(), "原生桥命名管道不可用")
        handle = self._kernel32.CreateFileW(
            name,
            0xC0000000,
            0,
            None,
            3,
            0,
            None,
        )
        invalid = wintypes.HANDLE(-1).value
        if handle == invalid:
            raise OSError(ctypes.get_last_error(), "无法连接原生桥")
        self.handle = handle

    def request(self, request: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(request, ensure_ascii=False).encode("utf-8")
        written = wintypes.DWORD()
        buffer = ctypes.create_string_buffer(payload)
        if not self._kernel32.WriteFile(
            self.handle, buffer, len(payload), ctypes.byref(written), None
        ):
            raise OSError(ctypes.get_last_error(), "向原生桥写入失败")
        response = ctypes.create_string_buffer(65536)
        received = wintypes.DWORD()
        if not self._kernel32.ReadFile(
            self.handle, response, len(response), ctypes.byref(received), None
        ):
            raise OSError(ctypes.get_last_error(), "从原生桥读取失败")
        return json.loads(response.raw[: received.value].decode("utf-8"))

    def close(self) -> None:
        if getattr(self, "handle", None):
            self._kernel32.CloseHandle(self.handle)
            self.handle = None


def _save_snapshot(directory: Path) -> dict[Path, tuple[int, int]]:
    if not directory.is_dir():
        return {}
    snapshot: dict[Path, tuple[int, int]] = {}
    for path in directory.glob("*.eu4"):
        try:
            stat = path.stat()
        except OSError:
            continue
        snapshot[path] = (stat.st_mtime_ns, stat.st_size)
    return snapshot
