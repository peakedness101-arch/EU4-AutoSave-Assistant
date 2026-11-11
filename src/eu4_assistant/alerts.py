from __future__ import annotations

from .models import AlertRecord, ArmyConcentrationWarning, CountrySnapshot, SaveRecord


def army_concentration_warnings(record: SaveRecord) -> list[ArmyConcentrationWarning]:
    country = record.countries.get(record.local_player_tag or "")
    if country is None or country.tag not in record.existing_tags:
        return []
    total = sum(army.regiment_count for army in country.armies)
    if total <= 0:
        return []
    enemies: set[str] = set()
    for war in record.active_wars:
        if country.tag in war.attackers:
            enemies.update(war.defenders)
        if country.tag in war.defenders:
            enemies.update(war.attackers)
    enemy_locations = {
        army.location
        for tag in enemies
        if tag in record.countries
        for army in record.countries[tag].armies
        if army.regiment_count > 0 and army.location is not None
    }
    counts: dict[int, int] = {}
    for army in country.armies:
        if army.location is not None and army.location > 0:
            counts[army.location] = counts.get(army.location, 0) + army.regiment_count
    return [
        ArmyConcentrationWarning(country.tag, province, count, total)
        for province, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        if count * 10 > total and province not in enemy_locations
    ]


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
