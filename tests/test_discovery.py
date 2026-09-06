from pathlib import Path

from eu4_assistant.discovery import (
    detect_eu4_installation,
    detect_eu4_save_directory,
    is_eu4_installation,
)


def _make_game(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "eu4.exe").write_bytes(b"exe")
    (path / "launcher-settings.json").write_text("{}", encoding="utf-8")
    return path


def test_detects_eu4_from_secondary_steam_library(tmp_path: Path) -> None:
    steam = tmp_path / "Steam"
    library = tmp_path / "Games"
    (steam / "steamapps").mkdir(parents=True)
    (library / "steamapps").mkdir(parents=True)
    (steam / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n"1" { "path" "'
        + str(library).replace("\\", r"\\")
        + '" }\n}',
        encoding="utf-8",
    )
    (library / "steamapps" / "appmanifest_236850.acf").write_text(
        '"AppState" { "installdir" "Europa Universalis IV" }',
        encoding="utf-8",
    )
    game = _make_game(
        library / "steamapps" / "common" / "Europa Universalis IV"
    )

    detected = detect_eu4_installation(candidate_steam_roots=[steam])

    assert detected == game.resolve()
    assert is_eu4_installation(detected)


def test_valid_configured_game_directory_has_priority(tmp_path: Path) -> None:
    configured = _make_game(tmp_path / "configured")
    other = _make_game(
        tmp_path / "Steam" / "steamapps" / "common" / "Europa Universalis IV"
    )

    detected = detect_eu4_installation(
        configured,
        candidate_steam_roots=[tmp_path / "Steam"],
    )

    assert detected == configured.resolve()
    assert detected != other.resolve()


def test_detects_redirected_documents_save_directory(tmp_path: Path) -> None:
    documents = tmp_path / "Redirected Documents"
    saves = documents / "Paradox Interactive" / "Europa Universalis IV" / "save games"
    saves.mkdir(parents=True)

    detected = detect_eu4_save_directory(
        documents_root=documents,
        candidate_steam_roots=[],
    )

    assert detected == saves.resolve()


def test_returns_expected_documents_path_before_first_save(tmp_path: Path) -> None:
    documents = tmp_path / "Documents"

    detected = detect_eu4_save_directory(
        documents_root=documents,
        candidate_steam_roots=[],
    )

    assert detected == documents / "Paradox Interactive" / "Europa Universalis IV" / "save games"
