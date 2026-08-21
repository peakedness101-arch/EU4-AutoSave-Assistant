from __future__ import annotations

from dataclasses import dataclass, field

from .models import ArmySnapshot, CountrySnapshot


def compact_army_strength(strength: float) -> str:
    """Format actual soldiers for the compact province marker label."""
    strength = max(0.0, strength)
    if strength < 1_000:
        return f"{strength:.0f}"
    if strength < 10_000:
        value = f"{strength / 1_000:.1f}".rstrip("0").rstrip(".")
        return f"{value}k"
    if strength < 1_000_000:
        return f"{strength / 1_000:.0f}k"
    value = f"{strength / 1_000_000:.1f}".rstrip("0").rstrip(".")
    return f"{value}m"


@dataclass(slots=True)
class CountryArmyAggregate:
    tag: str
    strength: float = 0.0
    regiment_count: int = 0
    army_count: int = 0


@dataclass(slots=True)
class ProvinceArmyAggregate:
    province_id: int
    countries: dict[str, CountryArmyAggregate] = field(default_factory=dict)
    armies: list[tuple[str, ArmySnapshot]] = field(default_factory=list)

    @property
    def total_strength(self) -> float:
        return sum(item.strength for item in self.countries.values())

    @property
    def total_regiments(self) -> int:
        return sum(item.regiment_count for item in self.countries.values())

    @property
    def dominant_tag(self) -> str:
        return min(
            self.countries.values(),
            key=lambda item: (-item.strength, -item.regiment_count, item.tag),
        ).tag


def aggregate_armies_by_province(
    countries: dict[str, CountrySnapshot],
) -> dict[int, ProvinceArmyAggregate]:
    provinces: dict[int, ProvinceArmyAggregate] = {}
    for country in countries.values():
        for army in country.armies:
            if army.location is None or army.location <= 0:
                continue
            province = provinces.setdefault(
                army.location, ProvinceArmyAggregate(army.location)
            )
            aggregate = province.countries.setdefault(
                country.tag, CountryArmyAggregate(country.tag)
            )
            aggregate.strength += army.strength
            aggregate.regiment_count += army.regiment_count
            aggregate.army_count += 1
            province.armies.append((country.tag, army))
    return provinces
