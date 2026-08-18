from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QToolButton

import eu4_assistant.ui.main_window as main_window_module
from eu4_assistant.mapdata import ProvinceInfo
from eu4_assistant.models import ArmySnapshot, CountrySnapshot, SaveRecord
from eu4_assistant.country_names import country_label
from eu4_assistant.ui.main_window import MainWindow
from eu4_assistant.versioning import VersionStatus


@pytest.fixture(scope="module")
def application() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(application: QApplication, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(MainWindow, "_load_database_index", lambda _self: None)
    monkeypatch.setattr(MainWindow, "_install_save_watcher", lambda _self: None)
    result = MainWindow()
    result.bridge_timer.stop()
    result.show()
    application.processEvents()
    yield result
    result.close()
    application.processEvents()


def test_world_map_is_the_only_main_page(window: MainWindow) -> None:
    assert window.centralWidget().layout().itemAt(0).widget() is window.map_page
    assert not hasattr(window, "tabs")
    assert not hasattr(window, "army_table")
    assert window.left_rail.isVisibleTo(window.map_page)
    assert window.quick_read_button.text() == "⚡ 快速读取最新存档"
    assert [window.left_rail.layout().itemAt(index).widget() for index in range(window.left_rail.layout().count())]
    assert set(window.tool_dialogs) == {
        "countries",
        "country_details",
        "armies",
        "alerts",
        "archive",
        "compare",
        "calculator",
        "settings",
    }
    assert all(not dialog.isModal() for dialog in window.tool_dialogs.values())


def test_left_function_rail_toggles_from_map_button(window: MainWindow) -> None:
    assert not window.left_rail.isHidden()
    QTest.mouseClick(window.left_rail_toggle, Qt.MouseButton.LeftButton)
    assert window.left_rail.isHidden()
    assert window.left_rail_toggle.text() == "☰ 功能栏"
    QTest.mouseClick(window.left_rail_toggle, Qt.MouseButton.LeftButton)
    assert not window.left_rail.isHidden()
    assert window.left_rail_toggle.text() == "隐藏功能栏 ◀"


def test_unsupported_risk_mode_enables_native_controls(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    status = VersionStatus("ffff", "EU4 v1.99.0.0 (ffff)", False, None, "unsupported")
    monkeypatch.setattr(main_window_module, "detect_game_version", lambda _path: status)
    window.config.allow_unsupported_version = True
    window.bridge.allow_unsupported_version = True
    window._refresh_version_status()

    assert window.reconnect_button.isEnabled()
    assert window.schedule_combo.isEnabled()
    assert window.save_now_button.isEnabled()
    assert window.compatibility_risk_banner.isVisible()
    assert "高风险" in window.version_label.text()


def test_province_click_selects_owner_and_opens_local_army_popup(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    country = CountrySnapshot(
        tag="USA",
        player_name="Tester",
        treasury=40,
        monthly_income=100,
        monthly_expense=250,
        religion="protestant",
        primary_culture="american",
        manpower=1.5,
        max_manpower=2.0,
        sailors=850,
        max_sailors=1200,
        ship_count=7,
        income_breakdown={"taxation": 60, "trade": 40},
        mana_spending={
            "adm": {"advance_tech": 300},
            "dip": {"buy_idea": 200},
            "mil": {"develop_prov": 100},
        },
        armies=[
            ArmySnapshot(
                army_id="54:1:1",
                name="First Army",
                location=1,
                regiment_count=12,
                strength=11_500,
                unit_types={"infantry": 10, "cavalry": 2},
            )
        ],
    )
    record = SaveRecord(
        path=Path("synthetic.eu4"),
        fingerprint="synthetic",
        format="plaintext",
        game_date="1767.7.27",
        build_id="491d",
        local_player_tag="USA",
        players=[],
        countries={"USA": country},
        province_owners={1: "USA"},
        province_controllers={1: "FRA"},
    )
    window.current_record = record
    window.provinces = {
        1: ProvinceInfo(1, "Test Province", 10, 20, 30, 100.0, 100.0)
    }
    window.map_country_combo.clear()
    window.map_country_combo.addItem("USA — Tester", "USA")
    monkeypatch.setattr(main_window_module, "province_id_at", lambda *_args: 1)

    window._map_clicked(QPointF(100, 100))

    assert window.selected_country_tag == "USA"
    assert window.sidebar_country.text() == f"{country_label('USA')} · Tester"
    assert "月支出超过月收入两倍" in window.alert_text.toPlainText()
    assert "上月收入 100.00" in window.alert_text.toPlainText()
    assert window.army_popup_widget is not None
    popup_text = "\n".join(
        label.text()
        for label in window.army_popup_widget.findChildren(QLabel)
    )
    assert "Test Province" in popup_text
    assert f"原主 {country_label('USA')}" in popup_text
    assert f"控制方 {country_label('FRA')}" in popup_text
    assert "First Army" in popup_text
    assert "12 团 / 11,500 兵力" in popup_text
    assert window.stat_labels["ideas"].text().startswith("理念")
    assert "上月利息" in window.stat_labels["interest"].text()
    assert "11,500" in window.stat_labels["army"].text()
    assert "11,500 人" in window.stat_labels["army"].text()
    assert "1,500/2,000 人" in window.stat_labels["manpower"].text()
    assert "7 艘" in window.stat_labels["navy"].text()
    assert "850/1,200 人" in window.stat_labels["sailors"].text()

    close_button = next(
        button for button in window.army_popup_widget.findChildren(QToolButton)
        if button.text() == "×"
    )
    QTest.mouseClick(close_button, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert window.army_popup_widget is None


def test_country_table_localizes_year_and_sorts_formatted_numbers(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(window, "_ensure_map_index", lambda: None)

    def country(tag: str, player: str, income: float) -> CountrySnapshot:
        return CountrySnapshot(
            tag=tag,
            player_name=player,
            powers=(int(income), 1, 1),
            technology=(1, 1, 1),
            monthly_income=income,
        )

    record = SaveRecord(
        path=Path("sortable.eu4"),
        fingerprint="sortable",
        format="plaintext",
        game_date="1767.7.27",
        build_id="491d",
        local_player_tag="FRA",
        players=[],
        countries={
            "FRA": country("FRA", "France Player", 9.5),
            "HAB": country("HAB", "Austria Player", 100.0),
            "GBR": country("GBR", "Britain Player", 26.92),
        },
    )

    window._show_record(record)

    assert window.map_year_badge.text() == "当前年份：1767年"
    assert window.country_table.isSortingEnabled()
    assert window.country_table.horizontalHeaderItem(1).text() == "国家"
    localized = {
        window.country_table.item(row, 0).text(): window.country_table.item(row, 1).text()
        for row in range(window.country_table.rowCount())
    }
    assert localized == {"FRA": "法兰西", "GBR": "大不列颠", "HAB": "奥地利"}

    window.country_table.sortItems(5, Qt.SortOrder.AscendingOrder)
    assert [
        window.country_table.item(row, 0).text()
        for row in range(window.country_table.rowCount())
    ] == ["FRA", "GBR", "HAB"]
    window.country_table.sortItems(5, Qt.SortOrder.DescendingOrder)
    assert [
        window.country_table.item(row, 0).text()
        for row in range(window.country_table.rowCount())
    ] == ["HAB", "GBR", "FRA"]


def test_settings_no_longer_reserves_chinese_mod_directory(window: MainWindow) -> None:
    assert not hasattr(window, "chinese_mod_edit")
    settings_text = "\n".join(
        label.text() for label in window.tool_dialogs["settings"].findChildren(QLabel)
    )
    assert "联机中文补丁" not in settings_text


def test_country_overview_groups_related_information(window: MainWindow) -> None:
    assert window.stat_positions == {
        "treasury": (0, 0, 1),
        "expense": (0, 1, 1),
        "income": (1, 0, 1),
        "interest": (1, 1, 1),
        "technology": (2, 0, 1),
        "ideas": (2, 1, 1),
        "powers": (3, 0, 2),
        "development": (4, 0, 1),
        "stability": (4, 1, 1),
        "army": (5, 0, 1),
        "manpower": (5, 1, 1),
        "navy": (6, 0, 1),
        "sailors": (6, 1, 1),
    }


def test_multi_save_breakdown_renders_after_loading(window: MainWindow) -> None:
    def record(game_date: str, amount: int) -> SaveRecord:
        country = CountrySnapshot(
            tag="ENG",
            mana_spending={"adm": {"advance_tech": amount, "buy_idea": 10}},
            income_breakdown={"trade": amount / 2},
            expense_breakdown={"army_maintenance": amount / 4},
        )
        return SaveRecord(
            path=Path(f"{game_date}.eu4"),
            fingerprint=game_date,
            format="plaintext",
            game_date=game_date,
            build_id="491d",
            local_player_tag="ENG",
            players=[],
            countries={"ENG": country},
            game_version="1.37.5.0",
        )

    window._comparison_ready([record("1500.1.1", 100), record("1501.1.1", 200)])
    window.compare_metric.setCurrentIndex(window.compare_metric.findData("mana_total:adm"))
    window._render_comparison()

    assert window.compare_tag.currentText() == "ENG"
    assert window.chart.series()[0].count() == 2
    assert window.compare_breakdown_table.rowCount() == 2
    assert window.compare_breakdown_table.item(1, 1).text() == "210"
    assert window.compare_breakdown_table.item(1, 6).text() == "100.00"


def test_player_alert_overview_lists_only_warned_players(window: MainWindow) -> None:
    safe = CountrySnapshot(tag="ENG", player_name="Alice", monthly_income=100)
    warned = CountrySnapshot(
        tag="FRA",
        player_name="Bob",
        monthly_income=100,
        monthly_expense=250,
    )
    window.current_record = SaveRecord(
        path=Path("alerts.eu4"),
        fingerprint="alerts",
        format="plaintext",
        game_date="1500.1.1",
        build_id="491d",
        local_player_tag="ENG",
        players=[],
        countries={"ENG": safe, "FRA": warned},
    )
    window.map_country_combo.clear()
    window.map_country_combo.addItem("ENG — Alice", "ENG")
    window.map_country_combo.addItem("FRA — Bob", "FRA")
    window._refresh_player_alert_overview()

    assert window.alert_overview_table.rowCount() == 1
    assert window.alert_overview_table.item(0, 1).text() == "FRA"
    assert window.alert_overview_table.item(0, 2).text() == "Bob"
    assert "1 / 2" in window.alert_overview_summary.text()
    assert window.left_tool_buttons["alerts"].text() == "玩家警告总览（1）"


def test_verified_save_is_parsed_even_when_auto_archive_is_off(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_path = Path("verified.eu4")
    monkeypatch.setattr(
        window.bridge,
        "request_save_and_wait",
        lambda _directory: {
            "ok": True,
            "file_created": True,
            "save_path": str(save_path),
            "message": "verified",
        },
    )
    imported: list[Path] = []
    monkeypatch.setattr(window, "_import_verified_save", lambda path: imported.append(Path(path)))

    def run_synchronously(function, on_result, *args, on_error=None, on_finished=None, **kwargs):
        try:
            on_result(function(*args, **kwargs))
        except Exception as exc:  # pragma: no cover - diagnostic fallback
            if on_error:
                on_error(str(exc))
        finally:
            if on_finished:
                on_finished()

    monkeypatch.setattr(window, "_run_worker", run_synchronously)
    window.auto_archive_checkbox.setChecked(False)
    window._request_native_save()

    assert imported == [save_path]
