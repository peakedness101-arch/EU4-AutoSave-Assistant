from pathlib import Path

import pytest

from eu4_assistant.archive import (
    archive_many,
    archive_save,
    undo_last_archive,
    wait_for_stable_file,
)
from eu4_assistant.parser import parse_save
from eu4_assistant.storage import SaveDatabase

from test_parser import MINIMAL_SAVE


def test_sqlite_import_and_deduplicate(tmp_path: Path) -> None:
    save = tmp_path / "source.eu4"
    save.write_bytes(MINIMAL_SAVE)
    record = parse_save(save)
    database = SaveDatabase(tmp_path / "assistant.sqlite3")
    try:
        assert database.import_record(record)
        assert not database.import_record(record)
        assert len(database.list_saves()) == 1
        assert database.list_saves()[0]["game_version"] == "1.37.5.0"
        assert database.list_saves()[0]["multiplayer"] == 1
        country = database.list_countries(record.fingerprint)[0]
        assert country["tag"] == "ENG"
        assert country["sailors"] == 2500
        assert country["max_sailors"] == 5000
        assert country["ship_count"] == 2
    finally:
        database.close()


def test_safe_archive_and_undo(tmp_path: Path) -> None:
    source = tmp_path / "save games" / "mp_autosave.eu4"
    source.parent.mkdir()
    source.write_bytes(MINIMAL_SAVE)
    archive_root = tmp_path / "archives"
    result = archive_save(
        source,
        archive_root,
        "测试战役",
        remove_source=True,
        wait_until_stable=False,
    )
    destination = Path(result.destination)
    assert destination.is_file()
    assert not source.exists()
    undo = undo_last_archive(archive_root)
    assert Path(undo.restored_source).is_file()
    assert not destination.exists()


def test_stability_wait_has_a_timeout(tmp_path: Path) -> None:
    source = tmp_path / "still-writing.eu4"
    source.write_bytes(MINIMAL_SAVE)
    with pytest.raises(TimeoutError, match="等待存档稳定超时"):
        wait_for_stable_file(
            source, checks=100, interval_seconds=0.005, timeout_seconds=0.02
        )


def test_batch_archive_isolates_failures(tmp_path: Path) -> None:
    good = tmp_path / "good.eu4"
    bad = tmp_path / "bad.eu4"
    good.write_bytes(MINIMAL_SAVE)
    bad.write_bytes(b"not a save")
    items = archive_many(
        [bad, good],
        tmp_path / "archives",
        "测试战役",
        remove_source=True,
        wait_until_stable=False,
    )
    assert items[0].error
    assert bad.is_file()
    assert items[1].result is not None
    assert Path(items[1].result.destination).is_file()
    assert not good.exists()
