from eu4_assistant.scheduling import AutosaveScheduler


def test_quarterly_baselines_then_commits_only_after_success() -> None:
    scheduler = AutosaveScheduler("quarterly", now=0, retry_interval_seconds=30)
    assert scheduler.due("1450.1.1", now=0) is None

    request = scheduler.due("1450.4.1", now=10)
    assert request is not None
    scheduler.complete(request, success=False, now=11)
    assert scheduler.last_period_key == (1450, 0)
    assert scheduler.due("1450.4.2", now=20) is None

    retry = scheduler.due("1450.4.3", now=40)
    assert retry is not None
    scheduler.complete(retry, success=True, now=41)
    assert scheduler.last_period_key == (1450, 1)
    assert scheduler.due("1450.4.4", now=50) is None


def test_ten_minute_mode_retries_and_counts_from_success() -> None:
    scheduler = AutosaveScheduler(
        "ten_minutes", now=100, real_interval_seconds=600, retry_interval_seconds=30
    )
    assert scheduler.due(None, now=699) is None
    request = scheduler.due(None, now=700)
    assert request is not None
    scheduler.complete(request, success=False, now=701)
    assert scheduler.due(None, now=720) is None

    retry = scheduler.due(None, now=730)
    assert retry is not None
    scheduler.complete(retry, success=True, now=731)
    assert scheduler.due(None, now=1330) is None
    assert scheduler.due(None, now=1331) is not None


def test_manual_success_satisfies_current_game_period() -> None:
    scheduler = AutosaveScheduler("yearly", now=0)
    assert scheduler.due("1450.1.1", now=0) is None
    scheduler.note_manual_success("1451.2.1", now=10)
    assert scheduler.due("1451.12.31", now=20) is None
    assert scheduler.due("1452.1.1", now=30) is not None


def test_invalid_dates_and_modes_never_trigger() -> None:
    scheduler = AutosaveScheduler("quarterly", now=0)
    assert scheduler.due("bad", now=100) is None
    assert scheduler.due("1450.13.1", now=200) is None
    scheduler.set_mode("unknown", now=300)
    assert scheduler.mode == "manual"
    assert scheduler.due("1451.1.1", now=1000) is None
