from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from eu4_assistant.mapdata import (
    _province_id_raster,
    load_country_colors,
    load_or_build_province_index,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build portable EU4 map caches.")
    parser.add_argument("game_dir", type=Path)
    parser.add_argument("cache_dir", type=Path)
    parser.add_argument("province_index", type=Path)
    args = parser.parse_args()

    game_dir = args.game_dir.resolve()
    cache_dir = args.cache_dir.resolve()
    province_map = game_dir / "map" / "provinces.bmp"
    definitions = game_dir / "map" / "definition.csv"
    started = time.perf_counter()
    provinces = load_or_build_province_index(game_dir, args.province_index)
    raster = _province_id_raster(
        str(game_dir),
        province_map.stat().st_mtime_ns,
        definitions.stat().st_mtime_ns,
        str(cache_dir),
    )
    colors = load_country_colors(str(game_dir), str(cache_dir))
    print(
        json.dumps(
            {
                "provinces": len(provinces),
                "raster": list(raster.shape),
                "country_colors": len(colors),
                "seconds": round(time.perf_counter() - started, 3),
                "cache_dir": str(cache_dir),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
