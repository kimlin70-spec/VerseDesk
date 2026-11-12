"""The verse list is shown in order, one verse per time slot on the local clock."""

import datetime as dt

from versedesk.rotation import (
    RotationClock,
    interval_label,
    next_change,
    slot_number,
    timer_ms,
    verse_index,
)


def test_slots_follow_the_wall_clock():
    assert slot_number(dt.datetime(2000, 1, 1, 0, 0), 120) == 0
    assert slot_number(dt.datetime(2000, 1, 1, 1, 59), 120) == 0
    assert slot_number(dt.datetime(2000, 1, 1, 2, 0), 120) == 1
    assert slot_number(dt.datetime(2000, 1, 2, 0, 0), 1440) == 1
    # time zones are ignored: it is the time shown on the PC's clock that counts
    aware = dt.datetime(2026, 11, 12, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=9)))
    assert slot_number(aware, 60) == slot_number(dt.datetime(2026, 11, 12, 9, 0), 60)


def test_the_list_goes_round_in_order():
    start = dt.datetime(2026, 11, 12, 0, 0)
    seen = [verse_index(start + dt.timedelta(hours=2 * k), 120, 5) for k in range(12)]
    first = seen[0]
    assert seen == [(first + k) % 5 for k in range(12)]
    assert verse_index(start, 120, 0) == 0  # empty list: no crash
    assert verse_index(dt.datetime(1990, 5, 1), 30, 7) in range(7)  # clock before 2000


def test_daily_changes_at_midnight_and_restarts_keep_the_place():
    a = verse_index(dt.datetime(2026, 11, 12, 0, 0), 1440, 40)
    assert verse_index(dt.datetime(2026, 11, 12, 23, 59), 1440, 40) == a
    assert verse_index(dt.datetime(2026, 11, 13, 0, 0), 1440, 40) == (a + 1) % 40


def test_next_change_and_timer():
    now = dt.datetime(2026, 11, 12, 9, 15, 30)
    assert next_change(now, 120) == dt.datetime(2026, 11, 12, 10, 0)
    assert next_change(now, 30) == dt.datetime(2026, 11, 12, 9, 30)
    assert next_change(now, 1440) == dt.datetime(2026, 11, 13, 0, 0)
    assert timer_ms(now, 30) == int((14 * 60 + 30 + 1.0) * 1000)
    assert timer_ms(dt.datetime(2026, 11, 12, 9, 29, 59, 999000), 30) >= 1000  # never zero
    assert timer_ms(now, 1440) == 6 * 3600 * 1000  # capped; the heartbeat re-arms it


def test_labels():
    assert [interval_label(m) for m in (30, 60, 120, 180, 360, 1440)] == [
        "30분마다", "1시간마다", "2시간마다", "3시간마다", "6시간마다", "하루에 한 번"]
    assert interval_label(90) == "1시간 30분마다" and interval_label(2880) == "2일마다" and interval_label(5) == "5분마다"


def test_clock_reports_each_new_slot_once(qapp):
    now = [dt.datetime(2026, 11, 12, 9, 0)]
    seen = []
    clock = RotationClock(lambda: seen.append(now[0]), 120, now=lambda: now[0])
    clock.check()
    assert seen == []
    now[0] = dt.datetime(2026, 11, 12, 10, 0, 1)
    clock.check()
    clock.check()
    assert len(seen) == 1
    now[0] = dt.datetime(2026, 11, 14, 7, 0)  # woke up from a long sleep
    clock.check()
    assert len(seen) == 2
    clock.set_interval(30)  # a new interval is not a change by itself
    clock.check()
    assert len(seen) == 2 and clock.interval == 30
    clock.stop()


def test_clock_survives_callback_errors(qapp):
    now = [dt.datetime(2026, 11, 12, 9, 0)]

    def boom():
        raise RuntimeError("x")

    clock = RotationClock(boom, 60, now=lambda: now[0])
    now[0] = dt.datetime(2026, 11, 12, 10, 0)
    clock.check()  # must not raise
    assert clock.current == slot_number(now[0], 60)
    clock.stop()
