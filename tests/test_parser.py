from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from eu4_assistant.parser import (
    _decode_player_name,
    _mana_index_mapping,
    _matching_brace,
    parse_save,
)


MINIMAL_SAVE = b'''EU4txt
savegame_version={
    first=1
    second=37
    third=5
    forth=0
}
multi_player=yes
players_countries={
    "Alice"
    "ENG"
}
date=1500.1.1
player="ENG"
provinces={
-236={
		name="London"
		owner="ENG"
		controller="FRA"
		history={
			owner="FRA"
		}
	}
-183={
		name="Paris"
		owner="FRA"
	}
}
countries={
\tENG={
\t\ttreasury=500.0
\t\tprimary_culture=english
\t\treligion=anglican
\t\tpowers={ 100 200 300 }
\t\ttechnology={
\t\t\tadm_tech=10
\t\t\tdip_tech=11
\t\t\tmil_tech=12
\t\t}
\t\tactive_idea_groups={
\t\t\tquality_ideas=7
\t\t}
\t\tmanpower=50.0
\t\tmax_manpower=100.0
\t\tsailors=2500.0
\t\tmax_sailors=5000.0
\t\tflags={
\t\t\ttest_flag=1499.1.1
\t\t}
\t\tvariables={
\t\t\ttest_variable=42
\t\t}
\t\testimated_loan=700
\t\tledger={
\t\t\tlastmonthincome=100
\t\t\tlastmonthincometable={ 10 20 30 4 }
\t\t\tlastmonthexpense=210
\t\t\tlastmonthexpensetable={ 1 81 3 }
\t\t}
\t\tadm_spent_indexed={
\t\t\t0=400 1=250 7=100 36=5 43=20 44=90
\t\t}
\t\tloan={
\t\t\tamount=700
\t\t\tinterest=3
\t\t\testate_loan=no
\t\t}
\t\tarmy={
\t\t\tid={
\t\t\t\tid=42
\t\t\t\ttype=54
\t\t\t}
\t\t\tname="First Army"
\t\t\tlocation=236
\t\t\tregiment={
\t\t\t\ttype="western_medieval_infantry"
\t\t\t\tstrength=0.75
\t\t\t}
\t\t}
\t\tnavy={
\t\t\tname="Home Fleet"
\t\t\tship={
\t\t\t\tname="Victory"
\t\t\t\ttype="carrack"
\t\t\t}
\t\t\tship={
\t\t\t\tname="Endeavour"
\t\t\t\ttype="caravel"
\t\t\t}
\t\t}
\t}
\tFRA={
\t\ttreasury=250.0
\t\tpowers={ 10 20 30 }
\t}
}
fired_events={
\ttest.1
}
'''


def test_parse_minimal_plaintext_save(tmp_path: Path) -> None:
    path = tmp_path / "test.eu4"
    path.write_bytes(MINIMAL_SAVE)
    record = parse_save(path)
    assert record.game_date == "1500.1.1"
    assert record.game_version == "1.37.5.0"
    assert record.multiplayer is True
    assert record.local_player_tag == "ENG"
    assert record.players[0].player_name == "Alice"
    eng = record.countries["ENG"]
    assert eng.powers == (100, 200, 300)
    assert eng.technology == (10, 11, 12)
    assert eng.ideas == {"quality_ideas": 7}
    assert eng.monthly_interest == 81
    assert eng.religion == "anglican"
    assert eng.primary_culture == "english"
    assert eng.income_breakdown["trade"] == 30
    assert eng.expense_breakdown["interest"] == 81
    assert eng.mana_spending["adm"] == {
        "buy_idea": 400,
        "advance_tech": 250,
        "develop_prov": 100,
        "other": 5,
        "force_march": 20,
        "create_leader": 90,
    }
    assert eng.loans[0].amount == 700
    assert eng.armies[0].location == 236
    assert eng.armies[0].strength == 750
    assert eng.manpower_people == 50_000
    assert eng.max_manpower_people == 100_000
    assert eng.sailors == 2500
    assert eng.max_sailors == 5000
    assert eng.ship_count == 2
    assert eng.flags == {"test_flag"}
    assert eng.variables == {"test_variable": "42"}
    assert record.fired_events == {"test.1"}
    assert record.province_owners == {236: "ENG", 183: "FRA"}
    assert record.province_controllers == {236: "FRA"}


def test_mana_index_mapping_tracks_eu4_version_changes() -> None:
    modern = _mana_index_mapping(37)
    assert modern[25] == "increse_tariffs"
    assert modern[37] == "artillery_barrage"
    assert modern[43] == "force_march"
    assert modern[44] == "create_leader"

    leviathan_era = _mana_index_mapping(34)
    assert leviathan_era[25] == "increse_tariffs"
    assert leviathan_era[36] == "boost_militarization"
    assert leviathan_era[43] == "add_tribal_land"
    assert leviathan_era[46] == "create_leader"

    legacy = _mana_index_mapping(30)
    assert legacy[25] == "buy_native_advancement"
    assert legacy[37] == "boost_militarization"
    assert legacy[46] == "create_leader"


def test_brace_scanner_ignores_braces_and_escaped_quotes_in_strings() -> None:
    block = b'root={\ntext="literal } { and \\"quoted\\" text"\nchild={ value=1 }\n}'
    assert _matching_brace(block, block.index(b"{")) == len(block)


def test_fast_country_boundary_keeps_following_top_level_blocks(tmp_path: Path) -> None:
    path = tmp_path / "fast-boundary.eu4"
    body = MINIMAL_SAVE.replace(
        b"\nfired_events={",
        b"\nactive_advisors={\n}\nfired_events={",
    )
    path.write_bytes(body)
    record = parse_save(path, include_all_countries=True)
    assert set(record.countries) == {"ENG", "FRA"}
    assert record.fired_events == {"test.1"}


def test_parse_zip_save(tmp_path: Path) -> None:
    path = tmp_path / "compressed.eu4"
    body = MINIMAL_SAVE.removeprefix(b"EU4txt\n")
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("gamestate", body)
        archive.writestr("meta", b"date=1500.1.1\nplayer=\"ENG\"\n")
    record = parse_save(path)
    assert record.format == "zip"
    assert record.countries["ENG"].monthly_interest == 81


def test_all_country_mode_includes_non_player_countries(tmp_path: Path) -> None:
    path = tmp_path / "all-countries.eu4"
    path.write_bytes(MINIMAL_SAVE)
    assert set(parse_save(path).countries) == {"ENG"}
    assert set(parse_save(path, include_all_countries=True).countries) == {"ENG", "FRA"}


def test_player_names_preserve_malformed_bytes_without_control_characters() -> None:
    assert _decode_player_name(b"\x11M\x96") == "ID:114d96"
    assert _decode_player_name("紫什么".encode() + b"\xe5lintian") == "紫什么\\xe5lintian"
