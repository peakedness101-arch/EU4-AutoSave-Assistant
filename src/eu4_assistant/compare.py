from __future__ import annotations

from datetime import date

from .models import ComparisonPoint, ForensicFinding, SaveRecord


class SaveVersionMismatch(ValueError):
    pass


def validate_same_game_version(records: list[SaveRecord]) -> str:
    missing = [record.path.name for record in records if not record.game_version]
    if missing:
        raise SaveVersionMismatch(
            "以下存档缺少可验证的 savegame_version：" + "、".join(missing)
        )
    versions = {record.game_version for record in records}
    if len(versions) != 1:
        details = "、".join(
            f"{record.path.name}={record.game_version}" for record in records
        )
        raise SaveVersionMismatch(f"存档版本号不一致，拒绝直接对比：{details}")
    return next(iter(versions))


def _date_key(value: str) -> tuple[int, int, int]:
    try:
        year, month, day = (int(part) for part in value.split(".", 2))
        return year, month, day
    except (TypeError, ValueError):
        return 0, 0, 0


def comparison_series(records: list[SaveRecord], country_tag: str) -> list[ComparisonPoint]:
    points: list[ComparisonPoint] = []
    for record in sorted(records, key=lambda item: _date_key(item.game_date)):
        country = record.countries.get(country_tag)
        if country is None:
            continue
        points.append(
            ComparisonPoint(
                game_date=record.game_date,
                country_tag=country_tag,
                treasury=country.treasury,
                monthly_income=country.monthly_income,
                monthly_expense=country.monthly_expense,
                monthly_interest=country.monthly_interest,
                debt=country.total_debt,
                adm=country.powers[0],
                dip=country.powers[1],
                mil=country.powers[2],
                adm_tech=country.technology[0],
                dip_tech=country.technology[1],
                mil_tech=country.technology[2],
                manpower=country.manpower_people,
                army_strength=country.army_strength,
                mana_spending={
                    power: dict(values)
                    for power, values in country.mana_spending.items()
                },
                income_breakdown=dict(country.income_breakdown),
                expense_breakdown=dict(country.expense_breakdown),
            )
        )
    return points


def comparison_metric_value(point: ComparisonPoint, metric: str) -> float:
    """Resolve scalar and save-ledger breakdown metrics for comparison charts."""
    if metric.startswith("mana_total:"):
        power = metric.split(":", 1)[1]
        return float(sum(point.mana_spending.get(power, {}).values()))
    if metric.startswith("mana:"):
        _prefix, power, category = metric.split(":", 2)
        return float(point.mana_spending.get(power, {}).get(category, 0))
    if metric.startswith("income:"):
        return float(point.income_breakdown.get(metric.split(":", 1)[1], 0.0))
    if metric.startswith("expense:"):
        return float(point.expense_breakdown.get(metric.split(":", 1)[1], 0.0))
    return float(getattr(point, metric))


def consecutive_date_gaps(points: list[ComparisonPoint], max_months: int = 12) -> list[str]:
    warnings: list[str] = []
    keys = [_date_key(point.game_date) for point in points]
    for left, right in zip(keys, keys[1:]):
        left_month = left[0] * 12 + left[1]
        right_month = right[0] * 12 + right[1]
        if right_month - left_month > max_months:
            warnings.append(
                f"{left[0]}.{left[1]}.{left[2]} 到 {right[0]}.{right[1]}.{right[2]} 存在日期缺口"
            )
    return warnings


def forensic_differences(records: list[SaveRecord], country_tag: str) -> list[ForensicFinding]:
    """Produce evidence-preserving changes without over-claiming cheating."""
    ordered = sorted(records, key=lambda item: _date_key(item.game_date))
    findings: list[ForensicFinding] = []
    for before, after in zip(ordered, ordered[1:]):
        old = before.countries.get(country_tag)
        new = after.countries.get(country_tag)
        if old is None or new is None:
            findings.append(
                ForensicFinding(
                    "inconclusive",
                    before.game_date,
                    after.game_date,
                    country_tag,
                    "country_presence",
                    "目标国家在其中一份存档中不存在，可能发生变身、吞并或存档不连续。",
                )
            )
            continue
        new_events = sorted(after.fired_events - before.fired_events)
        new_flags = sorted(new.flags - old.flags)
        removed_flags = sorted(old.flags - new.flags)
        changed_variables = {
            key: (old.variables.get(key), value)
            for key, value in new.variables.items()
            if old.variables.get(key) != value
        }
        for field, details in [
            ("fired_events", ", ".join(new_events)),
            ("flags_added", ", ".join(new_flags)),
            ("flags_removed", ", ".join(removed_flags)),
            (
                "variables_changed",
                ", ".join(f"{key}: {left} → {right}" for key, (left, right) in changed_variables.items()),
            ),
        ]:
            if details:
                findings.append(
                    ForensicFinding(
                        "inconclusive",
                        before.game_date,
                        after.game_date,
                        country_tag,
                        field,
                        details,
                    )
                )
    return findings
