from __future__ import annotations

import threading
import time
from pathlib import Path

from eu4_assistant.bridge import BridgeClient, _save_snapshot


MINIMAL_SAVE = b'''EU4txt\ndate=1444.11.11\nsavegame_version={\n\tfirst=1\n\tsecond=37\n\tthird=5\n\tforth=0\n}\nplayers_countries={\n\t"Alice"\n\t"ENG"\n}\nplayer="ENG"\ncountries={\n\tENG={\n\t\tname="England"\n\t\ttreasury=10\n\t}\n}\n'''


def test_save_snapshot_only_lists_eu4_files(tmp_path: Path) -> None:
    save = tmp_path / "test.eu4"
    save.write_bytes(MINIMAL_SAVE)
    (tmp_path / "ignore.txt").write_text("x", encoding="utf-8")

    assert list(_save_snapshot(tmp_path)) == [save]


def test_request_save_waits_for_parseable_file(tmp_path: Path, monkeypatch) -> None:
    client = BridgeClient(tmp_path)
    monkeypatch.setattr(client, "request_save", lambda: {"ok": True, "message": "returned"})

    def create_save() -> None:
        time.sleep(0.03)
        (tmp_path / "mp_autosave.eu4").write_bytes(MINIMAL_SAVE)

    worker = threading.Thread(target=create_save)
    worker.start()
    result = client.request_save_and_wait(
        tmp_path, timeout=1, poll_interval=0.01, stable_checks=2
    )
    worker.join()

    assert result["ok"] is True
    assert result["dispatch_ok"] is True
    assert result["file_created"] is True
    assert result["save_date"] == "1444.11.11"


def test_request_save_timeout_is_not_success(tmp_path: Path, monkeypatch) -> None:
    client = BridgeClient(tmp_path)
    monkeypatch.setattr(client, "request_save", lambda: {"ok": True, "message": "returned"})

    result = client.request_save_and_wait(
        tmp_path, timeout=0.03, poll_interval=0.01, stable_checks=2
    )

    assert result["ok"] is False
    assert result["dispatch_ok"] is True
    assert result["file_created"] is False


def test_request_save_does_not_accept_an_unrelated_manual_save(
    tmp_path: Path, monkeypatch
) -> None:
    client = BridgeClient(tmp_path)
    monkeypatch.setattr(client, "request_save", lambda: {"ok": True, "message": "returned"})

    def create_saves() -> None:
        time.sleep(0.02)
        (tmp_path / "user_manual.eu4").write_bytes(MINIMAL_SAVE)
        time.sleep(0.05)
        (tmp_path / "mp_autosave.eu4").write_bytes(MINIMAL_SAVE)

    worker = threading.Thread(target=create_saves)
    worker.start()
    result = client.request_save_and_wait(
        tmp_path, timeout=1, poll_interval=0.01, stable_checks=2
    )
    worker.join()

    assert Path(result["save_path"]).name == "mp_autosave.eu4"
