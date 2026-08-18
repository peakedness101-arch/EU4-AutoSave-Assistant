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
        if (
            len(window.tool_dialogs) != 8
            or window.map_scene is None
            or not window.country_table.isSortingEnabled()
            or window.map_year_badge is None
        ):
            return 2
        from .country_names import country_names

        localized = country_names()
        if len(localized) < 900 or localized.get("FRA") != "法兰西":
            return 4
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
