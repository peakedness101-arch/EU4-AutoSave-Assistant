from pathlib import Path

import pytest

from eu4_assistant.compare import (
    SaveVersionMismatch,
    comparison_series,
    comparison_metric_value,
    forensic_differences,
    validate_same_game_version,
)
from eu4_assistant.models import CountrySnapshot, SaveRecord


def make_record(game_date: str, treasury: float, events: set[str], flags: set[str]) -> SaveRecord:
    country = CountrySnapshot(
        tag="ENG",
        treasury=treasury,
        powers=(1, 2, 3),
        technology=(10, 11, 12),
        flags=flags,
    )
    return SaveRecord(
        path=Path(f"{game_date}.eu4"),
        fingerprint=game_date,
        format="plaintext",
        game_date=game_date,
        build_id="491d",
        local_player_tag="ENG",
        players=[],
        countries={"ENG": country},
        game_version="1.37.5.0",
        fired_events=events,
    )


def test_multi_save_series_is_sorted_and_forensics_stays_inconclusive() -> None:
    later = make_record("1501.1.1", 200, {"test.1"}, {"flag_a"})
    earlier = make_record("1500.1.1", 100, set(), set())
    points = comparison_series([later, earlier], "ENG")
    assert [point.game_date for point in points] == ["1500.1.1", "1501.1.1"]
    assert [point.treasury for point in points] == [100, 200]
    findings = forensic_differences([later, earlier], "ENG")
    assert {finding.field for finding in findings} == {"fired_events", "flags_added"}
    assert {finding.classification for finding in findings} == {"inconclusive"}


def test_comparison_rejects_different_save_versions_without_using_checksum() -> None:
    first = make_record("1500.1.1", 100, set(), set())
    second = make_record("1501.1.1", 200, set(), set())
    assert validate_same_game_version([first, second]) == "1.37.5.0"
    second.game_version = "1.38.0.0"
    with pytest.raises(SaveVersionMismatch):
        validate_same_game_version([first, second])


def test_comparison_exposes_mana_and_ledger_breakdowns() -> None:
    record = make_record("1500.1.1", 100, set(), set())
    country = record.countries["ENG"]
    country.mana_spending = {"adm": {"advance_tech": 300, "buy_idea": 100}}
    country.income_breakdown = {"trade": 42.5}
    country.expense_breakdown = {"army_maintenance": 12.25}
    point = comparison_series([record], "ENG")[0]
    assert comparison_metric_value(point, "mana_total:adm") == 400
    assert comparison_metric_value(point, "mana:adm:buy_idea") == 100
    assert comparison_metric_value(point, "income:trade") == 42.5
    assert comparison_metric_value(point, "expense:army_maintenance") == 12.25


def test_comparison_manpower_uses_same_people_unit_as_army_strength() -> None:
    record = make_record("1500.1.1", 100, set(), set())
    country = record.countries["ENG"]
    country.manpower = 12.5
    point = comparison_series([record], "ENG")[0]
    assert point.manpower == 12_500
