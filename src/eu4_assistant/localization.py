"""Chinese idea names from the installed translation patch and mod overlays."""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

from .config import PROJECT_ROOT, documents_directory
from .parser import _decode_province_name

_ENTRY = re.compile(rb'(?m)^[ \t]*([A-Za-z0-9_]+):[ \t]*\d*[ \t]*"((?:\\.|[^"\r\n])*)"')
_CJK = re.compile(r"[\u3400-\u9fff]")


def _decode_localisation_value(raw: bytes) -> str:
    # Patch YML wraps the game's escaped CP1252 bytes in UTF-8, whereas saves
    # contain the escaped bytes directly. Recover those bytes before decoding.
    if any(marker in raw for marker in (b"\x10", b"\x11", b"\x12", b"\x13")):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            pass
        else:
            restored = bytearray()
            for char in text:
                try:
                    restored.extend(char.encode("cp1252"))
                except UnicodeEncodeError:
                    if ord(char) <= 255:
                        restored.append(ord(char))
                    else:
                        restored.extend(char.encode("utf-8"))
            raw = bytes(restored)
    return re.sub(r"§[A-Za-z0-9!]", "", _decode_province_name(raw)).strip()


def _enabled_mod_roots() -> tuple[str, ...]:
    eu4_home = documents_directory() / "Paradox Interactive" / "Europa Universalis IV"
    try:
        enabled = json.loads((eu4_home / "dlc_load.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return ()
    roots: list[str] = []
    for relative in enabled.get("enabled_mods", []):
        if not isinstance(relative, str):
            continue
        try:
            descriptor = (eu4_home / relative).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            continue
        match = re.search(r'(?m)^\s*path\s*=\s*"([^"]+)"', descriptor)
        if match:
            root = Path(os.path.expandvars(match.group(1)))
            roots.append(str(root if root.is_absolute() else eu4_home / root))
    return tuple(roots)


def _read_names(root: Path, wanted: set[str]) -> dict[str, str]:
    names: dict[str, str] = {}
    folder = root / "localisation"
    if not folder.is_dir():
        return names
    files = sorted(folder.rglob("*.yml"))
    # Chinese patches normally replace l_english; native Chinese translations
    # take precedence when a mod supplies both formats.
    files.sort(key=lambda path: ("l_english" not in path.name, path.as_posix()))
    for path in files:
        if not any(language in path.name for language in ("l_english", "l_simp_chinese", "l_chinese")):
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        for match in _ENTRY.finditer(data):
            key = match.group(1).decode("ascii")
            if key not in wanted and not key.endswith("_ideas"):
                continue
            value = _decode_localisation_value(match.group(2))
            if _CJK.search(value):
                names[key] = value
    return names


@lru_cache(maxsize=8)
def _idea_names(game_dir: str, mod_dir: str, enabled_roots: tuple[str, ...]) -> dict[str, str]:
    try:
        names = json.loads((PROJECT_ROOT / "data" / "idea_names_zh.json").read_text(encoding="utf-8"))["names"]
    except (OSError, ValueError, KeyError):
        names = {}
    game = Path(game_dir)
    roots = [game, game.parent.parent / "workshop" / "content" / "236850" / "2976470733"]
    roots.extend(Path(root) for root in enabled_roots)
    if mod_dir:
        roots.append(Path(mod_dir))
    wanted = set(names)
    for root in roots:
        for path in (root / "common" / "ideas").glob("*.txt"):
            try:
                data = path.read_bytes()
            except OSError:
                continue
            wanted.update(key.decode("ascii") for key in re.findall(rb"(?m)^[ \t]*([A-Za-z0-9_]+)[ \t]*=[ \t]*\{", data))
    for root in dict.fromkeys(roots):
        names.update(_read_names(root, wanted))
    return names


def idea_group_name(key: str, game_dir: str, mod_dir: str | None = None) -> str:
    return _idea_names(game_dir, mod_dir or "", _enabled_mod_roots()).get(key, key)
