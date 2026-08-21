from eu4_assistant.army_markers import (
    aggregate_armies_by_province,
    compact_army_strength,
)
from eu4_assistant.models import ArmySnapshot, CountrySnapshot


def _army(name: str, location: int, regiments: int, strength: float) -> ArmySnapshot:
    return ArmySnapshot(name, name, location, regiments, strength)


def test_armies_are_aggregated_once_per_province_and_country() -> None:
    countries = {
        "ENG": CountrySnapshot(
            tag="ENG",
            armies=[_army("A", 1, 5, 4_000), _army("B", 1, 4, 3_000)],
        ),
        "FRA": CountrySnapshot(
            tag="FRA", armies=[_army("C", 1, 12, 6_500), _army("D", 2, 2, 2_000)]
        ),
    }

    result = aggregate_armies_by_province(countries)

    assert set(result) == {1, 2}
    assert result[1].total_strength == 13_500
    assert result[1].countries["ENG"].army_count == 2
    assert result[1].dominant_tag == "ENG"
    assert result[2].dominant_tag == "FRA"


def test_dominant_country_ties_use_regiments_then_tag() -> None:
    countries = {
        "SWE": CountrySnapshot(tag="SWE", armies=[_army("A", 1, 8, 5_000)]),
        "DAN": CountrySnapshot(tag="DAN", armies=[_army("B", 1, 9, 5_000)]),
        "AAA": CountrySnapshot(tag="AAA", armies=[_army("C", 2, 9, 5_000)]),
        "BBB": CountrySnapshot(tag="BBB", armies=[_army("D", 2, 9, 5_000)]),
    }

    result = aggregate_armies_by_province(countries)

    assert result[1].dominant_tag == "DAN"
    assert result[2].dominant_tag == "AAA"


def test_compact_army_strength_uses_readable_map_labels() -> None:
    assert compact_army_strength(0) == "0"
    assert compact_army_strength(850) == "850"
    assert compact_army_strength(2_000) == "2k"
    assert compact_army_strength(2_450) == "2.5k"
    assert compact_army_strength(12_400) == "12k"
    assert compact_army_strength(1_250_000) == "1.2m"
