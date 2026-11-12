import datetime as dt

from versedesk.daywatch import DayWatcher, midnight_timer_ms, seconds_until_next_midnight


def test_seconds_until_midnight():
    assert seconds_until_next_midnight(dt.datetime(2026, 11, 12, 23, 59, 30)) == 30
    assert seconds_until_next_midnight(dt.datetime(2026, 12, 31, 0, 0, 0)) == 86400
    assert seconds_until_next_midnight(dt.datetime(2028, 2, 28, 12, 0, 0)) == 43200


def test_midnight_timer_is_capped_and_never_zero():
    assert midnight_timer_ms(dt.datetime(2026, 1, 1, 23, 59, 59, 900000)) >= 1000
    assert midnight_timer_ms(dt.datetime(2026, 1, 1, 0, 0, 1)) == 6 * 3600 * 1000
    assert midnight_timer_ms(dt.datetime(2026, 1, 1, 23, 0, 0)) == 3601 * 1000


def test_watcher_reports_each_change_once(qapp):
    days = [dt.date(2026, 1, 1)]
    seen = []
    w = DayWatcher(seen.append, today=lambda: days[0], now=lambda: dt.datetime(2026, 1, 1, 12, 0))
    w.check()
    assert seen == []
    days[0] = dt.date(2026, 1, 2)  # midnight passed (or the PC woke up the next day)
    w.check()
    w.check()
    assert seen == [dt.date(2026, 1, 2)]
    days[0] = dt.date(2026, 1, 5)  # long sleep
    w.check()
    assert seen == [dt.date(2026, 1, 2), dt.date(2026, 1, 5)]
    w.stop()


def test_watcher_survives_callback_errors(qapp):
    days = [dt.date(2026, 1, 1)]

    def boom(_):
        raise RuntimeError("x")

    w = DayWatcher(boom, today=lambda: days[0], now=lambda: dt.datetime(2026, 1, 1, 12, 0))
    days[0] = dt.date(2026, 1, 2)
    w.check()  # must not raise
    assert w.current == dt.date(2026, 1, 2)
    w.stop()
