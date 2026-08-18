from __future__ import annotations

import re
from pathlib import Path


_NATIVE_SAVE_NAME = re.compile(r"^c\d{13}\.eu4$", re.IGNORECASE)


def is_managed_autosave(path: str | Path) -> bool:
    name = Path(path).name
    return name.lower() == "mp_autosave.eu4" or _NATIVE_SAVE_NAME.fullmatch(name) is not None


def managed_autosaves(directory: str | Path) -> list[Path]:
    root = Path(directory)
    if not root.is_dir():
        return []
    return [path for path in root.glob("*.eu4") if is_managed_autosave(path)]


def latest_save(directory: str | Path, *, recursive: bool = False) -> Path | None:
    """Return the newest EU4 save in a folder, with deterministic tie-breaking."""
    root = Path(directory)
    if not root.is_dir():
        return None
    candidates: list[tuple[int, str, Path]] = []
    iterator = root.rglob("*.eu4") if recursive else root.glob("*.eu4")
    for path in iterator:
        try:
            candidates.append((path.stat().st_mtime_ns, path.name.casefold(), path))
        except OSError:
            continue
    return max(candidates, default=None, key=lambda item: (item[0], item[1]))[2] if candidates else None
