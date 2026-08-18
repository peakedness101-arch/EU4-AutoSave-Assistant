from __future__ import annotations

import argparse
import ctypes
import json
import time
from pathlib import Path

from eu4_assistant.bridge import PIPE_NAME, _NamedPipeTransport


def wait_for_file(path: Path, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file() and path.stat().st_size:
            return
        time.sleep(0.05)
    raise TimeoutError(f"timed out waiting for {path}")


def close_process_window(pid: int) -> None:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    @callback_type
    def callback(window, _parameter):
        window_pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(window, ctypes.byref(window_pid))
        if window_pid.value == pid:
            user32.PostMessageW(window, 0x0010, 0, 0)  # WM_CLOSE
            return False
        return True

    user32.EnumWindows(callback, 0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ready", type=Path)
    parser.add_argument("result", type=Path)
    args = parser.parse_args()
    wait_for_file(args.ready)
    ready = json.loads(args.ready.read_text(encoding="utf-8"))

    deadline = time.monotonic() + 10.0
    while True:
        try:
            transport = _NamedPipeTransport(PIPE_NAME)
            break
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)
    try:
        hello = transport.request({"protocol": 1, "command": "hello", "payload": {}})
        assert hello["ok"] is True, hello
        assert hello["payload"]["build_id"] == "491d", hello
        assert hello["payload"]["game_loaded"] is True, hello
        assert hello["payload"]["synchronized"] is True, hello
        assert hello["payload"]["game_date"] == "1767.7.27", hello

        response = transport.request(
            {"protocol": 1, "command": "request_save", "payload": {}}
        )
        assert response["ok"] is True, response
        assert response["message"] == (
            "native save request returned; awaiting filesystem verification"
        ), response
    finally:
        transport.close()

    wait_for_file(args.result)
    result = json.loads(args.result.read_text(encoding="utf-8"))
    assert result["main_thread_id"] == ready["main_thread_id"]
    assert result["callback_thread_id"] == ready["main_thread_id"]
    assert result["automatic"] is True
    assert result["kind"] == 0
    print(json.dumps({"hello": hello, "response": response, "callback": result}, indent=2))
    close_process_window(int(ready["pid"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
