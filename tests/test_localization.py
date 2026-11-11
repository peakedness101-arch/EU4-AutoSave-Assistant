from pathlib import Path
import json

import pytest

import eu4_assistant.localization as localization
from test_mini_window import application, window, make_record


@pytest.mark.parametrize("raw,expected", [
    (b'\x10\xc3\x9b\xc2\x8f\x11Ie\x10\x06t\x12\xc3\xb5V', '进攻理念'),
    (b'\x10\xdb\x8f\x11Ie\x10\x06t\x12\xf5V', '进攻理念'),
    ('§Y质量理念§!'.encode(), '质量理念'),
    ('瑞典理念'.encode(), '瑞典理念'),
])
def test_decodes_patch_and_save_encodings(raw, expected):
    assert localization._decode_localisation_value(raw) == expected


def write_locale(root: Path, value: str):
    folder = root / "localisation"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "test_l_english.yml").write_text('l_english:\n'+value, encoding="utf-8-sig")


def test_bundled_names_match_patch_and_unknown_keys_survive(monkeypatch, tmp_path):
    monkeypatch.setattr(localization, "_enabled_mod_roots", lambda: ())
    expected = {
        "gns_ideas": "瑞典理念", "influence_ideas": "影响理念",
        "maritime_ideas": "航海理念", "offensive_ideas": "进攻理念",
        "quality_ideas": "质量理念", "quantity_ideas": "数量理念",
        "religious_ideas": "宗教理念",
    }
    for key, name in expected.items():
        assert localization.idea_group_name(key, str(tmp_path)) == name
    assert localization.idea_group_name("unknown_mod_group", str(tmp_path)) == "unknown_mod_group"


def test_runtime_patch_and_configured_mod_override_with_chinese_only(monkeypatch, tmp_path):
    monkeypatch.setattr(localization, "_enabled_mod_roots", lambda: ())
    game = tmp_path / "steamapps" / "common" / "Europa Universalis IV"
    patch = game.parent.parent / "workshop" / "content" / "236850" / "2976470733"
    write_locale(game, ' quality_ideas:0 "Quality Ideas"\n')
    write_locale(patch, ' quality_ideas:0 "补丁质量理念"\n')
    mod = tmp_path / "custom_mod"
    write_locale(mod, ' quality_ideas:0 "模组质量理念"\n special_group: "特别理念"\n')
    (mod / "common" / "ideas").mkdir(parents=True)
    (mod / "common" / "ideas" / "custom.txt").write_text('special_group = { }', encoding="utf-8")
    assert localization.idea_group_name("quality_ideas", str(game)) == "补丁质量理念"
    assert localization.idea_group_name("quality_ideas", str(game), str(mod)) == "模组质量理念"
    assert localization.idea_group_name("special_group", str(game), str(mod)) == "特别理念"


def test_enabled_chinese_mod_not_overwritten_by_later_english_mod(monkeypatch, tmp_path):
    monkeypatch.setattr(localization, "documents_directory", lambda: tmp_path)
    home = tmp_path / "Paradox Interactive" / "Europa Universalis IV"
    (home / "mod").mkdir(parents=True)
    mods = [tmp_path / "chinese", tmp_path / "english"]
    for i, root in enumerate(mods):
        (home / "mod" / f"{i}.mod").write_text(f'path="{root.as_posix()}"', encoding="utf-8")
    (home / "dlc_load.json").write_text(json.dumps({"enabled_mods": ["mod/0.mod", "mod/1.mod"]}), encoding="utf-8")
    write_locale(mods[0], ' gns_ideas: "本地瑞典理念"\n')
    write_locale(mods[1], ' gns_ideas: "Swedish Ideas"\n')
    assert localization.idea_group_name("gns_ideas", str(tmp_path / "game")) == "本地瑞典理念"


def test_details_show_chinese_progress_and_original_keys(window, monkeypatch, tmp_path):
    monkeypatch.setattr(localization, "_enabled_mod_roots", lambda: ())
    window.config.game_dir = str(tmp_path / "no_game")
    record = make_record()
    country = record.countries["ENG"]
    country.ideas = {"gns_ideas": 0, "quality_ideas": 4, "unknown_group": 1}
    window.current_record = record
    window.selected_country_tag = "ENG"
    window._country_selection_changed()
    assert window.detail_ideas.text() == "瑞典理念：0/7　质量理念：4/7　unknown_group：1/7"
    assert "gns_ideas" in window.detail_ideas.toolTip()
