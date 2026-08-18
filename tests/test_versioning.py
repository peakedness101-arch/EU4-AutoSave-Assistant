import json
from pathlib import Path

from eu4_assistant.versioning import detect_game_version
from eu4_assistant.config import AppConfig, default_game_directory, documents_directory


def test_detects_only_491d(tmp_path: Path) -> None:
    path = tmp_path / "launcher-settings.json"
    path.write_text(json.dumps({"version": "EU4 v1.37.5.0 Inca (491d)"}), encoding="utf-8")
    status = detect_game_version(tmp_path)
    assert status.supported
    assert status.detected_build_id == "491d"


def test_rejects_other_build_without_hashing(tmp_path: Path) -> None:
    path = tmp_path / "launcher-settings.json"
    path.write_text(json.dumps({"version": "EU4 v1.37.5.0 Inca (ffff)"}), encoding="utf-8")
    status = detect_game_version(tmp_path)
    assert not status.supported
    assert status.detected_build_id == "ffff"


def test_default_save_path_uses_windows_documents_location() -> None:
    assert Path(AppConfig().save_dir) == (
        documents_directory()
        / "Paradox Interactive"
        / "Europa Universalis IV"
        / "save games"
    )


def test_game_directory_can_be_configured_without_a_machine_specific_default(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("EU4_GAME_DIR", str(tmp_path))
    assert default_game_directory() == str(tmp_path)
    assert AppConfig().game_dir == str(tmp_path)
