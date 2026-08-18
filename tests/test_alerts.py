from eu4_assistant.alerts import economic_alerts
from eu4_assistant.models import CountrySnapshot


def test_expense_alert_is_strictly_greater_than_200_percent() -> None:
    exact = CountrySnapshot(tag="ENG", monthly_income=100, monthly_expense=200)
    over = CountrySnapshot(tag="ENG", monthly_income=100, monthly_expense=200.01)
    assert not economic_alerts(exact)
    assert [a.code for a in economic_alerts(over)] == ["EXPENSE_OVER_200_PERCENT"]


def test_interest_alert_requires_both_conditions() -> None:
    base = dict(tag="ENG", monthly_income=100, monthly_expense=0, monthly_interest=80.01)
    assert not economic_alerts(CountrySnapshot(**base, treasury=10000))
    alerts = economic_alerts(CountrySnapshot(**base, treasury=9999.99))
    assert [a.code for a in alerts] == ["INTEREST_OVER_80_AND_LOW_TREASURY"]


def test_interest_exactly_80_percent_does_not_alert() -> None:
    country = CountrySnapshot(
        tag="ENG", monthly_income=100, monthly_interest=80, treasury=0
    )
    assert not economic_alerts(country)


def test_alert_payload_contains_all_display_values() -> None:
    country = CountrySnapshot(
        tag="ENG", monthly_income=100, monthly_expense=250,
        monthly_interest=90, treasury=500,
    )
    for alert in economic_alerts(country):
        assert set(alert.values) >= {
            "monthly_income", "monthly_expense", "monthly_interest", "treasury",
            "treasury_threshold", "expense_income_ratio", "interest_income_ratio",
        }
        assert "存款阈值" in alert.message
