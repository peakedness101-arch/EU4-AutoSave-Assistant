from __future__ import annotations

from .models import AlertRecord, CountrySnapshot


def economic_alerts(country: CountrySnapshot) -> list[AlertRecord]:
    alerts: list[AlertRecord] = []
    income = country.monthly_income
    expense = country.monthly_expense
    interest = country.monthly_interest
    treasury = country.treasury
    expense_ratio = expense / income if income > 0 else float("inf")
    interest_ratio = interest / income if income > 0 else float("inf")

    common = {
        "monthly_income": income,
        "monthly_expense": expense,
        "monthly_interest": interest,
        "treasury": treasury,
        "treasury_threshold": income * 100.0,
        "expense_income_ratio": expense_ratio,
        "interest_income_ratio": interest_ratio,
    }

    if expense > income * 2.0:
        alerts.append(
            AlertRecord(
                code="EXPENSE_OVER_200_PERCENT",
                severity="critical",
                country_tag=country.tag,
                title="月支出超过月收入两倍",
                message=(
                    f"上月收入 {income:.2f}，上月支出 {expense:.2f}"
                    f"（支出/收入 {expense_ratio:.1%}），上月实际利息 {interest:.2f}"
                    f"（利息/收入 {interest_ratio:.1%}），当前存款 {treasury:.2f}，"
                    f"存款阈值 {income * 100.0:.2f}。"
                ),
                values=dict(common),
            )
        )

    if interest > income * 0.8 and treasury < income * 100.0:
        alerts.append(
            AlertRecord(
                code="INTEREST_OVER_80_AND_LOW_TREASURY",
                severity="critical",
                country_tag=country.tag,
                title="利息接近收入上限且存款不足",
                message=(
                    f"上月收入 {income:.2f}，实际利息 {interest:.2f}"
                    f"（利息/收入 {interest_ratio:.1%}），上月支出 {expense:.2f}"
                    f"（支出/收入 {expense_ratio:.1%}），当前存款 {treasury:.2f}，"
                    f"存款阈值 {income * 100.0:.2f}。"
                ),
                values=dict(common),
            )
        )

    return alerts
