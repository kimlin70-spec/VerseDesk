"""Notice when the calendar date changes (midnight, waking from sleep, clock changes).

``DayWatcher`` combines two cheap mechanisms:
  * a single-shot timer aimed just past the next local midnight, and
  * a heartbeat every 30 s that compares today's date with the date on screen
    (this catches sleep/hibernate resume and manual clock or time-zone changes,
    where timers may fire late or never).
The pure helpers are unit-tested; the Qt class is a thin wrapper.
"""

from __future__ import annotations

import datetime as _dt
import logging
from typing import Callable

log = logging.getLogger("versedesk.daywatch")

HEARTBEAT_MS = 30_000
MIDNIGHT_SLACK_S = 1.0  # fire slightly after midnight so date.today() has really changed


def seconds_until_next_midnight(now: _dt.datetime) -> float:
    tomorrow = (now + _dt.timedelta(days=1)).date()
    midnight = _dt.datetime.combine(tomorrow, _dt.time(0, 0, 0), tzinfo=now.tzinfo)
    return max(0.0, (midnight - now).total_seconds())


def midnight_timer_ms(now: _dt.datetime, cap_ms: int = 6 * 3600 * 1000) -> int:
    """Delay for the midnight timer. Capped (and re-armed by the heartbeat) so a long
    sleep or clock jump can never leave a stale timer far in the future."""
    ms = int((seconds_until_next_midnight(now) + MIDNIGHT_SLACK_S) * 1000)
    return max(1000, min(ms, cap_ms))


class DayWatcher:
    """Calls ``on_change(new_date)`` whenever the local date differs from the last one seen."""

    def __init__(
        self,
        on_change: Callable[[_dt.date], None],
        today: Callable[[], _dt.date] = _dt.date.today,
        now: Callable[[], _dt.datetime] = _dt.datetime.now,
    ):
        from PySide6.QtCore import QTimer

        self._on_change = on_change
        self._today = today
        self._now = now
        self.current = today()
        self._heartbeat = QTimer()
        self._heartbeat.setInterval(HEARTBEAT_MS)
        self._heartbeat.timeout.connect(self.check)
        self._midnight = QTimer()
        self._midnight.setSingleShot(True)
        self._midnight.timeout.connect(self.check)

    def start(self) -> None:
        self._heartbeat.start()
        self._arm_midnight()

    def stop(self) -> None:
        self._heartbeat.stop()
        self._midnight.stop()

    def _arm_midnight(self) -> None:
        self._midnight.start(midnight_timer_ms(self._now()))

    def check(self) -> None:
        try:
            today = self._today()
            if today != self.current:
                log.info("date changed: %s -> %s", self.current, today)
                self.current = today
                self._on_change(today)
            if not self._midnight.isActive():
                self._arm_midnight()
        except Exception:
            log.exception("date check failed")
