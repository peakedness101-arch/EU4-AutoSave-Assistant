from __future__ import annotations

from dataclasses import dataclass


VALID_AUTOSAVE_MODES = {"manual", "quarterly", "yearly", "ten_minutes"}


@dataclass(frozen=True, slots=True)
class ScheduledSaveRequest:
    mode: str
    period_key: tuple[int, int] | None = None


class AutosaveScheduler:
    """State machine for retry-safe game-time and real-time autosaves."""

    def __init__(
        self,
        mode: str,
        *,
        now: float,
        real_interval_seconds: float = 600.0,
        retry_interval_seconds: float = 30.0,
    ) -> None:
        self.real_interval_seconds = real_interval_seconds
        self.retry_interval_seconds = retry_interval_seconds
        self.mode = "manual"
        self.last_period_key: tuple[int, int] | None = None
        self.last_success_at = now
        self.last_attempt_at = float("-inf")
        self.last_attempt_key: tuple[int, int] | None = None
        self.pending: ScheduledSaveRequest | None = None
        self.set_mode(mode, now=now)

    def set_mode(self, mode: str, *, now: float) -> None:
        if mode not in VALID_AUTOSAVE_MODES:
            mode = "manual"
        if mode == self.mode:
            return
        self.mode = mode
        self.last_period_key = None
        self.last_success_at = now
        self.last_attempt_at = float("-inf")
        self.last_attempt_key = None
        self.pending = None

    def due(self, game_date: str | None, *, now: float) -> ScheduledSaveRequest | None:
        if self.pending is not None or self.mode == "manual":
            return None

        if self.mode == "ten_minutes":
            if now - self.last_success_at < self.real_interval_seconds:
                return None
            if now - self.last_attempt_at < self.retry_interval_seconds:
                return None
            request = ScheduledSaveRequest(self.mode)
            self.pending = request
            self.last_attempt_at = now
            self.last_attempt_key = None
            return request

        key = _period_key(self.mode, game_date)
        if key is None:
            return None
        if self.last_period_key is None:
            self.last_period_key = key
            return None
        if key == self.last_period_key:
            return None
        if self.last_attempt_key == key and now - self.last_attempt_at < self.retry_interval_seconds:
            return None

        request = ScheduledSaveRequest(self.mode, key)
        self.pending = request
        self.last_attempt_at = now
        self.last_attempt_key = key
        return request

    def complete(
        self,
        request: ScheduledSaveRequest,
        *,
        success: bool,
        now: float,
    ) -> None:
        if self.pending != request:
            return
        if success:
            self.last_success_at = now
            if request.period_key is not None:
                self.last_period_key = request.period_key
        self.pending = None

    def note_manual_success(self, game_date: str | None, *, now: float) -> None:
        self.last_success_at = now
        key = _period_key(self.mode, game_date)
        if key is not None:
            self.last_period_key = key


def _period_key(mode: str, game_date: str | None) -> tuple[int, int] | None:
    if mode not in {"quarterly", "yearly"} or not game_date:
        return None
    try:
        year, month, _day = (int(part) for part in game_date.split(".", 2))
    except (TypeError, ValueError):
        return None
    if year < 1 or month < 1 or month > 12:
        return None
    return (year, (month - 1) // 3) if mode == "quarterly" else (year, 0)
