"""Keep UI regression tests away from the user's configuration and database."""
from dataclasses import replace
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session", autouse=True)
def qt_application_lifetime():
    # All module fixtures must share a live QApplication until UI objects die.
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    import gc

    app = QApplication.instance() or QApplication([])
    yield app
    for widget in app.topLevelWidgets():
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()
    app.processEvents()


@pytest.fixture(autouse=True)
def isolate_ui_runtime(monkeypatch, tmp_path):
    import eu4_assistant.ui.main_window as module

    original = module.load_config
    saves = tmp_path / "ui_saves"
    saves.mkdir()
    monkeypatch.setattr(module, "load_config", lambda: replace(
        original(), database_path=str(tmp_path / "ui.sqlite3"),
        archive_dir=str(tmp_path / "ui_archives"), save_dir=str(saves),
        archive_cleanup_enabled=False, setup_confirmed=True,
    ))
    monkeypatch.setattr(module, "save_config", lambda _config: None)
