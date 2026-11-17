"""Show-desktop diagnostics and the insert-after fallback of the desktop keeper (fake window
manager). Background: on a user's PC, after resume from sleep, every click on the desktop
minimised all windows until the reboot. VerseDesk only saw it happen; these lines in log.txt
are what will tell the cause the next time, and the hint tells the user what helps."""

import logging
import time
import types

from tests.fake_win32 import C
from tests.test_desktop_keeper import directly_above, env, make_widget, topmost  # noqa: F401 (env is a fixture)


def _scene(wm, d):
    prog = wm.explorer_24h2()
    wm.taskbar()
    app = wm.new("Notepad")
    other = wm.new("Chrome_WidgetWin_1")
    w = make_widget(wm)
    layer = d.Win32DesktopLayer("bottom")
    layer.attach(w, click_through=True)
    layer.start()
    return prog, app, other, layer


def _lines(caplog, *words):
    return [r.getMessage() for r in caplog.records if any(word in r.getMessage() for word in words)]


def test_the_show_desktop_line_tells_minimised_windows_from_covered_ones(env, caplog):
    wm, d = env
    caplog.set_level(logging.INFO, logger="versedesk.desktop")
    prog, app, other, layer = _scene(wm, d)

    wm.keys = "LWin D"
    wm.win_d_24h2()  # a real Show desktop: the app windows are minimised, the desktop raised
    layer._on_win_event(0, d.api.EVENT_SYSTEM_FOREGROUND, prog, 0, 0, 0, 0)
    wm.keys = "none"
    layer._tick()
    raised = _lines(caplog, "desktop raised")[-1]
    assert "app windows: 2 minimised, 0 covered by the desktop, 0 above it" in raised
    assert "foreground 0x" in raised and "'Progman'" in raised
    assert "(held LWin D)" in raised  # the foreground change remembered the keys held at that moment
    assert "held none, last input 0 ms ago" in raised and "cursor (10, 10)" in raised

    wm.restore_app(app, prog)  # the user clicks an app on the taskbar
    layer._tick()
    normal = _lines(caplog, "back to normal")[-1]
    assert "lowered by Explorer" in normal and "0 minimised, 0 covered by the desktop, 2 above it" in normal

    wm._move(prog, wm._first_normal_index())  # the desktop merely comes to the front: nothing minimised
    layer._tick()
    assert "0 minimised, 2 covered by the desktop, 0 above it" in _lines(caplog, "desktop raised")[-1]
    layer.stop()


def test_back_to_normal_says_which_window_covers_a_desktop_that_is_still_up(env, caplog):
    wm, d = env
    caplog.set_level(logging.INFO, logger="versedesk.desktop")
    prog, app, other, layer = _scene(wm, d)
    wm.win_d_24h2()
    layer._tick()
    wm.wins[app].iconic = False
    wm._move(app, wm._first_normal_index())  # a window comes up above the raised desktop
    layer._tick()
    assert f"covered by 0x{app:X} 'Notepad'" in _lines(caplog, "back to normal")[-1]
    layer.stop()


def test_the_widget_does_not_stay_above_the_apps_when_windows_refuses_the_anchor(env, caplog):
    """Seen on the user's PC: SetWindowPos refused a hidden 'Default IME' window of another
    process as the insert-after anchor (ok=False). Right after Show desktop the widget would
    then stay where HWND_NOTOPMOST put it: above every app window."""
    wm, d = env
    caplog.set_level(logging.INFO, logger="versedesk.desktop")
    prog, app, other, layer = _scene(wm, d)
    wm.win_d_24h2()
    layer._tick()
    assert layer._raised and topmost(wm, 0x9000)
    wm.restore_app(app, prog)  # Explorer lowers the desktop to the very bottom...
    ime = wm.new("IME", title="Default IME", visible=False, top=False)  # ...right below a refused window
    wm.z.remove(ime)
    wm.z.insert(wm.z.index(prog), ime)
    wm.refused_anchors.add(ime)
    layer._tick()
    assert not topmost(wm, 0x9000)
    assert wm.z.index(app) < wm.z.index(0x9000) and wm.z.index(other) < wm.z.index(0x9000)
    assert directly_above(wm, 0x9000, prog)  # only the hidden IME window in between
    failed = _lines(caplog, "FAILED")
    assert failed and "FAILED (error 5)" in failed[0] and "IME" in failed[0]  # what Windows said, and to what
    assert all(r.levelno == logging.WARNING for r in caplog.records if "FAILED" in r.getMessage())
    layer.stop()


def test_the_anchor_fallback_never_climbs_into_the_topmost_band(env):
    """Below a higher topmost window the widget would become topmost itself: never try that."""
    wm, d = env
    prog, app, other, layer = _scene(wm, d)
    entry = next(iter(layer._pinned.values()))
    taskbar = next(h for h in wm.z if wm.wins[h].cls == "Shell_TrayWnd")
    low_top = wm.new("Overlay", ex=C["WS_EX_TOPMOST"] | C["WS_EX_TOOLWINDOW"])
    ime = wm.new("IME", visible=False, top=False)
    # an odd but possible moment: the widget below the desktop, nothing normal above the desktop
    # but a refused hidden window, and the lowest topmost window refuses too
    wm.z = [taskbar, low_top, ime, prog, 0x9000, layer._sentinel]
    wm.refused_anchors.update({ime, low_top})
    assert layer._place_above(entry, prog) is False  # (the next pass tries again)
    assert not topmost(wm, 0x9000)  # not slipped in below the taskbar, into the topmost band
    assert wm.z.index(0x9000) > wm.z.index(prog)
    layer.stop()


def test_a_refused_anchor_that_vanishes_never_sends_the_widget_to_hwnd_top(env):
    """HWND_TOP would put the widget above every app window - the very thing the fallback avoids."""
    wm, d = env
    prog, app, other, layer = _scene(wm, d)
    entry = next(iter(layer._pinned.values()))
    ime = wm.new("IME", visible=False, top=False)
    wm.z.remove(ime)
    wm.z.insert(wm.z.index(prog), ime)  # a hidden foreign window right above the desktop...
    wm.refused_anchors.add(ime)
    real = wm.set_window_pos

    def refuse_then_vanish(h, after, flags):
        ok = real(h, after, flags)
        if not ok and after == ime:
            wm.destroy(ime)  # ...that is gone before the next window up is looked for
        return ok

    wm.set_window_pos = refuse_then_vanish
    wm.calls.clear()
    assert layer._place_above(entry, prog) is False  # (the next pass looks again)
    assert not [c for c in wm.calls if c[0] == "SetWindowPos" and c[1] == 0x9000 and c[2] == 0]
    assert wm.z.index(app) < wm.z.index(0x9000)
    layer.stop()


def test_bring_to_front_also_steps_over_a_refused_anchor(env):
    wm, d = env
    wm.explorer_24h2()
    wm.taskbar()
    app = wm.new("Notepad")
    a, b = make_widget(wm, 0x9100), make_widget(wm, 0x9200)
    layer = d.Win32DesktopLayer("bottom")
    layer.attach(a)
    layer.attach(b)
    layer.bring_to_front(b)  # b is the highest of ours now
    ime = wm.new("CicLoaderWndClass", visible=False, top=False)
    wm.z.remove(ime)
    wm.z.insert(wm.z.index(0x9200), ime)  # a hidden foreign window right above our group
    wm.refused_anchors.add(ime)
    layer.bring_to_front(a)
    assert wm.z.index(0x9100) < wm.z.index(0x9200)  # a came to the front of our group...
    assert wm.z.index(app) < wm.z.index(0x9100)  # ...and is still below the app window
    assert not topmost(wm, 0x9100)


def test_show_desktop_switching_on_again_and_again_is_reported_once_an_hour(env, caplog, monkeypatch):
    wm, d = env
    caplog.set_level(logging.INFO, logger="versedesk.desktop")
    clock = [1000.0]
    monkeypatch.setattr(d, "time", types.SimpleNamespace(monotonic=lambda: clock[0], time=time.time))
    prog, app, other, layer = _scene(wm, d)
    storms = []
    layer.show_desktop_storm.connect(lambda: storms.append(clock[0]))

    def cycle(seconds_later):
        clock[0] += seconds_later
        wm.win_d_24h2()
        layer._tick()
        wm.restore_app(app, prog)
        layer._tick()

    for _ in range(3):  # the user pressing Win+D now and then: nothing to report
        cycle(60)
    assert not storms
    for i in range(4):  # four times within 30 s, as on the user's PC after resume
        cycle(60 if i == 0 else 2)
        assert bool(storms) == (i == 3), f"after quick cycle {i + 1}"  # the fourth, not earlier
    assert len(storms) == 1
    warning = _lines(caplog, "Show desktop switched on")
    assert len(warning) == 1 and "4 times within" in warning[0] and "visible top-level windows" in warning[0]
    for _ in range(8):  # it goes on: not again within the hour
        cycle(2)
    assert len(storms) == 1
    clock[0] += 3600
    for _ in range(4):
        cycle(2)
    assert len(storms) == 2
    layer.stop()


def test_a_long_gap_between_passes_is_logged_as_sleep(env, caplog):
    wm, d = env
    caplog.set_level(logging.INFO, logger="versedesk.desktop")
    prog, app, other, layer = _scene(wm, d)
    layer._tick()
    assert not _lines(caplog, "no desktop check")
    layer._last_tick_wall = time.time() - 125
    layer._tick()
    assert "no desktop check for 125 s" in _lines(caplog, "no desktop check")[0]
    layer.stop()


def test_diagnostics_never_break_the_keeper(env, caplog, monkeypatch):
    wm, d = env
    caplog.set_level(logging.INFO, logger="versedesk.desktop")
    prog, app, other, layer = _scene(wm, d)

    def broken(*_a):
        raise OSError("no cursor on this desktop")

    monkeypatch.setattr(d.api, "cursor_pos", broken)
    wm.win_d_24h2()
    layer._tick()
    assert layer._raised and topmost(wm, 0x9000)  # the widget was lifted all the same
    assert "details failed" in _lines(caplog, "desktop raised")[-1]
    layer.stop()
