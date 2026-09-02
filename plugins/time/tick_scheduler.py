"""Adaptive wake-up policy shared by the time plugin widgets."""

from __future__ import annotations

import math


COUNTDOWN_THRESHOLD_SECONDS = 5 * 60
MINIMUM_TIMER_DELAY_MS = 50


def next_tick_delay_ms(
    time_format: str,
    *,
    current_second: int,
    current_millisecond: int,
    alarm_remaining_seconds: float | None = None,
) -> int:
    """Return an aligned delay for the next visible clock change."""
    second = min(59, max(0, int(current_second)))
    millisecond = min(999, max(0, int(current_millisecond)))
    has_second_precision = "s" in str(time_format or "")
    countdown_active = (
        alarm_remaining_seconds is not None
        and alarm_remaining_seconds <= COUNTDOWN_THRESHOLD_SECONDS
    )

    if has_second_precision or countdown_active:
        return max(MINIMUM_TIMER_DELAY_MS, 1000 - millisecond)

    minute_delay = (60 - second) * 1000 - millisecond
    if alarm_remaining_seconds is not None:
        until_countdown = math.ceil(
            max(0.0, alarm_remaining_seconds - COUNTDOWN_THRESHOLD_SECONDS) * 1000
        )
        if until_countdown:
            minute_delay = min(minute_delay, until_countdown)
    return max(MINIMUM_TIMER_DELAY_MS, minute_delay)


__all__ = ["COUNTDOWN_THRESHOLD_SECONDS", "next_tick_delay_ms"]
