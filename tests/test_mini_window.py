from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QFileSystemWatcher, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication

from eu4_assistant.hotkeys import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_SHIFT,
    sequence_to_registration,
)
from eu4_assistant.models import ArmySnapshot, CountrySnapshot, PlayerCountry, SaveRecord
from eu4_assistant.ui.main_window import MainWindow
import eu4_assistant.ui.main_window as main_window_module


@pytest.fixture(scope="module")
def application() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(application: QApplication, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(MainWindow, "_load_database_index", lambda _self: None)
    monkeypatch.setattr(MainWindow, "_install_save_watcher", lambda _self: None)
    monkeypatch.setattr(main_window_module, "save_config", lambda _config: None)
    result = MainWindow()
    result.bridge_timer.stop()
    result.show()
    application.processEvents()
    yield result
    result.close()
    application.processEvents()


def make_record() -> SaveRecord:
    england = CountrySnapshot(
        tag="ENG",
        player_name="Alice",
        treasury=40,
        monthly_income=100,
        monthly_expense=250,
        monthly_interest=15,
        manpower=1.5,
        max_manpower=2.0,
        sailors=850,
        max_sailors=1200,
        ship_count=7,
        armies=[
            ArmySnapshot(
                army_id="54:1:1",
                name="First Army",
                location=1,
                regiment_count=12,
                strength=11_500,
            )
        ],
    )
    france = CountrySnapshot(
        tag="FRA",
        player_name="Bob",
        treasury=90,
        monthly_income=300,
        monthly_expense=120,
        ship_count=3,
    )
    return SaveRecord(
        path=Path("mini.eu4"),
        fingerprint="mini",
        format="plaintext",
        game_date="1767.7.27",
        build_id="491d",
        local_player_tag="ENG",
        players=[PlayerCountry("Alice", "ENG"), PlayerCountry("Bob", "FRA")],
        countries={"ENG": england, "FRA": france},
        multiplayer=True,
    )


def test_sequence_to_registration_maps_combinations() -> None:
    mods, vk = sequence_to_registration(QKeySequence("Ctrl+Alt+M"))
    assert mods == MOD_CONTROL | MOD_ALT
    assert vk == ord("M")
    mods, vk = sequence_to_registration(QKeySequence("Shift+F8"))
    assert mods == MOD_SHIFT
    assert vk == 0x77


def test_sequence_to_registration_rejects_plain_modifier_only() -> None:
    assert sequence_to_registration(QKeySequence()) is None


def test_mini_window_opens_and_shows_coarse_stats(window: MainWindow) -> None:
    record = make_record()
    window.current_record = record
    window.map_country_combo.clear()
    window.map_country_combo.addItem("ENG — Alice", "ENG")
    window.map_country_combo.addItem("FRA — Bob", "FRA")

    window._mini_toggle_window()
    assert window.mini_window is not None
    assert window.mini_window.isVisible()
    assert Qt.WindowType.WindowStaysOnTopHint in window.mini_window.windowFlags()
    assert Qt.WindowType.WindowDoesNotAcceptFocus in window.mini_window.windowFlags()

    window.selected_country_tag = "ENG"
    window._country_selection_changed()
    mini = window.mini_window
    assert "ENG" in mini.title_label.text()
    assert mini.stat_rows["treasury"].text() == "40.00"
    assert mini.stat_rows["income"].text() == "100.00"
    assert mini.stat_rows["expense"].text() == "250.00"
    assert mini.stat_rows["interest"].text() == "15.00"
    assert mini.stat_rows["army"].text() == "11,500 人（1 支）"
    assert mini.stat_rows["manpower"].text() == "1,500/2,000 人"
    assert mini.stat_rows["navy"].text() == "7 艘"
    assert mini.stat_rows["sailors"].text() == "850/1,200 人"

    window._mini_toggle_window()
    assert not mini.isVisible()


def test_mini_window_lock_toggles_click_through(window: MainWindow) -> None:
    window.current_record = make_record()
    window.map_country_combo.clear()
    window._mini_toggle_window()
    mini = window.mini_window

    window._mini_toggle_lock()
    assert mini.is_locked
    assert mini.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert mini.lock_button.text() == "解锁"

    window._mini_toggle_lock()
    assert not mini.is_locked
    assert not mini.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert mini.lock_button.text() == "锁定"


def test_mini_window_cycles_countries(window: MainWindow) -> None:
    record = make_record()
    window.current_record = record
    window.map_country_combo.clear()
    window.map_country_combo.addItem("ENG — Alice", "ENG")
    window.map_country_combo.addItem("FRA — Bob", "FRA")
    window.selected_country_tag = "ENG"

    window._mini_toggle_window()
    window._mini_switch_country(1)
    assert window.selected_country_tag == "FRA"
    assert "FRA" in window.mini_window.title_label.text()
    window._mini_switch_country(1)
    assert window.selected_country_tag == "ENG"


def test_mini_window_switches_only_multiplayer_player_countries(window: MainWindow) -> None:
    record = make_record()
    record.countries["SPA"] = CountrySnapshot(tag="SPA", treasury=999)
    window.current_record = record
    window.map_country_combo.clear()
    for tag in ("ENG", "FRA", "SPA"):
        window.map_country_combo.addItem(tag, tag)
    window.selected_country_tag = "SPA"

    window._mini_toggle_window()
    assert "SPA" in window.mini_window.title_label.text()
    window._mini_switch_country(1)
    assert window.selected_country_tag == "ENG"
    window._mini_switch_country(-1)
    assert window.selected_country_tag == "FRA"


def test_mini_window_disables_switching_for_single_player(window: MainWindow) -> None:
    record = make_record()
    record.multiplayer = False
    window.current_record = record
    window.map_country_combo.clear()
    window.selected_country_tag = "ENG"
    window._mini_toggle_window()
    window._update_mini_window()
    assert all(not button.isEnabled() for button in window.mini_window.country_switch_buttons)
    window._mini_switch_country(1)
    assert window.selected_country_tag == "ENG"


def test_settings_tab_exposes_editable_hotkeys(window: MainWindow) -> None:
    window.save_watcher = QFileSystemWatcher(window)
    settings = window.tool_dialogs["settings"]
    assert hasattr(window, "mini_window_hotkey_edit")
    assert hasattr(window, "mini_lock_hotkey_edit")
    window.mini_window_hotkey_edit.setKeySequence(QKeySequence("Ctrl+Shift+F9"))
    window._save_settings()
    assert window.config.mini_window_hotkey == "Ctrl+Shift+F9"


def test_mini_window_reopens_at_last_hidden_position(
    window: MainWindow, application: QApplication
) -> None:
    window.current_record = make_record()
    window.map_country_combo.clear()
    window.selected_country_tag = "ENG"
    window.config.mini_window_pos = ""
    window._mini_toggle_window()
    window.mini_window.move(321, 234)
    application.processEvents()

    window._mini_toggle_window()
    assert not window.mini_window.isVisible()
    assert window.config.mini_window_pos == "321,234"

    window.mini_window.move(0, 0)
    window._mini_toggle_window()
    application.processEvents()
    assert window.mini_window.pos().x() == 321
    assert window.mini_window.pos().y() == 234
