from __future__ import annotations

import csv
import colorsys
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from .resources import GameResourceResolver
from .versioning import detect_game_version


MAP_CACHE_VERSION = 1


@dataclass(slots=True)
class ProvinceInfo:
    province_id: int
    name: str
    red: int
    green: int
    blue: int
    center_x: float | None = None
    center_y: float | None = None


def _read_definitions(path: Path) -> dict[int, ProvinceInfo]:
    provinces: dict[int, ProvinceInfo] = {}
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as stream:
        reader = csv.reader(stream, delimiter=";")
        for row in reader:
            if len(row) < 5 or not row[0].isdigit():
                continue
            province_id = int(row[0])
            if province_id <= 0:
                continue
            provinces[province_id] = ProvinceInfo(
                province_id=province_id,
                red=int(row[1]),
                green=int(row[2]),
                blue=int(row[3]),
                name=row[4] or f"Province {province_id}",
            )
    return provinces


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_province_index(
    game_dir: str | Path,
    cache_path: str | Path,
    *,
    mod_dir: str | Path | None = None,
) -> dict[int, ProvinceInfo]:
    resources = GameResourceResolver.create(game_dir, mod_dir)
    definitions = resources.resolve_file("map/definition.csv")
    province_map = resources.resolve_file("map/provinces.bmp")
    if not definitions.is_file() or not province_map.is_file():
        raise FileNotFoundError("EU4 map/definition.csv 或 map/provinces.bmp 不存在。")

    provinces = _read_definitions(definitions)
    colors = {
        (info.red << 16) | (info.green << 8) | info.blue: province_id
        for province_id, info in provinces.items()
    }
    sorted_colors = np.array(sorted(colors), dtype=np.uint32)
    color_ids = np.array([colors[int(color)] for color in sorted_colors], dtype=np.int32)
    max_id = max(provinces, default=0)
    counts = np.zeros(max_id + 1, dtype=np.int64)
    x_sums = np.zeros(max_id + 1, dtype=np.float64)
    y_sums = np.zeros(max_id + 1, dtype=np.float64)

    image = np.asarray(Image.open(province_map).convert("RGB"), dtype=np.uint32)
    width = image.shape[1]
    x_values = np.arange(width, dtype=np.float64)
    for y, row in enumerate(image):
        packed = (row[:, 0] << 16) | (row[:, 1] << 8) | row[:, 2]
        indices = np.searchsorted(sorted_colors, packed)
        valid = indices < len(sorted_colors)
        safe_indices = np.minimum(indices, max(len(sorted_colors) - 1, 0))
        valid &= sorted_colors[safe_indices] == packed
        ids = color_ids[safe_indices[valid]]
        counts += np.bincount(ids, minlength=max_id + 1)
        x_sums += np.bincount(ids, weights=x_values[valid], minlength=max_id + 1)
        y_sums += np.bincount(
            ids, weights=np.full(ids.shape, float(y)), minlength=max_id + 1
        )

    for province_id, info in provinces.items():
        if counts[province_id]:
            info.center_x = float(x_sums[province_id] / counts[province_id])
            info.center_y = float(y_sums[province_id] / counts[province_id])

    cache = Path(cache_path)
    cache.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache.with_suffix(cache.suffix + ".partial")
    temporary.write_text(
        json.dumps(
            {
                "source_mtime_ns": province_map.stat().st_mtime_ns,
                "source_sha256": _file_sha256(province_map),
                "definition_sha256": _file_sha256(definitions),
                "provinces": [asdict(item) for item in provinces.values()],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    temporary.replace(cache)
    return provinces


def load_or_build_province_index(
    game_dir: str | Path,
    cache_path: str | Path,
    *,
    mod_dir: str | Path | None = None,
) -> dict[int, ProvinceInfo]:
    cache = Path(cache_path)
    resources = GameResourceResolver.create(game_dir, mod_dir)
    province_map = resources.resolve_file("map/provinces.bmp")
    definitions = resources.resolve_file("map/definition.csv")
    if cache.is_file() and province_map.is_file() and definitions.is_file():
        try:
            raw = json.loads(cache.read_text(encoding="utf-8"))
            current_source = _file_sha256(province_map)
            current_definitions = _file_sha256(definitions)
            if (
                raw.get("source_sha256") == current_source
                and raw.get("definition_sha256") == current_definitions
            ) or (
                not raw.get("source_sha256")
                and raw.get("source_mtime_ns") == province_map.stat().st_mtime_ns
            ):
                return {
                    int(item["province_id"]): ProvinceInfo(**item)
                    for item in raw["provinces"]
                }
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return build_province_index(game_dir, cache, mod_dir=mod_dir)


def load_country_colors(
    game_dir: str | Path,
    cache_dir: str | Path | None = None,
    mod_dir: str | Path | None = None,
) -> dict[str, tuple[int, int, int]]:
    """Load colors through normalized roots so every caller shares one cache key."""
    resources = GameResourceResolver.create(game_dir, mod_dir)
    return _load_country_colors_cached(
        str(resources.game_dir),
        str(Path(cache_dir).resolve()) if cache_dir is not None else None,
        str(resources.mod_dir) if resources.mod_dir is not None else None,
    )


@lru_cache(maxsize=8)
def _load_country_colors_cached(
    game_dir: str,
    cache_dir: str | None = None,
    mod_dir: str | None = None,
) -> dict[str, tuple[int, int, int]]:
    """Load the canonical RGB color for every country tag from EU4 data files."""
    resources = GameResourceResolver.create(game_dir, mod_dir)
    version = detect_game_version(resources.game_dir)
    cache_path: Path | None = None
    if cache_dir is not None:
        cache_path = _country_color_cache_path(
            resources, Path(cache_dir), version.detected_build_id
        )
        try:
            raw = json.loads(cache_path.read_text(encoding="utf-8"))
            if (
                raw.get("cache_version") == MAP_CACHE_VERSION
                and raw.get("build_id") == version.detected_build_id
                and raw.get("mod_root", "")
                == (str(resources.mod_dir) if resources.mod_dir is not None else "")
            ):
                return {
                    tag: tuple(int(value) for value in color)
                    for tag, color in raw["colors"].items()
                }
        except (OSError, ValueError, KeyError, TypeError):
            pass
    tag_files = resources.overlay_files("common/country_tags", "*.txt")
    colors: dict[str, tuple[int, int, int]] = {}
    if not tag_files:
        return colors
    tag_pattern = re.compile(
        r'^\s*([A-Z0-9]{3})\s*=\s*"([^"]+)"', re.MULTILINE
    )
    color_pattern = re.compile(
        r"(?m)^\s*color\s*=\s*\{\s*(\d+)\s+(\d+)\s+(\d+)\s*\}"
    )
    for tag_file in tag_files:
        try:
            content = tag_file.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        for tag, relative in tag_pattern.findall(content):
            country_path = resources.resolve_file(
                Path("common").joinpath(*relative.replace("\\", "/").split("/"))
            )
            try:
                country_text = country_path.read_text(
                    encoding="utf-8-sig", errors="replace"
                )
            except OSError:
                continue
            match = color_pattern.search(country_text)
            if match:
                colors[tag] = tuple(
                    max(0, min(255, int(component))) for component in match.groups()
                )
    if cache_path is not None and colors:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache_path.with_suffix(cache_path.suffix + ".partial")
        temporary.write_text(
            json.dumps(
                {
                    "cache_version": MAP_CACHE_VERSION,
                    "build_id": version.detected_build_id,
                    "mod_root": (
                        str(resources.mod_dir) if resources.mod_dir is not None else ""
                    ),
                    "colors": colors,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        temporary.replace(cache_path)
    return colors


# Preserve the existing public cache-clear hook used by tests and diagnostics.
load_country_colors.cache_clear = _load_country_colors_cached.cache_clear  # type: ignore[attr-defined]


def _country_color_cache_path(
    resources: GameResourceResolver,
    cache_dir: Path,
    build_id: str | None,
) -> Path:
    build_key = build_id or "unknown"
    if resources.mod_dir is None:
        return cache_dir / f"country_colors_{build_key}.json"
    signature = hashlib.sha256(str(resources.mod_dir).lower().encode("utf-8"))
    for relative in ("common/country_tags", "common/countries"):
        try:
            stat = (resources.mod_dir / relative).stat()
            signature.update(f":{relative}:{stat.st_mtime_ns}".encode("ascii"))
        except OSError:
            continue
    mod_key = signature.hexdigest()[:12]
    return cache_dir / f"country_colors_{build_key}_mod_{mod_key}.json"


def invalidate_country_color_cache(
    game_dir: str | Path,
    cache_dir: str | Path | None,
    mod_dir: str | Path | None = None,
) -> None:
    """Discard one selected resource stack after the user explicitly saves settings."""
    _load_country_colors_cached.cache_clear()
    if cache_dir is None:
        return
    resources = GameResourceResolver.create(game_dir, mod_dir)
    version = detect_game_version(resources.game_dir)
    cache_path = _country_color_cache_path(
        resources, Path(cache_dir), version.detected_build_id
    )
    try:
        cache_path.unlink(missing_ok=True)
    except OSError:
        pass


def fallback_country_color(tag: str) -> tuple[int, int, int]:
    """Give custom or unknown tags a stable, distinguishable map color."""
    digest = hashlib.blake2b(tag.encode("ascii", errors="replace"), digest_size=4).digest()
    hue = int.from_bytes(digest[:2], "little") / 65535.0
    saturation = 0.48 + digest[2] / 255.0 * 0.24
    value = 0.66 + digest[3] / 255.0 * 0.24
    return tuple(round(channel * 255) for channel in colorsys.hsv_to_rgb(hue, saturation, value))


@lru_cache(maxsize=8)
def load_water_provinces(
    game_dir: str | Path, mod_dir: str | Path | None = None
) -> set[int]:
    default_map = GameResourceResolver.create(game_dir, mod_dir).resolve_file(
        "map/default.map"
    )
    try:
        text = default_map.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return set()
    water: set[int] = set()
    for key in ("sea_starts", "lakes"):
        match = re.search(rf"(?s)\b{key}\s*=\s*\{{(.*?)\}}", text)
        if match:
            water.update(int(value) for value in re.findall(r"\d+", match.group(1)))
    return water


def _load_cached_province_raster(
    cache_dir: Path, province_sha256: str, definition_sha256: str
) -> np.ndarray | None:
    try:
        manifests = list(cache_dir.glob("province_raster_*.json"))
    except OSError:
        return None
    for manifest in manifests:
        try:
            raw = json.loads(manifest.read_text(encoding="utf-8"))
            if (
                raw.get("cache_version") != MAP_CACHE_VERSION
                or raw.get("province_sha256") != province_sha256
                or raw.get("definition_sha256") != definition_sha256
            ):
                continue
            archive_path = manifest.with_name(raw["archive"])
            with np.load(archive_path, allow_pickle=False) as archive:
                province_ids = archive["province_ids"].astype(np.uint16, copy=False)
            if province_ids.ndim != 2:
                continue
            province_ids.setflags(write=False)
            return province_ids
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return None


def _save_province_raster_cache(
    cache_dir: Path,
    province_ids: np.ndarray,
    province_sha256: str,
    definition_sha256: str,
) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(
        f"{province_sha256}:{definition_sha256}".encode("ascii")
    ).hexdigest()[:12]
    archive_path = cache_dir / f"province_raster_{key}.npz"
    archive_temporary = archive_path.with_suffix(".npz.partial")
    with archive_temporary.open("wb") as stream:
        np.savez_compressed(stream, province_ids=province_ids)
    archive_temporary.replace(archive_path)
    manifest = archive_path.with_suffix(".json")
    manifest_temporary = manifest.with_suffix(".json.partial")
    manifest_temporary.write_text(
        json.dumps(
            {
                "cache_version": MAP_CACHE_VERSION,
                "province_sha256": province_sha256,
                "definition_sha256": definition_sha256,
                "archive": archive_path.name,
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    manifest_temporary.replace(manifest)


@lru_cache(maxsize=4)
def _province_id_raster(
    game_dir: str,
    province_mtime_ns: int,
    definition_mtime_ns: int,
    cache_dir: str | None = None,
    mod_dir: str | None = None,
) -> np.ndarray:
    del province_mtime_ns, definition_mtime_ns  # cache invalidation keys
    resources = GameResourceResolver.create(game_dir, mod_dir)
    province_path = resources.resolve_file("map/provinces.bmp")
    definition_path = resources.resolve_file("map/definition.csv")
    province_sha256 = _file_sha256(province_path)
    definition_sha256 = _file_sha256(definition_path)
    if cache_dir:
        cached = _load_cached_province_raster(
            Path(cache_dir), province_sha256, definition_sha256
        )
        if cached is not None:
            return cached
    definitions = _read_definitions(definition_path)
    colors = {
        (info.red << 16) | (info.green << 8) | info.blue: province_id
        for province_id, info in definitions.items()
    }
    sorted_colors = np.array(sorted(colors), dtype=np.uint32)
    color_ids = np.array([colors[int(color)] for color in sorted_colors], dtype=np.uint16)
    source = np.asarray(Image.open(province_path).convert("RGB"), dtype=np.uint32)
    packed = (source[:, :, 0] << 16) | (source[:, :, 1] << 8) | source[:, :, 2]
    indices = np.searchsorted(sorted_colors, packed)
    valid = indices < len(sorted_colors)
    safe = np.minimum(indices, max(len(sorted_colors) - 1, 0))
    if len(sorted_colors):
        valid &= sorted_colors[safe] == packed
    province_ids = np.zeros(packed.shape, dtype=np.uint16)
    if len(sorted_colors):
        province_ids[valid] = color_ids[safe[valid]]
    province_ids.setflags(write=False)
    if cache_dir:
        _save_province_raster_cache(
            Path(cache_dir), province_ids, province_sha256, definition_sha256
        )
    return province_ids


def build_political_map(
    game_dir: str | Path,
    province_owners: dict[int, str],
    province_controllers: dict[int, str] | None = None,
    *,
    draw_borders: bool = True,
    cache_dir: str | Path | None = None,
    mod_dir: str | Path | None = None,
) -> Image.Image:
    """Render the EU4 world map with each owned province in its country color."""
    resources = GameResourceResolver.create(game_dir, mod_dir)
    province_map = resources.resolve_file("map/provinces.bmp")
    definitions = resources.resolve_file("map/definition.csv")
    if not province_map.is_file() or not definitions.is_file():
        raise FileNotFoundError("EU4 政治地图需要 map/provinces.bmp 与 map/definition.csv。")
    province_ids = _province_id_raster(
        str(resources.game_dir),
        province_map.stat().st_mtime_ns,
        definitions.stat().st_mtime_ns,
        str(Path(cache_dir).resolve()) if cache_dir is not None else None,
        str(resources.mod_dir) if resources.mod_dir is not None else None,
    )
    max_id = int(province_ids.max(initial=0))
    palette = np.empty((max_id + 1, 3), dtype=np.uint8)
    palette[:] = (105, 101, 91)  # uncolonized land / wasteland
    palette[0] = (42, 67, 82)
    for province_id in load_water_provinces(
        str(resources.game_dir),
        str(resources.mod_dir) if resources.mod_dir is not None else None,
    ):
        if 0 <= province_id <= max_id:
            palette[province_id] = (42, 82, 104)
    country_colors = load_country_colors(
        str(resources.game_dir),
        str(Path(cache_dir).resolve()) if cache_dir is not None else None,
        str(resources.mod_dir) if resources.mod_dir is not None else None,
    )
    for province_id, owner in province_owners.items():
        if 0 < province_id <= max_id:
            palette[province_id] = country_colors.get(owner, fallback_country_color(owner))
    result = palette[province_ids].copy()
    if province_controllers:
        controller_palette = palette.copy()
        occupied_ids: list[int] = []
        for province_id, controller in province_controllers.items():
            owner = province_owners.get(province_id)
            if owner and controller != owner and 0 < province_id <= max_id:
                controller_palette[province_id] = country_colors.get(
                    controller, fallback_country_color(controller)
                )
                occupied_ids.append(province_id)
        if occupied_ids:
            height, width = province_ids.shape
            stripe = (
                np.arange(height, dtype=np.uint16)[:, None]
                + np.arange(width, dtype=np.uint16)[None, :]
            ) % 14 < 5
            occupied_lookup = np.zeros(max_id + 1, dtype=np.bool_)
            occupied_lookup[np.asarray(occupied_ids, dtype=np.uint16)] = True
            occupied = occupied_lookup[province_ids]
            mask = occupied & stripe
            result[mask] = controller_palette[province_ids[mask]]
    if draw_borders:
        border_color = np.array((24, 34, 43), dtype=np.uint8)
        horizontal = province_ids[:, 1:] != province_ids[:, :-1]
        vertical = province_ids[1:, :] != province_ids[:-1, :]
        result[:, 1:][horizontal] = border_color
        result[1:, :][vertical] = border_color
    return Image.fromarray(result)


def province_id_at(
    game_dir: str | Path,
    x: float,
    y: float,
    cache_dir: str | Path | None = None,
    mod_dir: str | Path | None = None,
) -> int | None:
    """Return the province id under a political-map scene coordinate."""
    resources = GameResourceResolver.create(game_dir, mod_dir)
    province_map = resources.resolve_file("map/provinces.bmp")
    definitions = resources.resolve_file("map/definition.csv")
    if not province_map.is_file() or not definitions.is_file():
        return None
    raster = _province_id_raster(
        str(resources.game_dir),
        province_map.stat().st_mtime_ns,
        definitions.stat().st_mtime_ns,
        str(Path(cache_dir).resolve()) if cache_dir is not None else None,
        str(resources.mod_dir) if resources.mod_dir is not None else None,
    )
    ix, iy = int(x), int(y)
    if iy < 0 or ix < 0 or iy >= raster.shape[0] or ix >= raster.shape[1]:
        return None
    province_id = int(raster[iy, ix])
    return province_id if province_id > 0 else None


def clear_runtime_map_caches() -> None:
    load_country_colors.cache_clear()
    load_water_provinces.cache_clear()
    _province_id_raster.cache_clear()
