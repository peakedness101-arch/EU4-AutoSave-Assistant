import json
from pathlib import Path

from eu4_assistant.versioning import detect_game_version
from eu4_assistant.config import AppConfig, documents_directory, load_config, save_config


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


def test_mod_settings_round_trip_and_default_disabled(tmp_path: Path) -> None:
    config = AppConfig()
    assert not config.mod_mode_enabled
    assert not config.setup_confirmed
    config.mod_mode_enabled = True
    config.mod_dir = r"D:\Mods\Example"
    config.setup_confirmed = True
    path = tmp_path / "settings.json"

    save_config(config, path)
    restored = load_config(path)

    assert restored.mod_mode_enabled
    assert restored.mod_dir == r"D:\Mods\Example"
    assert restored.setup_confirmed


def test_legacy_settings_are_treated_as_already_confirmed(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"campaign_name": "旧版用户"}), encoding="utf-8")

    restored = load_config(path)

    assert restored.setup_confirmed
