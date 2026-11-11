from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from eu4_assistant.alerts import army_concentration_warnings
from eu4_assistant.models import ActiveWarSnapshot, ArmySnapshot, CountrySnapshot, PlayerCountry
from eu4_assistant.parser import SaveParseError, _decode_province_name, parse_save
from eu4_assistant.mapdata import ProvinceInfo
from test_parser import MINIMAL_SAVE
from test_mini_window import application, window, make_record


def army(location, regiments, strength=1):
    return ArmySnapshot(str(location), "army", location, regiments, strength)


def concentration_record():
    record = make_record()
    record.countries["ENG"].armies = [army(1, 6), army(1, 5), army(2, 10), army(None, 79)]
    record.countries["FRA"].armies = [army(1, 1)]
    return record


def test_threshold_uses_regiments_aggregates_and_counts_unknown_locations():
    record = concentration_record()
    warnings = army_concentration_warnings(record)
    assert [(w.province_id, w.regiment_count, w.total_regiments) for w in warnings] == [(1, 11, 100)]
    assert warnings[0].ratio == .11


@pytest.mark.parametrize("side", ["attacker", "defender", "ally", "neutral", "separate_peace"])
def test_enemy_presence_only_suppresses_opposite_current_sides(side):
    record = concentration_record()
    if side == "attacker":
        record.active_wars = [ActiveWarSnapshot({"ENG"}, {"FRA"})]
    elif side == "defender":
        record.active_wars = [ActiveWarSnapshot({"FRA"}, {"ENG"})]
    elif side == "ally":
        record.active_wars = [ActiveWarSnapshot({"ENG", "FRA"}, {"SPA"})]
    elif side == "separate_peace":
        record.active_wars = [ActiveWarSnapshot({"ENG"}, {"SPA"})]
    assert bool(army_concentration_warnings(record)) == (side not in {"attacker", "defender"})
    record.countries["FRA"].armies[0].location = 99
    assert len(army_concentration_warnings(record)) == 1


def test_empty_armies_and_missing_local_identity():
    record = concentration_record()
    record.countries["ENG"].armies = []
    assert army_concentration_warnings(record) == []
    record.local_player_tag = None
    assert army_concentration_warnings(record) == []


@pytest.mark.parametrize("compressed", [False, True])
def test_parse_current_sides_names_and_history_separation(tmp_path, compressed):
    war = b'''\nactive_war={
\thistory={
\t\t1499.1.1={
\t\t\tadd_attacker="ENG"
\t\t\tadd_defender="SPA"
\t\t}
\t}
\tattackers={ ENG }
\tdefenders={ "FRA" }
\tpersistent_defenders={ FRA SPA }
\toriginal_defender="SPA"
}
'''
    path = tmp_path / "war.eu4"
    if compressed:
        with ZipFile(path, "w", ZIP_DEFLATED) as archive:
            archive.writestr("meta", b'EU4txt\nplayer="ENG"\ndate=1500.1.1\n')
            archive.writestr("gamestate", MINIMAL_SAVE + war)
    else:
        path.write_bytes(MINIMAL_SAVE + war)
    record = parse_save(path, include_all_countries=True)
    assert record.active_wars == [ActiveWarSnapshot({"ENG"}, {"FRA"})]
    assert record.province_names == {236: "London", 183: "Paris"}
    assert "ENG" in record.existing_tags  # occupied by FRA, still exists
    path.write_bytes(MINIMAL_SAVE + b'\nactive_war={\n\tattackers={ ENG }\n}\n')
    with pytest.raises(SaveParseError, match="双方名单"):
        parse_save(path)


def test_regiment_parser_counts_depleted_and_mercenary_regiments(tmp_path):
    data = MINIMAL_SAVE.replace(b'\t\t\tlocation=236', b'\t\t\tmercenary=yes\n\t\t\tlocation=236')
    path = tmp_path / "merc.eu4"
    path.write_bytes(data)
    country = parse_save(path).countries["ENG"]
    assert country.armies[0].regiment_count == 1
    assert country.armies[0].strength == 750


def test_monitor_drops_extinct_tags_keeps_ai_and_deduplicates(window, monkeypatch):
    record = make_record()
    record.countries["CAS"] = CountrySnapshot("CAS", player_name="Old player")
    record.players.extend([PlayerCountry("Old player", "CAS"), PlayerCountry("Other", "FRA")])
    window.selected_country_tag = "CAS"
    monkeypatch.setattr(window, "_ensure_map_index", lambda **kwargs: None)
    window._show_record(record)
    assert window._mini_player_tags() == ["ENG", "FRA"]
    assert window.selected_country_tag == "ENG"
    assert "CAS" in record.countries
    record.province_owners.clear()
    window._show_record(record)
    assert window.selected_country_tag is None
    assert window._selected_country() is None


def test_monitor_falls_back_to_first_valid_player_without_local(window, monkeypatch):
    record = make_record()
    record.local_player_tag = "CAS"
    monkeypatch.setattr(window, "_ensure_map_index", lambda **kwargs: None)
    window._show_record(record)
    assert window.selected_country_tag == "ENG"


def test_warning_stays_local_names_fallback_clear_and_reopen(window, monkeypatch):
    record = concentration_record()
    record.province_names[1] = "My London"
    window.current_record = record
    window.selected_country_tag = "FRA"
    window._mini_toggle_window()
    mini = window.mini_window
    assert "FRA" in mini.title_label.text()
    assert "本机 ENG" in mini.warning_title.text()
    assert "My London（1）｜11 / 100 团" in mini.warning_text.text()
    window._mini_switch_country(1)
    assert "My London" in mini.warning_text.text()
    record.province_names.clear()
    window.provinces[1] = ProvinceInfo(1, "Fallback London", 0, 0, 0)
    window._update_mini_window()
    assert "Fallback London（1）" in mini.warning_text.text()
    window.provinces.clear()
    window._update_mini_window()
    assert "未知省份（1）" in mini.warning_text.text()
    window._mini_toggle_window()
    record.countries["ENG"].armies = []
    window._update_mini_window()
    assert not mini.isVisible()
    window._mini_toggle_window()
    assert mini.warning_text.text() == ""
    assert "无警告" in mini.warning_title.text()
    record.local_player_tag = None
    window._update_mini_window()
    assert "无法识别本机玩家国家" in mini.warning_title.text()


def test_many_warnings_are_sorted_and_scrollable(window, application):
    from PySide6.QtTest import QTest
    record = make_record()
    record.countries["ENG"].armies = [army(i, i + 100) for i in range(1, 10)]
    window.current_record = record
    window.selected_country_tag = "ENG"
    window._mini_toggle_window()
    application.processEvents()
    QTest.qWait(30)  # QScrollArea applies its deferred layout after the label changes.
    mini = window.mini_window
    assert len(mini.warning_text.text().splitlines()) == 9
    assert mini.warning_text.text().splitlines()[0].startswith("未知省份（9）")
    assert mini.warning_scroll.verticalScrollBar().maximum() > 0, (
        mini.size().toTuple(), mini.warning_text.size().toTuple(),
        mini.warning_text.minimumSize().toTuple(), mini.warning_text.heightForWidth(240),
        mini.warning_scroll.size().toTuple(), mini.warning_text.text(),
    )


def sync_workers(window, monkeypatch):
    def run(function, callback, *args, on_error=None, on_finished=None, **kwargs):
        try:
            callback(function(*args, **kwargs))
        except Exception as exc:
            if on_error:
                on_error(str(exc))
            else:
                raise
        finally:
            if on_finished:
                on_finished()
    monkeypatch.setattr(window, "_run_worker", run)
    monkeypatch.setattr(window, "_ensure_map_index", lambda **kwargs: None)


@pytest.mark.parametrize("archive_enabled,archive_fails", [(False, False), (True, False), (True, True)])
def test_save_always_parses_before_archive(window, monkeypatch, tmp_path, archive_enabled, archive_fails):
    import eu4_assistant.ui.main_window as module
    source = Path(window.config.save_dir) / "c1234567890123.eu4"
    source.write_bytes(MINIMAL_SAVE)
    sync_workers(window, monkeypatch)
    window.auto_archive_checkbox.setChecked(archive_enabled)
    monkeypatch.setattr(window.bridge, "request_save_and_wait", lambda directory: {
        "ok": True, "file_created": True, "save_path": str(source)
    })
    real_archive = module.archive_save
    calls = []
    def archive(*args, **kwargs):
        assert window.current_record is not None
        assert window.current_record.path == source.resolve()
        assert not window.auto_parse_pending
        calls.append(source)
        if archive_fails:
            raise OSError("archive unavailable")
        return real_archive(*args, **kwargs)
    monkeypatch.setattr(module, "archive_save", archive)
    window._request_native_save()
    assert window.current_record.game_date == "1500.1.1"
    window._scan_auto_archive()
    assert bool(calls) == archive_enabled
    assert source.exists() == (not archive_enabled or archive_fails)
    assert window.current_record.path.is_file()
    assert Path(window.database.list_saves()[0]["path"]).is_file()
    if archive_fails:
        assert "自动归档失败" in window.archive_log.toPlainText()


def test_parse_failure_keeps_previous_record_and_retries(window, monkeypatch):
    sync_workers(window, monkeypatch)
    window.current_record = make_record()
    previous = window.current_record
    source = Path(window.config.save_dir) / "c1234567890123.eu4"
    source.write_bytes(b"bad save")
    window._import_verified_save(source)
    assert window.current_record is previous
    assert source.exists()
    assert "自动解析失败" in window.import_status.text()
    assert not window.auto_parse_pending
    window.auto_archive_checkbox.setChecked(True)
    window._scan_auto_archive()
    assert source.exists()
    source.write_bytes(MINIMAL_SAVE)
    window._import_verified_save(source)
    assert window.current_record is not previous


def test_duplicate_requests_and_out_of_order_completion(window, monkeypatch, tmp_path):
    import os
    jobs = []
    monkeypatch.setattr(window, "_ensure_map_index", lambda **kwargs: None)
    monkeypatch.setattr(window, "_run_worker", lambda *args, **kwargs: jobs.append((args, kwargs)))
    old, new = tmp_path / "old.eu4", tmp_path / "new.eu4"
    old.write_bytes(MINIMAL_SAVE)
    new.write_bytes(MINIMAL_SAVE.replace(b"1500.1.1", b"1500.2.1"))
    os.utime(old, ns=(1_000_000_000, 1_000_000_000))
    os.utime(new, ns=(2_000_000_000, 2_000_000_000))
    window._import_verified_save(old)
    window._import_verified_save(new)
    window._import_verified_save(new)
    assert len(jobs) == 2
    for args, kwargs in reversed(jobs):
        args[1](args[0](args[2], include_all_countries=True))
        kwargs["on_finished"]()
    assert window.current_record.game_date == "1500.2.1"
    assert len(window.records) == 2
    window._import_verified_save(new)
    assert len(jobs) == 2


def test_scanner_does_not_move_source_being_parsed(window, monkeypatch):
    jobs = []
    source = Path(window.config.save_dir) / "c1234567890123.eu4"
    source.write_bytes(MINIMAL_SAVE)
    monkeypatch.setattr(window, "_run_worker", lambda *args, **kwargs: jobs.append((args, kwargs)))
    window.auto_archive_checkbox.setChecked(True)
    window._import_verified_save(source)
    window._scan_auto_archive()
    assert len(jobs) == 1
    assert source.is_file()


def test_failed_save_does_not_start_parsing(window, monkeypatch):
    sync_workers(window, monkeypatch)
    previous = make_record()
    window.current_record = previous
    monkeypatch.setattr(window.bridge, "request_save_and_wait", lambda directory: {
        "ok": False, "file_created": False, "save_path": "no.eu4"
    })
    monkeypatch.setattr(window, "_import_verified_save", lambda path: pytest.fail("unexpected parse"))
    window._request_native_save()
    assert window.current_record is previous


def test_identical_snapshots_share_record_when_paths_are_updated(window, monkeypatch, tmp_path):
    sync_workers(window, monkeypatch)
    old, new = tmp_path / "old.eu4", tmp_path / "new.eu4"
    old.write_bytes(MINIMAL_SAVE)
    new.write_bytes(MINIMAL_SAVE)
    window._import_verified_save(new)
    current = window.current_record
    window._import_verified_save(old)
    assert window.current_record is current
    assert window.records[current.fingerprint] is current
    assert current.path.is_file()


@pytest.mark.parametrize("raw,expected", [
    (b'\x10\xcc\x91\x12\x36\x77\x10\x61\x53', '里耶卡'),
    (b'\x10\xcc\x91', '里'),
    (b'\x11\x2e\x4e', '丠'),
    (b'\x12\x2d\x45', '中'),
    (b'\x13\x3b\x45', '中'),
    (b'Paris', 'Paris'),
    ('北京'.encode(), '北京'),
    (b'Le\xf3n', 'León'),
    (b'\x10\xcc', ''),
])
def test_province_name_encodings(raw, expected):
    assert _decode_province_name(raw) == expected
