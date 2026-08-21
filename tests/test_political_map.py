from pathlib import Path

from PIL import Image

from eu4_assistant.mapdata import (
    _province_id_raster,
    build_political_map,
    fallback_country_color,
    invalidate_country_color_cache,
    load_country_colors,
    load_water_provinces,
    province_id_at,
)


def _build_tiny_game(root: Path) -> None:
    (root / "map").mkdir(parents=True)
    (root / "common" / "country_tags").mkdir(parents=True)
    (root / "common" / "countries").mkdir(parents=True)
    (root / "map" / "definition.csv").write_text(
        "province;red;green;blue;x;x\n"
        "1;10;0;0;Land One;x\n"
        "2;0;10;0;Land Two;x\n"
        "3;0;0;10;Sea;x\n",
        encoding="utf-8",
    )
    Image.new("RGB", (3, 1)).save(root / "map" / "provinces.bmp")
    image = Image.open(root / "map" / "provinces.bmp")
    image.putdata([(10, 0, 0), (0, 10, 0), (0, 0, 10)])
    image.save(root / "map" / "provinces.bmp")
    (root / "map" / "default.map").write_text("sea_starts = { 3 }\nlakes = { }\n")
    (root / "common" / "country_tags" / "00_countries.txt").write_text(
        'ENG = "countries/England.txt"\nFRA = "countries/France.txt"\n',
        encoding="utf-8",
    )
    (root / "common" / "countries" / "England.txt").write_text(
        "color = { 200 10 20 }\n", encoding="utf-8"
    )
    (root / "common" / "countries" / "France.txt").write_text(
        "color = { 20 30 220 }\n", encoding="utf-8"
    )


def test_loads_country_colors_and_water_ids(tmp_path: Path) -> None:
    _build_tiny_game(tmp_path)
    assert load_country_colors(tmp_path)["ENG"] == (200, 10, 20)
    assert load_water_provinces(tmp_path) == {3}


def test_builds_country_colored_map(tmp_path: Path) -> None:
    _build_tiny_game(tmp_path)
    rendered = build_political_map(
        tmp_path, {1: "ENG", 2: "XYZ"}, draw_borders=False
    )
    assert list(rendered.getdata()) == [
        (200, 10, 20),
        fallback_country_color("XYZ"),
        (42, 82, 104),
    ]
    assert province_id_at(tmp_path, 0, 0) == 1
    assert province_id_at(tmp_path, 50, 50) is None


def test_occupied_province_uses_controller_stripes(tmp_path: Path) -> None:
    _build_tiny_game(tmp_path)
    image = Image.new("RGB", (20, 2), (10, 0, 0))
    image.save(tmp_path / "map" / "provinces.bmp")
    rendered = build_political_map(
        tmp_path,
        {1: "ENG"},
        {1: "FRA"},
        draw_borders=False,
    )
    colors = set(rendered.getdata())
    assert (200, 10, 20) in colors
    assert (20, 30, 220) in colors


def test_portable_map_caches_are_reused_and_invalidated(tmp_path: Path) -> None:
    _build_tiny_game(tmp_path)
    (tmp_path / "launcher-settings.json").write_text(
        '{"version":"EU4 v1.37.5.0 (491d)"}', encoding="utf-8"
    )
    cache = tmp_path / "cache"
    first = build_political_map(
        tmp_path, {1: "ENG"}, draw_borders=False, cache_dir=cache
    )
    assert first.getpixel((0, 0)) == (200, 10, 20)
    assert list(cache.glob("province_raster_*.npz"))
    assert (cache / "country_colors_491d.json").is_file()

    load_country_colors.cache_clear()
    _province_id_raster.cache_clear()
    (tmp_path / "common" / "countries" / "England.txt").write_text(
        "color = { 7 8 9 }\n", encoding="utf-8"
    )
    assert load_country_colors(tmp_path, cache)["ENG"] == (200, 10, 20)
    invalidate_country_color_cache(tmp_path, cache)
    assert load_country_colors(tmp_path, cache)["ENG"] == (7, 8, 9)
    assert (cache / "country_colors_491d.json").is_file()

    image = Image.open(tmp_path / "map" / "provinces.bmp")
    image.putdata([(0, 10, 0), (10, 0, 0), (0, 0, 10)])
    image.save(tmp_path / "map" / "provinces.bmp")
    _province_id_raster.cache_clear()
    assert province_id_at(tmp_path, 0, 0, cache) == 2
    assert len(list(cache.glob("province_raster_*.npz"))) == 2


def test_mod_resources_override_vanilla_with_per_file_fallback(tmp_path: Path) -> None:
    game = tmp_path / "game"
    mod = tmp_path / "mod"
    _build_tiny_game(game)
    (mod / "common" / "country_tags").mkdir(parents=True)
    (mod / "common" / "countries").mkdir(parents=True)
    (mod / "map").mkdir(parents=True)
    (mod / "common" / "country_tags" / "zz_mod.txt").write_text(
        'ENG = "countries/Mod England.txt"\nMOD = "countries/Modland.txt"\n',
        encoding="utf-8",
    )
    (mod / "common" / "countries" / "Mod England.txt").write_text(
        "color = { 1 2 3 }\n", encoding="utf-8"
    )
    (mod / "common" / "countries" / "Modland.txt").write_text(
        "color = { 4 5 6 }\n", encoding="utf-8"
    )
    (mod / "map" / "default.map").write_text(
        "sea_starts = { 2 }\nlakes = { }\n", encoding="utf-8"
    )

    colors = load_country_colors(game, None, mod)
    assert colors["ENG"] == (1, 2, 3)
    assert colors["MOD"] == (4, 5, 6)
    assert colors["FRA"] == (20, 30, 220)
    assert load_water_provinces(game, mod) == {2}
    assert province_id_at(game, 0, 0, mod_dir=mod) == 1
