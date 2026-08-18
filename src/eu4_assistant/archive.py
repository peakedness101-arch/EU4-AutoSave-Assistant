from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .parser import parse_save


@dataclass(slots=True)
class ArchiveResult:
    source: str
    destination: str
    fingerprint: str
    game_date: str
    moved_at: str


@dataclass(slots=True)
class UndoResult:
    restored_source: str
    removed_archive: str
    restored_at: str


@dataclass(slots=True)
class ArchiveBatchItem:
    source: str
    result: ArchiveResult | None = None
    error: str | None = None


def _safe_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    return cleaned or "未命名战役"


def wait_for_stable_file(
    path: str | Path,
    checks: int = 3,
    interval_seconds: float = 0.5,
    timeout_seconds: float = 120.0,
) -> None:
    file_path = Path(path)
    deadline = time.monotonic() + timeout_seconds
    previous: tuple[int, int] | None = None
    stable = 0
    while stable < checks:
        stat = file_path.stat()
        current = (stat.st_size, stat.st_mtime_ns)
        if current == previous and stat.st_size > 0:
            stable += 1
        else:
            stable = 0
            previous = current
        remaining = deadline - time.monotonic()
        if stable < checks and remaining <= 0:
            raise TimeoutError(f"等待存档稳定超时：{file_path}")
        if stable < checks:
            time.sleep(min(interval_seconds, remaining))


def preview_archive_path(
    source: str | Path,
    archive_root: str | Path,
    campaign_name: str,
    game_date: str,
    local_tag: str | None,
    captured_at: datetime | None = None,
) -> Path:
    timestamp = (captured_at or datetime.now()).strftime("%Y%m%d-%H%M%S")
    date_part = game_date.replace(".", "-")
    tag = local_tag or "---"
    folder = Path(archive_root) / _safe_name(campaign_name)
    stem = f"{timestamp}__{date_part}__{tag}"
    sequence = 1
    while True:
        candidate = folder / f"{stem}__{sequence:04d}.eu4"
        if not candidate.exists() and not candidate.with_suffix(candidate.suffix + ".partial").exists():
            return candidate
        sequence += 1


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def archive_save(
    source: str | Path,
    archive_root: str | Path,
    campaign_name: str,
    *,
    remove_source: bool = True,
    wait_until_stable: bool = True,
) -> ArchiveResult:
    source_path = Path(source).resolve()
    if wait_until_stable:
        wait_for_stable_file(source_path)
    record = parse_save(source_path)
    destination = preview_archive_path(
        source_path,
        archive_root,
        campaign_name,
        record.game_date,
        record.local_player_tag,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".partial")
    shutil.copy2(source_path, partial)
    source_hash = _sha256(source_path)
    copied_hash = _sha256(partial)
    if source_hash != copied_hash:
        partial.unlink(missing_ok=True)
        raise IOError("归档副本校验失败；源文件已保留。")
    os.replace(partial, destination)
    if remove_source:
        source_path.unlink()

    result = ArchiveResult(
        source=str(source_path),
        destination=str(destination),
        fingerprint=source_hash,
        game_date=record.game_date,
        moved_at=datetime.now().isoformat(timespec="seconds"),
    )
    manifest = Path(archive_root) / "archive_manifest.jsonl"
    with manifest.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")
    return result


def archive_many(
    sources: list[str | Path],
    archive_root: str | Path,
    campaign_name: str,
    *,
    remove_source: bool = True,
    wait_until_stable: bool = True,
) -> list[ArchiveBatchItem]:
    items: list[ArchiveBatchItem] = []
    for source in sources:
        try:
            result = archive_save(
                source,
                archive_root,
                campaign_name,
                remove_source=remove_source,
                wait_until_stable=wait_until_stable,
            )
        except Exception as exc:
            items.append(ArchiveBatchItem(str(source), error=str(exc)))
        else:
            items.append(ArchiveBatchItem(str(source), result=result))
    return items


def undo_last_archive(archive_root: str | Path) -> UndoResult:
    root = Path(archive_root)
    manifest = root / "archive_manifest.jsonl"
    if not manifest.is_file():
        raise FileNotFoundError("没有可撤销的归档记录。")
    lines = [line for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise ValueError("归档清单为空。")
    entry = json.loads(lines[-1])
    source = Path(entry["source"])
    destination = Path(entry["destination"])
    if source.exists():
        raise FileExistsError(f"源位置已经存在文件，拒绝覆盖：{source}")
    if not destination.is_file():
        raise FileNotFoundError(f"归档文件不存在：{destination}")
    if _sha256(destination) != entry["fingerprint"]:
        raise IOError("归档文件内容已变化，拒绝撤销。")
    source.parent.mkdir(parents=True, exist_ok=True)
    partial = source.with_suffix(source.suffix + ".restore.partial")
    shutil.copy2(destination, partial)
    if _sha256(partial) != entry["fingerprint"]:
        partial.unlink(missing_ok=True)
        raise IOError("恢复副本校验失败，归档文件已保留。")
    os.replace(partial, source)
    destination.unlink()
    undo = UndoResult(
        restored_source=str(source),
        removed_archive=str(destination),
        restored_at=datetime.now().isoformat(timespec="seconds"),
    )
    undo_manifest = root / "archive_undo_manifest.jsonl"
    with undo_manifest.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(asdict(undo), ensure_ascii=False) + "\n")
    manifest.write_text("\n".join(lines[:-1]) + ("\n" if len(lines) > 1 else ""), encoding="utf-8")
    return undo
