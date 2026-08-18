from pathlib import Path

from eu4_assistant.savefiles import is_managed_autosave, latest_save, managed_autosaves


def test_managed_autosave_names_are_exact(tmp_path: Path) -> None:
    names = [
        "mp_autosave.eu4",
        "c3431174315816.eu4",
        "manual.eu4",
        "c123.eu4",
        "c3431174315816.txt",
    ]
    for name in names:
        (tmp_path / name).write_bytes(b"x")

    assert is_managed_autosave("MP_AUTOSAVE.EU4")
    assert is_managed_autosave("c3431174315816.eu4")
    assert not is_managed_autosave("manual.eu4")
    assert {path.name for path in managed_autosaves(tmp_path)} == {
        "mp_autosave.eu4",
        "c3431174315816.eu4",
    }


def test_latest_save_uses_file_modification_time(tmp_path: Path) -> None:
    older = tmp_path / "older.eu4"
    newer = tmp_path / "newer.eu4"
    older.write_bytes(b"old")
    newer.write_bytes(b"new")
    older.touch()
    newer.touch()
    older_time = older.stat().st_mtime_ns
    import os
    os.utime(newer, ns=(older_time + 1_000_000, older_time + 1_000_000))
    assert latest_save(tmp_path) == newer
    assert latest_save(tmp_path / "missing") is None
    nested = tmp_path / "campaign" / "1500"
    nested.mkdir(parents=True)
    archived = nested / "archived.eu4"
    archived.write_bytes(b"archive")
    archived_time = newer.stat().st_mtime_ns + 1_000_000
    os.utime(archived, ns=(archived_time, archived_time))
    assert latest_save(tmp_path) == newer
    assert latest_save(tmp_path, recursive=True) == archived
