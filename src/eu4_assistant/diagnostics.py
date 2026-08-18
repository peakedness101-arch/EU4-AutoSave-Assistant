from __future__ import annotations

import atexit
import faulthandler
import logging
import platform
import sys
import threading
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType


LOGGER_NAME = "eu4_assistant"
MAX_LOG_BYTES = 5 * 1024 * 1024
LOG_BACKUPS = 5
CRASH_REPORTS = 10
_configured_log_dir: Path | None = None
_qt_message_handler = None
_fault_stream = None


def _system_header() -> str:
    return "\n".join(
        (
            f"timestamp={datetime.now().astimezone().isoformat(timespec='milliseconds')}",
            f"python={sys.version.replace(chr(10), ' ')}",
            f"executable={sys.executable}",
            f"frozen={bool(getattr(sys, 'frozen', False))}",
            f"platform={platform.platform()}",
        )
    )


def write_crash_report(
    log_dir: str | Path,
    category: str,
    details: str,
) -> Path:
    directory = Path(log_dir)
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    destination = directory / f"crash_{timestamp}.log"
    destination.write_text(
        f"EU4 AutoSave Assistant crash report\ncategory={category}\n"
        f"{_system_header()}\n\n{details.rstrip()}\n",
        encoding="utf-8",
        errors="backslashreplace",
    )
    reports = sorted(directory.glob("crash_*.log"), key=lambda item: item.name)
    for stale in reports[:-CRASH_REPORTS]:
        try:
            stale.unlink()
        except OSError:
            pass
    return destination


def _format_exception(
    exception_type: type[BaseException],
    exception: BaseException,
    trace: TracebackType | None,
) -> str:
    return "".join(traceback.format_exception(exception_type, exception, trace))


def _flush_handlers() -> None:
    for handler in logging.getLogger(LOGGER_NAME).handlers:
        try:
            handler.flush()
        except Exception:
            pass


def _close_fault_stream() -> None:
    global _fault_stream
    if _fault_stream is None:
        return
    try:
        if faulthandler.is_enabled():
            faulthandler.disable()
        _fault_stream.flush()
        _fault_stream.close()
    except Exception:
        pass
    _fault_stream = None


def configure_diagnostics(log_dir: str | Path) -> logging.Logger:
    global _configured_log_dir, _fault_stream
    directory = Path(log_dir).resolve()
    logger = logging.getLogger(LOGGER_NAME)
    if _configured_log_dir == directory and logger.handlers:
        return logger
    directory.mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    handler = RotatingFileHandler(
        directory / "assistant.log",
        maxBytes=MAX_LOG_BYTES,
        backupCount=LOG_BACKUPS,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s.%(msecs)03d %(levelname)s %(threadName)s "
            "%(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)
    _configured_log_dir = directory
    logging.captureWarnings(True)
    warning_logger = logging.getLogger("py.warnings")
    warning_logger.setLevel(logging.WARNING)
    warning_logger.propagate = False
    for warning_handler in list(warning_logger.handlers):
        warning_logger.removeHandler(warning_handler)
    warning_logger.addHandler(handler)
    _close_fault_stream()
    fault_path = directory / "native_fault.log"
    if fault_path.exists() and fault_path.stat().st_size > MAX_LOG_BYTES:
        backup = directory / "native_fault.previous.log"
        try:
            fault_path.replace(backup)
        except OSError:
            pass
    try:
        _fault_stream = fault_path.open("ab", buffering=0)
        _fault_stream.write((f"\n--- diagnostic session ---\n{_system_header()}\n").encode("utf-8"))
        faulthandler.enable(file=_fault_stream, all_threads=True)
    except (OSError, RuntimeError) as exc:
        logger.error("无法启用原生故障转储：%s", exc)
        _close_fault_stream()

    def report(
        category: str,
        exception_type: type[BaseException],
        exception: BaseException,
        trace: TracebackType | None,
    ) -> None:
        details = _format_exception(exception_type, exception, trace)
        logger.critical("%s\n%s", category, details)
        try:
            destination = write_crash_report(directory, category, details)
            logger.critical("崩溃报告已写入 %s", destination)
        finally:
            _flush_handlers()

    def main_exception_hook(exception_type, exception, trace) -> None:
        if issubclass(exception_type, KeyboardInterrupt):
            sys.__excepthook__(exception_type, exception, trace)
            return
        report("未捕获的主线程异常", exception_type, exception, trace)

    def thread_exception_hook(args: threading.ExceptHookArgs) -> None:
        report(
            f"未捕获的线程异常：{args.thread.name if args.thread else 'unknown'}",
            args.exc_type,
            args.exc_value,
            args.exc_traceback,
        )

    def unraisable_hook(args) -> None:
        exception = args.exc_value or RuntimeError(args.err_msg or "unraisable exception")
        report("无法上抛的异常", type(exception), exception, args.exc_traceback)

    sys.excepthook = main_exception_hook
    threading.excepthook = thread_exception_hook
    sys.unraisablehook = unraisable_hook
    atexit.register(_flush_handlers)
    atexit.register(_close_fault_stream)
    logger.info("诊断日志已启动\n%s", _system_header())
    return logger


def install_qt_message_logging() -> None:
    global _qt_message_handler
    if _configured_log_dir is None or _qt_message_handler is not None:
        return
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    logger = logging.getLogger(LOGGER_NAME)

    def handler(message_type, context, message) -> None:
        location = ""
        if context is not None and context.file:
            location = f" ({context.file}:{context.line})"
        if message_type == QtMsgType.QtDebugMsg:
            logger.debug("Qt: %s%s", message, location)
        elif message_type == QtMsgType.QtInfoMsg:
            logger.info("Qt: %s%s", message, location)
        elif message_type == QtMsgType.QtWarningMsg:
            logger.warning("Qt: %s%s", message, location)
        else:
            logger.error("Qt: %s%s", message, location)
            if message_type == QtMsgType.QtFatalMsg and _configured_log_dir is not None:
                write_crash_report(_configured_log_dir, "Qt fatal", f"{message}{location}")
                _flush_handlers()

    _qt_message_handler = handler
    qInstallMessageHandler(handler)


def diagnostics_directory() -> Path | None:
    return _configured_log_dir
