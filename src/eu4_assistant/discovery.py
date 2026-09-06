from __future__ import annotations

import os
import re
from collections.abc import Iterable
from pathlib import Path


EU4_STEAM_APP_ID = "236850"
EU4_INSTALL_NAME = "Europa Universalis IV"


def is_eu4_installation(path: str | Path | None) -> bool:
    if not path:
        return False
    root = Path(path)
    return (root / "eu4.exe").is_file() and (root / "launcher-settings.json").is_file()


def _unique_paths(paths: Iterable[str | Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for value in paths:
        if not value:
            continue
        path = Path(value).expanduser()
        key = str(path).replace("/", "\\").rstrip("\\").casefold()
        if key and key not in seen:
            seen.add(key)
            result.append(path)
    return result


def _registry_steam_roots() -> list[Path]:
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []
    candidates: list[Path] = []
    locations = (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Valve\Steam"),
    )
    for hive, key_name in locations:
        try:
            with winreg.OpenKey(hive, key_name) as key:
                for value_name in ("SteamPath", "InstallPath"):
                    try:
                        value, _kind = winreg.QueryValueEx(key, value_name)
                    except OSError:
                        continue
                    if value:
                        candidates.append(Path(os.path.expandvars(str(value))))
        except OSError:
            continue
    return _unique_paths(candidates)


def steam_roots() -> list[Path]:
    candidates: list[str | Path] = []
    for variable in ("STEAM_PATH", "SteamPath"):
        value = os.environ.get(variable)
        if value:
            candidates.append(value)
    candidates.extend(_registry_steam_roots())
    for drive_letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        drive = Path(f"{drive_letter}:\\")
        candidates.extend(
            (
                drive / "Steam",
                drive / "STEAM",
                drive / "Program Files (x86)" / "Steam",
                drive / "Program Files" / "Steam",
            )
        )
    return _unique_paths(candidates)


def _steam_library_roots(roots: Iterable[str | Path]) -> list[Path]:
    libraries: list[Path] = []
    for root in _unique_paths(roots):
        libraries.append(root)
        vdf = root / "steamapps" / "libraryfolders.vdf"
        try:
            content = vdf.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        for raw_path in re.findall(r'"path"\s+"([^"]+)"', content):
            libraries.append(Path(raw_path.replace(r"\\", "\\")))
    return _unique_paths(libraries)


def detect_eu4_installation(
    configured: str | Path | None = None,
    *,
    candidate_steam_roots: Iterable[str | Path] | None = None,
) -> Path | None:
    environment = os.environ.get("EU4_GAME_DIR")
    direct_candidates = _unique_paths((configured or "", environment or ""))
    for candidate in direct_candidates:
        if is_eu4_installation(candidate):
            return candidate.resolve()

    roots = list(candidate_steam_roots) if candidate_steam_roots is not None else steam_roots()
    for library in _steam_library_roots(roots):
        manifest = library / "steamapps" / f"appmanifest_{EU4_STEAM_APP_ID}.acf"
        install_name = EU4_INSTALL_NAME
        try:
            content = manifest.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            content = ""
        match = re.search(r'"installdir"\s+"([^"]+)"', content, re.IGNORECASE)
        if match:
            install_name = match.group(1)
        candidate = library / "steamapps" / "common" / install_name
        if is_eu4_installation(candidate):
            return candidate.resolve()
    return None


def _documents_candidates(preferred: str | Path | None) -> list[Path]:
    candidates: list[str | Path] = []
    if preferred:
        candidates.append(preferred)
    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        candidates.append(Path(user_profile) / "Documents")
    for variable in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        value = os.environ.get(variable)
        if value:
            candidates.append(Path(value) / "Documents")
    candidates.append(Path.home() / "Documents")
    return _unique_paths(candidates)


def detect_eu4_save_directory(
    configured: str | Path | None = None,
    *,
    documents_root: str | Path | None = None,
    candidate_steam_roots: Iterable[str | Path] | None = None,
) -> Path | None:
    if configured and Path(configured).is_dir():
        return Path(configured).resolve()

    expected_documents_paths = [
        root / "Paradox Interactive" / EU4_INSTALL_NAME / "save games"
        for root in _documents_candidates(documents_root)
    ]
    for candidate in expected_documents_paths:
        if candidate.is_dir():
            return candidate.resolve()

    roots = list(candidate_steam_roots) if candidate_steam_roots is not None else steam_roots()
    for root in _unique_paths(roots):
        userdata = root / "userdata"
        if not userdata.is_dir():
            continue
        for account in sorted(userdata.iterdir()):
            candidate = account / EU4_STEAM_APP_ID / "remote" / "save games"
            if candidate.is_dir():
                return candidate.resolve()

    return expected_documents_paths[0] if expected_documents_paths else None
