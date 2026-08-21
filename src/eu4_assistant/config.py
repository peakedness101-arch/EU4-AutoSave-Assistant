from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path


def _resolve_project_root() -> Path:
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parents[2]
    configured_home = os.environ.get("EU4_AUTOSAVE_HOME")
    if configured_home:
        return Path(configured_home).resolve()
    return Path(sys.executable).resolve().parent


PROJECT_ROOT = _resolve_project_root()


def documents_directory() -> Path:
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            ) as key:
                value, _kind = winreg.QueryValueEx(key, "Personal")
            expanded = os.path.expandvars(str(value))
            if expanded:
                return Path(expanded)
        except (OSError, ValueError):
            pass
    return Path.home() / "Documents"


def default_game_directory() -> str:
    """Find a local EU4 install without embedding a developer machine path."""
    configured = os.environ.get("EU4_GAME_DIR")
    if configured:
        return str(Path(configured).expanduser())

    steam_roots: list[Path] = []
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"
            ) as key:
                value, _kind = winreg.QueryValueEx(key, "SteamPath")
            if value:
                steam_roots.append(Path(str(value)))
        except (OSError, ValueError):
            pass
        program_files = os.environ.get("ProgramFiles(x86)")
        if program_files:
            steam_roots.append(Path(program_files) / "Steam")

    for steam_root in steam_roots:
        candidate = (
            steam_root / "steamapps" / "common" / "Europa Universalis IV"
        )
        if (candidate / "eu4.exe").is_file():
            return str(candidate)
    return ""


@dataclass(slots=True)
class AppConfig:
    game_dir: str = field(default_factory=default_game_directory)
    save_dir: str = str(
        documents_directory()
        / "Paradox Interactive"
        / "Europa Universalis IV"
        / "save games"
    )
    archive_dir: str = str(PROJECT_ROOT / "archives")
    database_path: str = str(PROJECT_ROOT / "data" / "assistant.sqlite3")
    campaign_name: str = "默认战役"
    autosave_mode: str = "quarterly"
    allow_unsupported_version: bool = False
    archive_cleanup_enabled: bool = True
    mod_mode_enabled: bool = False
    mod_dir: str = ""
    mini_window_hotkey: str = "Ctrl+Shift+F9"
    mini_window_lock_hotkey: str = "Ctrl+Shift+F10"
    mini_window_pos: str = ""
    setup_confirmed: bool = False


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or PROJECT_ROOT / "config" / "settings.json"
    if not config_path.exists():
        return AppConfig()
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    # Ctrl+Alt+L is commonly reserved by other desktop software. Migrate only
    # the former built-in default; all other custom sequences remain intact.
    if raw.get("mini_window_lock_hotkey") == "Ctrl+Alt+L":
        raw["mini_window_lock_hotkey"] = "Ctrl+Shift+F10"
    # A settings file created by an older release represents an existing user,
    # so the new first-run dialog must not appear after every upgrade.
    if "setup_confirmed" not in raw:
        raw["setup_confirmed"] = True
    allowed = AppConfig.__dataclass_fields__
    return AppConfig(**{key: value for key, value in raw.items() if key in allowed})


def save_config(config: AppConfig, path: Path | None = None) -> None:
    config_path = path or PROJECT_ROOT / "config" / "settings.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = config_path.with_suffix(".json.partial")
    temporary.write_text(
        json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(config_path)
