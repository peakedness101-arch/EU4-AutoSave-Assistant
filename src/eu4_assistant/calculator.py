from __future__ import annotations

import math

from .models import CountrySnapshot, LoanCapacityResult


class LoanCalculationError(ValueError):
    pass


def select_standard_loan_principal(country: CountrySnapshot) -> tuple[float, str]:
    """Follow the locked precedence: estimated_loan, max ordinary principal, manual."""
    if country.estimated_loan is not None and country.estimated_loan > 0:
        return float(country.estimated_loan), "estimated_loan"

    ordinary_amounts = [loan.amount for loan in country.ordinary_loans if loan.amount > 0]
    if ordinary_amounts:
        return max(ordinary_amounts), "max_ordinary_loan"

    raise LoanCalculationError("存档中没有可用的标准普通贷款本金，请手动输入。")


def calculate_loan_capacity(
    monthly_income: float,
    loan_principal: float,
    annual_interest_rate: float = 3.0,
    current_loan_count: int = 0,
    principal_source: str = "manual",
) -> LoanCapacityResult:
    if monthly_income < 0:
        raise LoanCalculationError("预估月收入不能为负数。")
    if loan_principal <= 0:
        raise LoanCalculationError("单笔贷款本金必须大于零。")
    if annual_interest_rate <= 0:
        raise LoanCalculationError("预估年利率必须大于零。")
    if current_loan_count < 0:
        raise LoanCalculationError("当前贷款数量不能为负数。")

    monthly_interest_per_loan = loan_principal * annual_interest_rate / 100.0 / 12.0
    estimated_max_loans = math.floor(monthly_income / monthly_interest_per_loan)
    estimated_remaining_loans = max(estimated_max_loans - current_loan_count, 0)
    usage = current_loan_count / estimated_max_loans if estimated_max_loans else 0.0

    return LoanCapacityResult(
        monthly_income=monthly_income,
        loan_principal=loan_principal,
        principal_source=principal_source,
        annual_interest_rate=annual_interest_rate,
        current_loan_count=current_loan_count,
        monthly_interest_per_loan=monthly_interest_per_loan,
        estimated_max_loans=estimated_max_loans,
        estimated_total_capacity=estimated_max_loans * loan_principal,
        estimated_remaining_loans=estimated_remaining_loans,
        estimated_current_interest=current_loan_count * monthly_interest_per_loan,
        capacity_usage=usage,
    )

