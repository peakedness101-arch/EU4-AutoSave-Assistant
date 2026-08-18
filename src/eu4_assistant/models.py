from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass(slots=True)
class PlayerCountry:
    player_name: str
    country_tag: str


@dataclass(slots=True)
class LoanSnapshot:
    amount: float
    annual_interest: float
    estate_loan: bool = False
    expiry_date: str | None = None


@dataclass(slots=True)
class ArmySnapshot:
    army_id: str
    name: str
    location: int | None
    regiment_count: int
    strength: float
    unit_types: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class CountrySnapshot:
    tag: str
    player_name: str | None = None
    treasury: float = 0.0
    monthly_income: float = 0.0
    monthly_expense: float = 0.0
    monthly_interest: float = 0.0
    estimated_loan: float | None = None
    powers: tuple[int, int, int] = (0, 0, 0)
    technology: tuple[int, int, int] = (0, 0, 0)
    ideas: dict[str, int] = field(default_factory=dict)
    manpower: float = 0.0
    max_manpower: float = 0.0
    sailors: float = 0.0
    max_sailors: float = 0.0
    ship_count: int = 0
    stability: float = 0.0
    inflation: float = 0.0
    development: float = 0.0
    religion: str = ""
    primary_culture: str = ""
    income_breakdown: dict[str, float] = field(default_factory=dict)
    expense_breakdown: dict[str, float] = field(default_factory=dict)
    mana_spending: dict[str, dict[str, int]] = field(default_factory=dict)
    loans: list[LoanSnapshot] = field(default_factory=list)
    armies: list[ArmySnapshot] = field(default_factory=list)
    flags: set[str] = field(default_factory=set)
    variables: dict[str, str] = field(default_factory=dict)

    @property
    def ordinary_loans(self) -> list[LoanSnapshot]:
        return [loan for loan in self.loans if not loan.estate_loan]

    @property
    def total_debt(self) -> float:
        return sum(loan.amount for loan in self.loans)

    @property
    def army_strength(self) -> float:
        return sum(army.strength for army in self.armies)

    @property
    def manpower_people(self) -> float:
        """EU4 stores the manpower pool in thousands; expose actual people."""
        return self.manpower * 1000.0

    @property
    def max_manpower_people(self) -> float:
        return self.max_manpower * 1000.0


@dataclass(slots=True)
class SaveRecord:
    path: Path
    fingerprint: str
    format: Literal["plaintext", "zip"]
    game_date: str
    build_id: str | None
    local_player_tag: str | None
    players: list[PlayerCountry]
    countries: dict[str, CountrySnapshot]
    game_version: str | None = None
    multiplayer: bool | None = None
    fired_events: set[str] = field(default_factory=set)
    province_owners: dict[int, str] = field(default_factory=dict)
    province_controllers: dict[int, str] = field(default_factory=dict)


@dataclass(slots=True)
class ForensicFinding:
    classification: Literal[
        "direct_evidence", "high_confidence_anomaly", "suspicious", "inconclusive"
    ]
    from_date: str
    to_date: str
    country_tag: str
    field: str
    details: str


@dataclass(slots=True)
class AlertRecord:
    code: str
    severity: Literal["warning", "critical"]
    country_tag: str
    title: str
    message: str
    values: dict[str, float]


@dataclass(slots=True)
class LoanCapacityResult:
    monthly_income: float
    loan_principal: float
    principal_source: str
    annual_interest_rate: float
    current_loan_count: int
    monthly_interest_per_loan: float
    estimated_max_loans: int
    estimated_total_capacity: float
    estimated_remaining_loans: int
    estimated_current_interest: float
    capacity_usage: float


@dataclass(slots=True)
class ComparisonPoint:
    game_date: str
    country_tag: str
    treasury: float
    monthly_income: float
    monthly_expense: float
    monthly_interest: float
    debt: float
    adm: int
    dip: int
    mil: int
    adm_tech: int
    dip_tech: int
    mil_tech: int
    manpower: float
    army_strength: float
    mana_spending: dict[str, dict[str, int]] = field(default_factory=dict)
    income_breakdown: dict[str, float] = field(default_factory=dict)
    expense_breakdown: dict[str, float] = field(default_factory=dict)
