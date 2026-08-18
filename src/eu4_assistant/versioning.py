from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


SUPPORTED_BUILD_ID = "491d"


@dataclass(slots=True)
class VersionStatus:
    detected_build_id: str | None
    display_version: str | None
    supported: bool
    source: Path | None
    reason: str


def detect_game_version(game_dir: str | Path) -> VersionStatus:
    root = Path(game_dir)
    launcher_settings = root / "launcher-settings.json"
    if not launcher_settings.is_file():
        return VersionStatus(
            None,
            None,
            False,
            None,
            "未找到 launcher-settings.json，无法验证构建标识。",
        )
    try:
        settings = json.loads(launcher_settings.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return VersionStatus(None, None, False, launcher_settings, f"版本信息读取失败：{exc}")

    display = str(settings.get("version") or settings.get("rawVersion") or "")
    match = re.search(r"\(([0-9a-fA-F]{4})\)", display)
    build_id = match.group(1).lower() if match else None
    supported = build_id == SUPPORTED_BUILD_ID
    reason = (
        f"已验证支持的构建标识 {SUPPORTED_BUILD_ID}。"
        if supported
        else f"检测到 {build_id or '未知'}，仅支持 {SUPPORTED_BUILD_ID}。"
    )
    return VersionStatus(build_id, display or None, supported, launcher_settings, reason)

