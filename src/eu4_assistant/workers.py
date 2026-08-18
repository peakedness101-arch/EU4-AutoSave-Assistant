from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


LOGGER = logging.getLogger("eu4_assistant.worker")


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(str)
    finished = Signal()


class FunctionWorker(QRunnable):
    def __init__(self, function: Callable[..., Any], *args: Any, **kwargs: Any):
        super().__init__()
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.function(*self.args, **self.kwargs)
        except Exception:
            details = traceback.format_exc()
            LOGGER.error("后台任务执行失败：%r\n%s", self.function, details)
            self.signals.error.emit(details)
        else:
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()
