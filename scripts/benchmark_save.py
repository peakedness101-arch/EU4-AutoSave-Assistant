from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from eu4_assistant.mapdata import build_political_map
from eu4_assistant.parser import parse_save


def _measure(operation, runs: int) -> tuple[object, list[float]]:
    result = None
    timings: list[float] = []
    for _ in range(runs):
        started = time.perf_counter()
        result = operation()
        timings.append(time.perf_counter() - started)
    return result, timings


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark a real EU4 save.")
    parser.add_argument("save", type=Path)
    parser.add_argument("game_dir", type=Path)
    parser.add_argument("cache_dir", type=Path)
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be at least 1")

    record, parse_timings = _measure(
        lambda: parse_save(args.save, include_all_countries=True), args.runs
    )
    _, map_timings = _measure(
        lambda: build_political_map(
            args.game_dir,
            record.province_owners,
            record.province_controllers,
            cache_dir=args.cache_dir,
        ),
        args.runs,
    )
    print(
        json.dumps(
            {
                "save": str(args.save.resolve()),
                "date": record.game_date,
                "countries": len(record.countries),
                "province_owners": len(record.province_owners),
                "parse_seconds": [round(value, 3) for value in parse_timings],
                "parse_median_seconds": round(statistics.median(parse_timings), 3),
                "map_seconds": [round(value, 3) for value in map_timings],
                "map_median_seconds": round(statistics.median(map_timings), 3),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
