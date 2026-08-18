from __future__ import annotations

import json
from pathlib import Path

from eu4_assistant.bridge import BridgeClient, BridgeStatus


def test_bridge_injects_only_configured_game_executable(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "launcher-settings.json").write_text(
        json.dumps({"version": "EU4 v1.37.5.0 Inca (491d)"}), encoding="utf-8"
    )
    (tmp_path / "eu4.exe").write_bytes(b"not used by this unit test")
    client = BridgeClient(tmp_path)
    disconnected = BridgeStatus(client.version, False, message="not connected")
    connected = BridgeStatus(client.version, True, game_loaded=True, synchronized=True)
    statuses = iter([disconnected, connected])
    monkeypatch.setattr(client, "connect", lambda: next(statuses))

    captured: dict[str, object] = {}

    def fake_find_process_id(*, expected_path):
        captured["expected_path"] = expected_path
        return 1234

    monkeypatch.setattr("eu4_assistant.bridge.find_process_id", fake_find_process_id)
    monkeypatch.setattr(
        "eu4_assistant.bridge.inject_bridge",
        lambda pid: captured.setdefault("pid", pid),
    )
    monkeypatch.setattr("eu4_assistant.bridge.time.sleep", lambda _seconds: None)

    result = client.ensure_injected()
    assert result.connected
    assert captured == {"expected_path": tmp_path / "eu4.exe", "pid": 1234}


def test_unsupported_version_can_only_inject_after_explicit_override(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "launcher-settings.json").write_text(
        json.dumps({"version": "EU4 v1.99.0.0 Test (ffff)"}), encoding="utf-8"
    )
    (tmp_path / "eu4.exe").write_bytes(b"not used by this unit test")
    blocked = BridgeClient(tmp_path)
    assert not blocked.version_allowed

    client = BridgeClient(tmp_path, allow_unsupported_version=True)
    assert client.version_allowed
    disconnected = BridgeStatus(client.version, False, message="not connected")
    connected = BridgeStatus(client.version, True, game_loaded=True, synchronized=True)
    statuses = iter([disconnected, connected])
    monkeypatch.setattr(client, "connect", lambda: next(statuses))
    monkeypatch.setattr(
        "eu4_assistant.bridge.find_process_id",
        lambda *, expected_path: 4321 if expected_path == tmp_path / "eu4.exe" else None,
    )
    captured: list[int] = []
    monkeypatch.setattr("eu4_assistant.bridge.inject_bridge", captured.append)
    monkeypatch.setattr("eu4_assistant.bridge.time.sleep", lambda _seconds: None)

    assert client.ensure_injected().connected
    assert captured == [4321]
    handshake = client._status_from_response(
        {
            "ok": True,
            "payload": {
                "build_id": "491d",
                "game_loaded": True,
                "synchronized": True,
            },
        }
    )
    assert handshake.connected
