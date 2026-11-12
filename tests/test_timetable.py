import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from eu4_assistant.timetable import (
    GameDate, TimetableEntry, TimetableStore, due_entries, parse_game_date,
    read_timetable, shift_months, write_timetable,
)
import eu4_assistant.timetable as timetable_module
import eu4_assistant.ui.timetable as panel_module
from eu4_assistant.ui.timetable import TimetablePanel
from test_mini_window import application, window, make_record


def entry(date="1500.06.15", note="准备下一阶段\n勿忘事项"):
    return TimetableEntry(parse_game_date(date), note)


@pytest.mark.parametrize("date,expected", [
    ("1500.03.14", False), ("1500.03.15", True), ("1500.06.15", True),
    ("1500.09.15", True), ("1500.09.16", False),
])
def test_inclusive_reminder_range(date, expected):
    assert bool(due_entries([entry()], parse_game_date(date))) == expected


@pytest.mark.parametrize("date,months,expected", [
    ("1500.05.31", -3, "1500.02.28"), ("1500.01.31", 3, "1500.04.30"),
    ("1500.01.15", -3, "1499.10.15"), ("1500.12.31", 3, "1501.03.31"),
    ("0001.01.15", -3, "0001.01.01"), ("20000.12.15", 3, "20000.12.31"),
])
def test_fixed_calendar_month_arithmetic(date, months, expected):
    assert str(shift_months(parse_game_date(date), months)) == expected


@pytest.mark.parametrize("date", ["1500.2.29", "1600.2.29", "0.1.1", "20001.1.1", "1500.4.31", "1500.0.1", "1500-06-15", None, True])
def test_rejects_invalid_game_dates(date):
    with pytest.raises(ValueError):
        parse_game_date(date)


def test_multiple_dates_sort_and_clock_rollback():
    items = [entry("1500.07.01", "后"), entry("1500.05.01", "前"), entry("1500.05.01", "同日")]
    assert [item.note for item in due_entries(items, GameDate(1500, 6, 1))] == ["前", "同日", "后"]
    assert due_entries(items, GameDate(1600, 1, 1)) == []
    assert len(due_entries(items, GameDate(1500, 6, 1))) == 3
    assert due_entries(items, None) == []


def test_roundtrip_restart_import_replacement_backup_and_empty(tmp_path):
    local = tmp_path / "config" / "timetable.json"
    store = TimetableStore(local)
    assert store.entries == [] and not local.exists()
    store.save([entry()])
    assert TimetableStore(local).entries == [entry()]
    exported = tmp_path / "shared.json"
    write_timetable(exported, store.entries)
    raw = json.loads(exported.read_text(encoding="utf-8"))
    assert raw == {"format_version": 1, "items": [{"date": "1500.06.15", "note": entry().note}]}
    assert "准备" in exported.read_text(encoding="utf-8")
    old = local.read_bytes()
    backup = store.replace([entry("1550.01.01", "新事项")])
    assert backup.read_bytes() == old
    assert store.entries == TimetableStore(local).entries == [entry("1550.01.01", "新事项")]
    store.replace([])
    assert store.entries == read_timetable(local) == []


@pytest.mark.parametrize("payload", [
    "not json", '[]', '{"format_version":2,"items":[]}',
    '{"format_version":true,"items":[]}', '{"format_version":1,"items":{}}',
    '{"format_version":1,"items":[{"date":"1600.02.29","note":"x"}]}',
    '{"format_version":1,"items":[{"date":"1500.01.01","note":" "}]}',
    '{"format_version":1,"items":[{"date":"1500.01.01","note":42}]}',
    '{"format_version":1,"items":[{}]}', '{"format_version":1,"items":[null]}',
])
def test_bad_import_and_corrupt_local_preserve_data(tmp_path, payload):
    local = tmp_path / "local.json"
    local.write_text(payload, encoding="utf-8")
    store = TimetableStore(local)
    assert store.load_error
    with pytest.raises(ValueError):
        read_timetable(local)
    with pytest.raises(ValueError):
        store.save([])
    assert local.read_text(encoding="utf-8") == payload
    backup = store.replace([entry()])
    assert backup.read_text(encoding="utf-8") == payload
    assert store.load_error is None and read_timetable(local) == [entry()]


@pytest.mark.parametrize("operation", ["save", "backup", "replace"])
def test_io_failure_does_not_change_saved_or_memory_data(tmp_path, monkeypatch, operation):
    store = TimetableStore(tmp_path / "local.json")
    store.save([entry()])
    before = store.path.read_bytes()
    def fail(*args, **kwargs):
        raise OSError("test disk failure")
    if operation == "backup":
        monkeypatch.setattr(timetable_module.shutil, "copy2", fail)
    else:
        monkeypatch.setattr(timetable_module.os, "replace", fail)
    with pytest.raises(OSError):
        (store.save if operation == "save" else store.replace)([])
    assert store.entries == [entry()]
    assert store.path.read_bytes() == before
    assert not list(tmp_path.glob("*.partial"))


def status(date="1500.06.15", **kwargs):
    values = dict(connected=True, game_loaded=True, synchronized=True, saving=False, game_date=date, message="fixture")
    values.update(kwargs)
    return SimpleNamespace(**values)


def test_editor_crud_restart_and_day_limits(window, tmp_path):
    panel = window.timetable_panel
    panel.year.setValue(1600)
    panel.day.setValue(31)
    panel.month.setValue(2)
    assert panel.day.maximum() == panel.day.value() == 28
    panel.month.setValue(6)
    panel.day.setValue(15)
    panel.note.setPlainText("第一条\n多行内容")
    panel.save_entry()
    assert len(panel.store.entries) == 1
    panel.table.setCurrentCell(0, 0)
    panel.note.setPlainText("修改后")
    panel.save_entry()
    assert panel.store.entries[0].note == "修改后"
    assert TimetableStore(panel.store.path).entries == panel.store.entries
    panel.table.setCurrentCell(0, 0)
    panel.delete_entry()
    assert panel.store.entries == read_timetable(panel.store.path) == []


def test_ui_reject_empty_and_preserve_form_on_failed_save(window, monkeypatch):
    panel = window.timetable_panel
    errors = []
    monkeypatch.setattr(panel, "_error", lambda exc: errors.append(str(exc)))
    panel.save_entry()
    assert errors and panel.store.entries == []
    panel.note.setPlainText("保留输入")
    def fail(*args):
        raise OSError("无法保存")
    monkeypatch.setattr(panel.store, "save", fail)
    panel.save_entry()
    assert panel.note.toPlainText() == "保留输入" and panel.store.entries == []


def test_json_ui_confirmation_validation_export_and_replace(window, monkeypatch, tmp_path):
    panel = window.timetable_panel
    panel.store.save([entry()])
    panel._refresh()
    errors = []
    monkeypatch.setattr(panel, "_error", lambda exc: errors.append(str(exc)))
    incoming = tmp_path / "incoming.json"
    incoming.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(panel_module.QFileDialog, "getOpenFileName", lambda *args: (str(incoming), ""))
    confirmations = []
    def confirm(*args):
        confirmations.append(args[2])
        return QMessageBox.StandardButton.No
    monkeypatch.setattr(panel_module.QMessageBox, "question", confirm)
    panel.import_file()
    assert errors and not confirmations and panel.store.entries == [entry()]
    write_timetable(incoming, [])
    panel.import_file()
    assert confirmations and panel.store.entries == [entry()]
    monkeypatch.setattr(panel_module.QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    panel.import_file()
    assert panel.store.entries == []
    assert list((panel.store.path.parent / "timetable_backups").glob("*.json"))
    output = tmp_path / "out.json"
    monkeypatch.setattr(panel_module.QFileDialog, "getSaveFileName", lambda *args: (str(output), ""))
    panel.export_file()
    assert read_timetable(output) == []


def test_corrupt_file_disables_edit_but_allows_import(application, tmp_path):
    path = tmp_path / "bad.json"
    path.write_bytes(b"broken")
    panel = TimetablePanel(TimetableStore(path))
    assert not panel.save_button.isEnabled()
    assert not panel.delete_button.isEnabled()
    assert panel.import_button.isEnabled()
    assert "原文件已保留" in panel.storage_status.text()
    panel.close()


def test_bridge_clock_priority_disconnect_lobby_error_and_bad_dates(window, monkeypatch):
    monkeypatch.setattr(window, "_evaluate_schedule", lambda status: None)
    record = make_record()
    record.game_date = "1490.01.01"
    window.current_record = record
    assert window._timetable_date() == (GameDate(1490, 1, 1), "存档预览")
    window._bridge_status_ready(status())
    assert window._timetable_date() == (GameDate(1500, 6, 15), "实时游戏")
    for invalid in [status(connected=False), status(game_loaded=False), status(synchronized=False), status("bad"), status("1600.2.29")]:
        window._bridge_status_ready(status())
        window._bridge_status_ready(invalid)
        assert window._timetable_date() == (GameDate(1490, 1, 1), "存档预览")
    window._bridge_status_ready(status())
    window._bridge_poll_failed("fixture error")
    assert window.timetable_live_date is None
    window.current_record = None
    assert window._timetable_date()[0] is None


def test_mini_refresh_scroll_country_switch_hidden_and_fixed_controls(window, application, monkeypatch):
    monkeypatch.setattr(window, "_evaluate_schedule", lambda status: None)
    window.current_record = make_record()
    window.current_record.game_date = "1500.06.15"
    window.selected_country_tag = "ENG"
    panel = window.timetable_panel
    items = [entry(note=f"事项{i}：" + "很长的多行注意事项" * 20) for i in range(8)]
    panel.store.save(items)
    window._refresh_timetable()
    assert window.mini_window is None
    window._mini_toggle_window()
    mini = window.mini_window
    QTest.qWait(30)
    assert mini.timetable_text.text().count("1500.06.15") == 8
    assert "存档预览" in mini.timetable_title.text()
    assert mini.timetable_scroll.verticalScrollBar().maximum() > 0
    positions = [button.geometry() for button in mini.country_switch_buttons]
    window._mini_switch_country(1)
    assert "事项0" in mini.timetable_text.text()
    window._bridge_status_ready(status("1510.01.01"))
    assert not mini.timetable_scroll.isVisible()
    window._bridge_status_ready(status())
    assert "实时游戏" in mini.timetable_title.text()
    window._mini_toggle_lock()
    assert mini.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    application.processEvents()
    assert mini.width() == 400
    assert [button.geometry() for button in mini.country_switch_buttons] == positions
    window._mini_toggle_window()
    window._bridge_status_ready(status("1510.01.01"))
    assert not mini.isVisible()
    window._mini_toggle_window()
    assert mini.timetable_text.text() == ""
    window._bridge_status_ready(status())
    panel.store.save([])
    panel.changed.emit()
    assert mini.timetable_text.text() == "" and not mini.timetable_scroll.isVisible()


def test_timetable_is_not_version_gated(window, monkeypatch):
    import eu4_assistant.ui.main_window as module
    unsupported = SimpleNamespace(supported=False, detected_build_id="unknown", reason="fixture")
    monkeypatch.setattr(module, "detect_game_version", lambda path: unsupported)
    window.config.allow_unsupported_version = False
    window._refresh_version_status()
    assert window.tool_dialogs["timetable"].isEnabled()
    assert window.left_tool_buttons["timetable"].isEnabled()
    assert not window.tool_dialogs["timetable"].isModal()
    assert window.tool_dialogs["timetable"] not in window.analysis_dialogs


def test_new_button_creates_visible_draft_and_save_persists_it(window, application):
    panel = window.timetable_panel
    window._show_tool_dialog("timetable")
    QTest.mouseClick(panel.new_button, Qt.MouseButton.LeftButton)
    application.processEvents()
    assert panel.table.rowCount() == 1
    assert "未保存" in panel.table.item(0, 1).text()
    assert "正在新增" in panel.storage_status.text()
    assert panel.note.hasFocus()
    assert panel.store.entries == []
    panel.note.setPlainText("真实按钮新增\n补充说明")
    QTest.mouseClick(panel.new_button, Qt.MouseButton.LeftButton)
    assert panel.note.toPlainText() == "真实按钮新增\n补充说明"
    assert panel.table.rowCount() == 1
    QTest.mouseClick(panel.save_button, Qt.MouseButton.LeftButton)
    assert len(panel.store.entries) == 1
    assert panel.store.entries[0].note == "真实按钮新增\n补充说明"
    assert read_timetable(panel.store.path) == panel.store.entries
    assert "未保存" not in panel.table.item(0, 1).text()


@pytest.mark.parametrize("note", ["", "提前写好的注意事项", "第一行\n第二行"])
@pytest.mark.parametrize("from_saved_entry", [False, True])
def test_new_draft_copies_current_date_and_note(window, application, note, from_saved_entry):
    panel = window.timetable_panel
    if from_saved_entry:
        panel.store.save([entry()])
        panel._refresh()
        panel.table.setCurrentCell(0, 0)
    window._show_tool_dialog("timetable")
    panel.year.setValue(1780)
    panel.month.setValue(6)
    panel.day.setValue(15)
    panel.note.setPlainText(note)
    original = list(panel.store.entries)
    QTest.mouseClick(panel.new_button, Qt.MouseButton.LeftButton)
    application.processEvents()
    assert panel._draft == (GameDate(1780, 6, 15), note)
    assert panel.note.toPlainText() == note
    assert panel.table.item(panel.table.currentRow(), 0).text() == "1780.06.15"
    assert (" ".join(note.splitlines()) or "请在下方填写注意事项") in panel.table.item(panel.table.currentRow(), 1).text()
    assert panel.store.entries == original
    if note:
        QTest.mouseClick(panel.save_button, Qt.MouseButton.LeftButton)
        assert panel.store.entries == original + [entry("1780.06.15", note)]
        assert read_timetable(panel.store.path) == panel.store.entries


def test_date_arrow_buttons_respond_to_clicks_and_clamp_month_end(window, application):
    panel = window.timetable_panel
    window._show_tool_dialog("timetable")
    panel.year.setValue(1780)
    panel.month.setValue(5)
    panel.day.setValue(15)
    application.processEvents()
    for spin, controls in zip([panel.year, panel.month, panel.day], panel.date_steppers):
        previous = spin.value()
        QTest.mouseClick(controls.up, Qt.MouseButton.LeftButton)
        assert spin.value() == previous + 1
        QTest.mouseClick(controls.down, Qt.MouseButton.LeftButton)
        assert spin.value() == previous
    panel.month.setValue(1)
    panel.day.setValue(31)
    QTest.mouseClick(panel.date_steppers[1].up, Qt.MouseButton.LeftButton)
    assert panel.month.value() == 2 and panel.day.value() == 28
    assert not panel.date_steppers[2].up.isEnabled()
    QTest.mouseClick(panel.date_steppers[2].down, Qt.MouseButton.LeftButton)
    assert panel.day.value() == 27 and panel.date_steppers[2].up.isEnabled()
    panel.day.setValue(1)
    assert not panel.date_steppers[2].down.isEnabled()


def test_draft_restores_when_selecting_saved_item_and_can_be_cancelled(window, application):
    panel = window.timetable_panel
    panel.store.save([entry()])
    panel._refresh()
    window._show_tool_dialog("timetable")
    QTest.mouseClick(panel.new_button, Qt.MouseButton.LeftButton)
    panel.note.setPlainText("保留草稿")
    panel.year.setValue(1780)
    panel.table.setCurrentCell(0, 0)
    panel.note.setPlainText("修改已保存项")
    QTest.mouseClick(panel.save_button, Qt.MouseButton.LeftButton)
    assert panel.table.rowCount() == 2
    QTest.mouseClick(panel.new_button, Qt.MouseButton.LeftButton)
    assert panel.note.toPlainText() == "保留草稿" and panel.year.value() == 1780
    QTest.mouseClick(panel.delete_button, Qt.MouseButton.LeftButton)
    assert panel.table.rowCount() == 1
    assert len(panel.store.entries) == 1
    assert panel.store.entries[0].note == "修改已保存项"
