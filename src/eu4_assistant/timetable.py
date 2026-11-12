"""Portable memos and date arithmetic for EU4's fixed 365-day calendar."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
import tempfile
import os

MONTH_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


@dataclass(frozen=True, order=True)
class GameDate:
    year: int
    month: int
    day: int

    def __post_init__(self) -> None:
        if not (1 <= self.year <= 20000 and 1 <= self.month <= 12):
            raise ValueError("日期年份须为 1～20000，月份须为 1～12。")
        if not 1 <= self.day <= MONTH_DAYS[self.month - 1]:
            raise ValueError("无效游戏日期：EU4 二月固定 28 天，请检查月份和日数。")

    def __str__(self) -> str:
        return f"{self.year:04d}.{self.month:02d}.{self.day:02d}"


def parse_game_date(value: str) -> GameDate:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,5}\.[0-9]{1,2}\.[0-9]{1,2}", value):
        raise ValueError("日期格式应为 年.月.日，例如 1500.06.15。")
    return GameDate(*(int(part) for part in value.split(".")))


def shift_months(value: GameDate, months: int) -> GameDate:
    index = (value.year - 1) * 12 + value.month - 1 + months
    if index < 0:
        return GameDate(1, 1, 1)
    if index >= 20000 * 12:
        return GameDate(20000, 12, 31)
    year, month = divmod(index, 12)
    return GameDate(year + 1, month + 1, min(value.day, MONTH_DAYS[month]))


@dataclass(frozen=True)
class TimetableEntry:
    date: GameDate
    note: str

    def __post_init__(self) -> None:
        if not isinstance(self.date, GameDate):
            raise ValueError("事项日期无效。")
        if not isinstance(self.note, str) or not self.note.strip():
            raise ValueError("注意事项不能为空。")


def due_entries(entries: list[TimetableEntry], date: GameDate | None) -> list[TimetableEntry]:
    if date is None:
        return []
    return sorted(
        (entry for entry in entries if shift_months(entry.date, -3) <= date <= shift_months(entry.date, 3)),
        key=lambda entry: entry.date,
    )


def read_timetable(path: Path) -> list[TimetableEntry]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"时间表不是有效的 UTF-8 JSON：{exc}") from exc
    if not isinstance(raw, dict) or type(raw.get("format_version")) is not int or raw["format_version"] != 1:
        raise ValueError("不支持的时间表格式；format_version 必须为 1。")
    if not isinstance(raw.get("items"), list):
        raise ValueError("时间表 items 必须为列表。")
    result = []
    for index, item in enumerate(raw["items"], 1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 条事项必须为对象。")
        try:
            result.append(TimetableEntry(parse_game_date(item.get("date")), item.get("note")))
        except ValueError as exc:
            raise ValueError(f"第 {index} 条事项：{exc}") from exc
    return result


def write_timetable(path: Path, entries: list[TimetableEntry]) -> None:
    payload = {"format_version": 1, "items": [{"date": str(entry.date), "note": entry.note} for entry in entries]}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, suffix=".partial", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class TimetableStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.entries: list[TimetableEntry] = []
        self.load_error: str | None = None
        if self.path.exists():
            try:
                self.entries = read_timetable(self.path)
            except (OSError, ValueError) as exc:
                self.load_error = str(exc)

    def save(self, entries: list[TimetableEntry]) -> None:
        if self.load_error:
            raise ValueError("原时间表读取失败，已保留原文件；请通过导入恢复，不会自动覆盖。")
        write_timetable(self.path, entries)
        self.entries = list(entries)

    def replace(self, entries: list[TimetableEntry]) -> Path | None:
        backup = None
        if self.path.exists():
            directory = self.path.parent / "timetable_backups"
            directory.mkdir(parents=True, exist_ok=True)
            backup = directory / f"before_import_{datetime.now():%Y%m%d_%H%M%S_%f}.json"
            shutil.copy2(self.path, backup)
            if backup.read_bytes() != self.path.read_bytes():
                raise OSError("时间表备份校验失败，未替换原时间表。")
        write_timetable(self.path, entries)
        self.entries = list(entries)
        self.load_error = None
        return backup
