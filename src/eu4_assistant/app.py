from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from .config import PROJECT_ROOT
from .diagnostics import configure_diagnostics, install_qt_message_logging


def main() -> int:
    logger = configure_diagnostics(PROJECT_ROOT / "logs")
    install_qt_message_logging()
    logger.info("正在启动 EU4 联机自动存档与分析助手，参数=%s", sys.argv[1:])
    from .ui.main_window import MainWindow

    application = QApplication(sys.argv)
    application.setApplicationName("EU4 联机自动存档与分析助手")
    application.setFont(QFont("Microsoft YaHei UI", 9))
    window = MainWindow()
    if "--smoke-test" in sys.argv:
        if len(window.tool_dialogs) != 9 or window.map_scene is None:
            return 2
        # Exercise the timetable compiled into the executable, using temporary
        # data so a release smoke check never writes the user's personal memos.
        from tempfile import TemporaryDirectory
        from .timetable import TimetableStore, read_timetable
        from .ui.timetable import TimetablePanel

        with TemporaryDirectory(prefix="eu4_timetable_smoke_") as temporary:
            store = TimetableStore(Path(temporary) / "timetable.json")
            panel = TimetablePanel(store)
            panel.year.setValue(1500)
            panel.month.setValue(6)
            panel.day.setValue(15)
            panel.note.setPlainText("时间表发布包检查\n保留多行注意事项")
            panel.new_button.click()
            if panel.table.rowCount() != 1 or panel.note.toPlainText() != "时间表发布包检查\n保留多行注意事项":
                return 4
            for spin, buttons in zip([panel.year, panel.month, panel.day], panel.date_steppers):
                before = spin.value()
                buttons.up.click()
                if spin.value() != before + 1:
                    return 5
                buttons.down.click()
                if spin.value() != before:
                    return 5
            panel.save_button.click()
            if len(store.entries) != 1 or read_timetable(store.path) != store.entries:
                return 6
            panel.close()
        logger.info("时间表发布包功能检查通过：新增、注意事项带入、六个日期按钮、保存")
        configured_game = window.config.game_dir
        if (Path(configured_game) / "map" / "provinces.bmp").is_file():
            from .mapdata import build_political_map

            rendered = build_political_map(
                configured_game,
                {},
                cache_dir=PROJECT_ROOT / "data" / "map_cache",
            )
            if rendered.width < 1000 or rendered.height < 500:
                return 3
        window.close()
        logger.info("发行版冒烟测试通过")
        return 0
    window.show()
    exit_code = application.exec()
    logger.info("程序正常退出，代码=%s", exit_code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
