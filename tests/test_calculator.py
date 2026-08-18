from eu4_assistant.calculator import (
    LoanCalculationError,
    calculate_loan_capacity,
    select_standard_loan_principal,
)
from eu4_assistant.models import CountrySnapshot, LoanSnapshot


def test_principal_prefers_estimated_loan() -> None:
    country = CountrySnapshot(
        tag="ENG",
        estimated_loan=900,
        loans=[LoanSnapshot(1200, 3.0), LoanSnapshot(1500, 3.0)],
    )
    assert select_standard_loan_principal(country) == (900.0, "estimated_loan")


def test_principal_falls_back_to_max_ordinary_loan() -> None:
    country = CountrySnapshot(
        tag="ENG",
        loans=[
            LoanSnapshot(1200, 3.0),
            LoanSnapshot(1500, 3.0),
            LoanSnapshot(2000, 1.0, estate_loan=True),
        ],
    )
    assert select_standard_loan_principal(country) == (1500.0, "max_ordinary_loan")


def test_calculator_uses_three_percent_and_floor() -> None:
    result = calculate_loan_capacity(100, 1000, current_loan_count=10)
    assert result.monthly_interest_per_loan == 2.5
    assert result.estimated_max_loans == 40
    assert result.estimated_remaining_loans == 30
    assert result.estimated_total_capacity == 40000
    assert result.capacity_usage == 0.25


def test_calculator_rejects_invalid_values() -> None:
    for values in [(-1, 100, 3), (1, 0, 3), (1, 100, 0)]:
        try:
            calculate_loan_capacity(*values)
        except LoanCalculationError:
            pass
        else:
            raise AssertionError("expected LoanCalculationError")

