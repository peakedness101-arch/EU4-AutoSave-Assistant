from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea, QToolButton

import eu4_assistant.ui.main_window as main_window_module
from eu4_assistant.config import AppConfig
from eu4_assistant.mapdata import ProvinceInfo
from eu4_assistant.models import ArmySnapshot, CountrySnapshot, SaveRecord
from eu4_assistant.ui.main_window import MainWindow
from eu4_assistant.ui.assets import country_flag_pixmap, country_shield_pixmap
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
    assert window.sidebar_country.text() == "USA · Tester"
    assert "月支出超过月收入两倍" in window.alert_text.toPlainText()
    assert "上月收入 100.00" in window.alert_text.toPlainText()
    assert window.army_popup_widget is not None
    popup_text = "\n".join(
        label.text()
        for label in window.army_popup_widget.findChildren(QLabel)
    )
    assert "Test Province" in popup_text
    assert "原主 USA · 控制方 FRA" in popup_text
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


def test_settings_no_longer_reserves_chinese_mod_directory(window: MainWindow) -> None:
    assert not hasattr(window, "chinese_mod_edit")
    settings_text = "\n".join(
        label.text() for label in window.tool_dialogs["settings"].findChildren(QLabel)
    )
    assert "联机中文补丁" not in settings_text


def test_settings_exposes_optional_generic_mod_root(window: MainWindow) -> None:
    assert not window.mod_mode_checkbox.isChecked()
    assert not window.mod_dir_edit.isEnabled()
    window.mod_mode_checkbox.setChecked(True)
    assert window.mod_dir_edit.isEnabled()


def test_first_run_opens_settings_until_user_confirms(
    application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = AppConfig(
        database_path=str(tmp_path / "assistant.sqlite3"),
        setup_confirmed=False,
    )
    monkeypatch.setattr(main_window_module, "load_config", lambda: config)
    monkeypatch.setattr(MainWindow, "_load_database_index", lambda _self: None)
    monkeypatch.setattr(MainWindow, "_install_save_watcher", lambda _self: None)
    first_run_window = MainWindow()
    first_run_window.bridge_timer.stop()
    first_run_window.show()
    QApplication.processEvents()

    settings = first_run_window.tool_dialogs["settings"]
    assert settings.isVisible()
    assert first_run_window.first_run_settings_notice.isVisible()
    assert "首次使用" in first_run_window.first_run_settings_notice.text()

    first_run_window.close()
    QApplication.processEvents()


def test_map_uses_one_dominant_shield_per_occupied_province(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    england = CountrySnapshot(
        tag="ENG",
        armies=[
            ArmySnapshot("e1", "English One", 1, 4, 4_000),
            ArmySnapshot("e2", "English Two", 1, 3, 3_000),
        ],
    )
    france = CountrySnapshot(
        tag="FRA", armies=[ArmySnapshot("f1", "French Army", 1, 10, 6_500)]
    )
    window.current_record = SaveRecord(
        path=Path("armies.eu4"),
        fingerprint="armies",
        format="plaintext",
        game_date="1500.1.1",
        build_id="491d",
        local_player_tag="ENG",
        players=[],
        countries={"ENG": england, "FRA": france},
        province_owners={1: "ENG"},
    )
    window.provinces = {
        1: ProvinceInfo(1, "London", 10, 20, 30, 50.0, 50.0)
    }
    monkeypatch.setattr(
        main_window_module, "load_country_colors", lambda *_args: {"ENG": (1, 2, 3)}
    )

    def fake_shield(_game, _tag, size, **_kwargs) -> QPixmap:
        pixmap = QPixmap(*size)
        pixmap.fill(QColor("white"))
        return pixmap

    monkeypatch.setattr(main_window_module, "country_shield_pixmap", fake_shield)
    window._political_map_ready(Image.new("RGB", (100, 100)))

    assert len(window.army_dot_items) == 1
    assert len(window.army_shield_items) == 1
    assert window.army_dot_items[0].data(0) == 1
    assert "主盾徽：ENG" in window.army_shield_items[0].toolTip()
    label_texts = {
        child.text()
        for child in window.army_shield_items[0].childItems()
        if hasattr(child, "text")
    }
    assert "7k" in label_texts
    window._update_army_marker_visibility(0.84)
    assert window.army_dot_items[0].isVisible()
    assert not window.army_shield_items[0].isVisible()
    window._update_army_marker_visibility(0.85)
    assert not window.army_dot_items[0].isVisible()
    assert window.army_shield_items[0].isVisible()
    window.map_country_combo.clear()
    window.map_country_combo.addItem("ENG", "ENG")
    click_position = window.map_view.mapFromScene(QPointF(50.0, 50.0))
    QTest.mouseClick(
        window.map_view.viewport(), Qt.MouseButton.LeftButton, pos=click_position
    )
    QApplication.processEvents()
    assert window.army_popup_widget is not None
    popup_text = "\n".join(
        label.text() for label in window.army_popup_widget.findChildren(QLabel)
    )
    assert "English One" in popup_text
    assert "French Army" in popup_text


def test_crowded_province_click_keeps_map_view_and_bounds_army_popup(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    armies = [
        ArmySnapshot(
            f"army-{index}",
            f"Crowded Army {index}",
            1,
            10,
            10_000,
        )
        for index in range(80)
    ]
    window.current_record = SaveRecord(
        path=Path("crowded.eu4"),
        fingerprint="crowded",
        format="plaintext",
        game_date="1500.1.1",
        build_id="491d",
        local_player_tag="ENG",
        players=[],
        countries={"ENG": CountrySnapshot(tag="ENG", armies=armies)},
        province_owners={1: "ENG"},
    )
    window.provinces = {
        1: ProvinceInfo(1, "London", 10, 20, 30, 50.0, 50.0)
    }
    window.map_country_combo.clear()
    window.map_country_combo.addItem("ENG", "ENG")
    window.map_scene.clear()
    window.map_scene.addRect(0, 0, 1_000, 500)
    window.map_view.resetTransform()
    window.map_view.scale(1.75, 1.75)
    window.map_view.centerOn(QPointF(420.0, 210.0))
    QApplication.processEvents()
    scale_before = window.map_view.transform().m11()
    center_before = window.map_view.mapToScene(
        window.map_view.viewport().rect().center()
    )
    monkeypatch.setattr(main_window_module, "province_id_at", lambda *_args: 1)

    window._map_clicked(QPointF(420.0, 210.0))
    QApplication.processEvents()

    center_after = window.map_view.mapToScene(
        window.map_view.viewport().rect().center()
    )
    assert window.map_view.transform().m11() == pytest.approx(scale_before)
    assert center_after.x() == pytest.approx(center_before.x(), abs=1.0)
    assert center_after.y() == pytest.approx(center_before.y(), abs=1.0)
    assert window.army_popup_widget is not None
    assert window.army_popup_widget.height() <= window.map_view.viewport().height() - 12
    scroll = window.army_popup_widget.findChild(QScrollArea, "armyPopupScroll")
    assert scroll is not None
    assert scroll.verticalScrollBar().maximum() > 0


def test_ocean_click_keeps_map_scene_and_view_unchanged(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    window.current_record = SaveRecord(
        path=Path("ocean.eu4"),
        fingerprint="ocean",
        format="plaintext",
        game_date="1500.1.1",
        build_id="491d",
        local_player_tag="ENG",
        players=[],
        countries={"ENG": CountrySnapshot(tag="ENG")},
        province_owners={1: "ENG"},
    )
    monkeypatch.setattr(main_window_module, "load_country_colors", lambda *_args: {})
    window._political_map_ready(Image.new("RGB", (1_000, 500), (42, 82, 104)))
    assert window.map_pixmap_item is not None
    window.map_view.resetTransform()
    window.map_view.scale(1.6, 1.6)
    window.map_view.centerOn(QPointF(430.0, 220.0))
    QApplication.processEvents()
    item_count = len(window.map_scene.items())
    scale_before = window.map_view.transform().m11()
    horizontal_before = window.map_view.horizontalScrollBar().value()
    vertical_before = window.map_view.verticalScrollBar().value()
    activations: list[int] = []
    monkeypatch.setattr(main_window_module, "province_id_at", lambda *_args: 3)
    monkeypatch.setattr(main_window_module, "load_water_provinces", lambda *_args: {3})
    monkeypatch.setattr(
        window,
        "_activate_province",
        lambda province_id, _position: activations.append(province_id),
    )

    # Exercise the ocean branch directly. Qt's offscreen platform can corrupt
    # its native backing store when QTest synthesizes a viewport click over a
    # large QGraphicsPixmapItem during interpreter shutdown on Windows.
    window._map_clicked(
        window.map_view.mapToScene(window.map_view.viewport().rect().center())
    )
    QApplication.processEvents()

    assert activations == []
    assert len(window.map_scene.items()) == item_count
    assert window.map_pixmap_item in window.map_scene.items()
    assert window.map_view.transform().m11() == pytest.approx(scale_before)
    assert window.map_view.horizontalScrollBar().value() == horizontal_before
    assert window.map_view.verticalScrollBar().value() == vertical_before


def test_shields_are_deferred_until_zoomed_and_reused_on_refresh(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    window.current_record = SaveRecord(
        path=Path("lazy.eu4"),
        fingerprint="lazy",
        format="plaintext",
        game_date="1500.1.1",
        build_id="491d",
        local_player_tag="ENG",
        players=[],
        countries={
            "ENG": CountrySnapshot(
                tag="ENG", armies=[ArmySnapshot("e1", "Army", 1, 4, 4_000)]
            )
        },
        province_owners={1: "ENG"},
    )
    window.provinces = {
        1: ProvinceInfo(1, "London", 10, 20, 30, 50.0, 50.0)
    }
    monkeypatch.setattr(
        main_window_module, "load_country_colors", lambda *_args: {"ENG": (1, 2, 3)}
    )
    compose_calls: list[str] = []

    def fake_shield(_game, tag, size, **_kwargs) -> QPixmap:
        compose_calls.append(tag)
        pixmap = QPixmap(*size)
        pixmap.fill(QColor("white"))
        return pixmap

    monkeypatch.setattr(main_window_module, "country_shield_pixmap", fake_shield)
    monkeypatch.setattr(
        window, "_fill_map_view", lambda: window._update_army_marker_visibility(0.4)
    )

    window._political_map_ready(Image.new("RGB", (100, 100)))
    QApplication.processEvents()
    assert compose_calls == []
    assert len(window.army_dot_items) == 1
    assert window.army_shield_items == []

    window._update_army_marker_visibility(0.85)
    assert compose_calls == ["ENG"]
    assert len(window.army_shield_items) == 1

    window._political_map_ready(Image.new("RGB", (100, 100)))
    window._update_army_marker_visibility(0.85)
    assert compose_calls == ["ENG"]


def test_country_flag_prefers_mod_file(
    application: QApplication, tmp_path: Path
) -> None:
    game = tmp_path / "game"
    mod = tmp_path / "mod"
    (game / "gfx" / "flags").mkdir(parents=True)
    (mod / "gfx" / "flags").mkdir(parents=True)
    Image.new("RGBA", (8, 8), (255, 0, 0, 255)).save(
        game / "gfx" / "flags" / "ENG.tga"
    )
    Image.new("RGBA", (8, 8), (0, 0, 255, 255)).save(
        mod / "gfx" / "flags" / "ENG.tga"
    )

    vanilla = country_flag_pixmap(game, "ENG", (8, 8))
    overlaid = country_flag_pixmap(game, "ENG", (8, 8), mod_dir=mod)

    assert vanilla.toImage().pixelColor(4, 4).red() == 255
    assert overlaid.toImage().pixelColor(4, 4).blue() == 255


def test_country_shield_clips_flag_inside_frame_canvas(
    application: QApplication, tmp_path: Path
) -> None:
    game = tmp_path / "game"
    flags = game / "gfx" / "flags"
    interface = game / "gfx" / "interface"
    flags.mkdir(parents=True)
    interface.mkdir(parents=True)
    Image.new("RGBA", (32, 32), (245, 190, 0, 255)).save(flags / "TST.tga")
    Image.new("RGBA", (40, 40), (0, 0, 0, 255)).save(
        interface / "shield_medium_mask.tga"
    )
    Image.new("RGBA", (64, 64), (0, 0, 0, 0)).save(
        interface / "shield_medium_overlay.dds"
    )

    shield = country_shield_pixmap(game, "TST", (64, 64)).toImage()

    assert shield.pixelColor(32, 32).alpha() == 255
    assert all(shield.pixelColor(0, y).alpha() == 0 for y in range(64))
    assert all(shield.pixelColor(63, y).alpha() == 0 for y in range(64))
    assert all(shield.pixelColor(x, 0).alpha() == 0 for x in range(64))
    assert all(shield.pixelColor(x, 63).alpha() == 0 for x in range(64))


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
