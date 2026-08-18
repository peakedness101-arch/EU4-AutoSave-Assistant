from __future__ import annotations

import re
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path

from .config import PROJECT_ROOT


_TAG_PATTERN = re.compile(r"[A-Z0-9]{3}")


class _CountryTableParser(HTMLParser):
    """Extract TAG-to-Chinese-name rows from the bundled EU4 wiki table."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def _country_table_path() -> Path | None:
    candidates = (
        PROJECT_ROOT / "data" / "country_names.html",
        PROJECT_ROOT / "国家列表.html",
    )
    return next((path for path in candidates if path.is_file()), None)


@lru_cache(maxsize=1)
def country_names() -> dict[str, str]:
    path = _country_table_path()
    if path is None:
        return {}
    parser = _CountryTableParser()
    try:
        parser.feed(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        return {}

    result: dict[str, str] = {}
    for row in parser.rows:
        if len(row) < 4:
            continue
        tag = row[3].strip().upper()
        chinese_name = row[1].strip()
        if _TAG_PATTERN.fullmatch(tag) and chinese_name:
            result[tag] = chinese_name
    return result


def country_name(tag: str | None) -> str:
    normalized = (tag or "").strip().upper()
    return country_names().get(normalized, normalized or "—")


def country_label(tag: str | None) -> str:
    normalized = (tag or "").strip().upper()
    name = country_name(normalized)
    if not normalized or name == normalized:
        return normalized or "—"
    return f"{normalized} · {name}"
