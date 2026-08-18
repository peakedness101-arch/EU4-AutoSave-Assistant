from __future__ import annotations

import logging
import warnings

from eu4_assistant.diagnostics import (
    CRASH_REPORTS,
    configure_diagnostics,
    diagnostics_directory,
    write_crash_report,
)


def _flush(logger: logging.Logger) -> None:
    for handler in logger.handlers:
        handler.flush()


def test_runtime_log_records_messages_and_python_warnings(tmp_path) -> None:
    log_dir = tmp_path / "logs"
    logger = configure_diagnostics(log_dir)
    logger.info("runtime-log-marker")
    with warnings.catch_warnings():
        warnings.simplefilter("always")
        warnings.warn("warning-log-marker", RuntimeWarning, stacklevel=1)
    _flush(logger)

    content = (log_dir / "assistant.log").read_text(encoding="utf-8")
    assert "runtime-log-marker" in content
    assert "warning-log-marker" in content
    assert diagnostics_directory() == log_dir.resolve()
    fault_content = (log_dir / "native_fault.log").read_text(encoding="utf-8")
    assert "diagnostic session" in fault_content
    assert "platform=" in fault_content


def test_crash_report_contains_context_and_retains_latest_reports(tmp_path) -> None:
    log_dir = tmp_path / "logs"
    for index in range(CRASH_REPORTS + 3):
        write_crash_report(log_dir, f"test-{index}", f"details-{index}")

    reports = sorted(log_dir.glob("crash_*.log"))
    assert len(reports) == CRASH_REPORTS
    content = reports[-1].read_text(encoding="utf-8")
    assert "EU4 AutoSave Assistant crash report" in content
    assert f"category=test-{CRASH_REPORTS + 2}" in content
    assert f"details-{CRASH_REPORTS + 2}" in content
    assert "python=" in content
    assert "platform=" in content
