"""Which verse is on screen: the list is shown in order, one verse per time slot.

A slot is ``interval_minutes`` long and counted on the local wall clock from a fixed start
(2000-01-01 00:00).  So the verse depends only on the time — nothing is saved — and the list
keeps going in order across restarts.  With 120 minutes the verse changes at 0:00, 2:00,
4:00, ...; with 1440 (once a day) at midnight.

``RotationClock`` notices a new slot with two cheap mechanisms: a single-shot timer aimed
just past the next change, and a heartbeat every 30 s (catches sleep/hibernate resume and
clock or time-zone changes, where timers may fire late or never).  The pure helpers are
unit-tested; the Qt class is a thin wrapper.
"""

from __future__ import annotations

import datetime as _dt
import logging
from typing import Callable

log = logging.getLogger("versedesk.rotation")

EPOCH = _dt.datetime(2000, 1, 1)
DEFAULT_INTERVAL_MINUTES = 120
MIN_INTERVAL_MINUTES = 1
MAX_INTERVAL_MINUTES = 7 * 24 * 60
INTERVAL_CHOICES = (30, 60, 120, 180, 360, 1440)  # offered in the editor
HEARTBEAT_MS = 30_000
SLACK_S = 1.0  # fire slightly after the change so the clock has really moved on
TIMER_CAP_MS = 6 * 3600 * 1000  # re-armed by the heartbeat, so a clock jump never leaves it far off


def _local(now: _dt.datetime) -> _dt.datetime:
    return now.replace(tzinfo=None)  # wall-clock time, whatever the zone


def slot_number(now: _dt.datetime, interval_minutes: int) -> int:
    minutes = (_local(now) - EPOCH) // _dt.timedelta(minutes=1)
    return minutes // max(1, interval_minutes)


def verse_index(now: _dt.datetime, interval_minutes: int, count: int) -> int:
    """Position in a list of ``count`` verses (0 when the list is empty)."""
    return slot_number(now, interval_minutes) % count if count > 0 else 0


def next_change(now: _dt.datetime, interval_minutes: int) -> _dt.datetime:
    interval = max(1, interval_minutes)
    return EPOCH + _dt.timedelta(minutes=(slot_number(now, interval) + 1) * interval)


def timer_ms(now: _dt.datetime, interval_minutes: int, cap_ms: int = TIMER_CAP_MS) -> int:
    seconds = (next_change(now, interval_minutes) - _local(now)).total_seconds()
    return max(1000, min(int((seconds + SLACK_S) * 1000), cap_ms))


def interval_label(minutes: int) -> str:
    """Korean text for the editor: '30분마다', '2시간마다', '하루에 한 번'."""
    if minutes == 1440:
        return "하루에 한 번"
    if minutes % 1440 == 0:
        return f"{minutes // 1440}일마다"
    if minutes % 60 == 0:
        return f"{minutes // 60}시간마다"
    if minutes > 60:
        return f"{minutes // 60}시간 {minutes % 60}분마다"
    return f"{minutes}분마다"


class RotationClock:
    """Calls ``on_change()`` whenever the time slot changes."""

    def __init__(
        self,
        on_change: Callable[[], None],
        interval_minutes: int = DEFAULT_INTERVAL_MINUTES,
        now: Callable[[], _dt.datetime] = _dt.datetime.now,
    ):
        from PySide6.QtCore import QTimer

        self._on_change = on_change
        self._now = now
        self.interval = max(MIN_INTERVAL_MINUTES, interval_minutes)
        self.current = slot_number(now(), self.interval)
        self._heartbeat = QTimer()
        self._heartbeat.setInterval(HEARTBEAT_MS)
        self._heartbeat.timeout.connect(self.check)
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.check)

    def start(self) -> None:
        self._heartbeat.start()
        self._arm()

    def stop(self) -> None:
        self._heartbeat.stop()
        self._timer.stop()

    def set_interval(self, minutes: int) -> None:
        """A new interval starts counting at once (no change is reported here)."""
        self.interval = max(MIN_INTERVAL_MINUTES, minutes)
        self.current = slot_number(self._now(), self.interval)
        if self._heartbeat.isActive():
            self._arm()

    def _arm(self) -> None:
        self._timer.start(timer_ms(self._now(), self.interval))

    def check(self) -> None:
        try:
            slot = slot_number(self._now(), self.interval)
            if slot != self.current:
                self.current = slot
                self._on_change()
            if self._heartbeat.isActive() and not self._timer.isActive():
                self._arm()
        except Exception:
            log.exception("rotation check failed")
