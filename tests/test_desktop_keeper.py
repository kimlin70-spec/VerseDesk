"""Drive the real Windows desktop-layer logic (versedesk/win32/desktop.py) against the fake
window manager in tests/fake_win32.py. This checks the state machine, not Windows itself;
the live check on a real desktop runs in CI (tools/ci_desktop_check.py)."""

import ctypes
import importlib
import sys
from ctypes import wintypes

import pytest
from PySide6.QtWidgets import QWidget

from tests.fake_win32 import C, EXPLORER_PID, WINDOWPOS, FakeWM


class FakeWidget(QWidget):
    def __init__(self, hwnd):
        super().__init__()
        self._hwnd = hwnd
        self._visible = True
        self.setObjectName(f"w{hwnd:x}")

    def winId(self):  # noqa: N802
        return self._hwnd

    def isVisible(self):  # noqa: N802
        return self._visible


@pytest.fixture
def env(monkeypatch, qapp):
    wm = FakeWM()
    import versedesk.win32 as pkg

    monkeypatch.setitem(sys.modules, "versedesk.win32.api", wm.api)
    monkeypatch.setattr(pkg, "api", wm.api, raising=False)
    sys.modules.pop("versedesk.win32.desktop", None)
    desktop = importlib.import_module("versedesk.win32.desktop")
    yield wm, desktop
    sys.modules.pop("versedesk.win32.desktop", None)


def make_widget(wm, hwnd=0x9000):
    wm.adopt(hwnd, ex=C["WS_EX_TOOLWINDOW"] | C["WS_EX_LAYERED"])
    return FakeWidget(hwnd)


def directly_above(wm, a, b):
    """``a`` is above ``b`` with only hidden windows (e.g. the sentinel) in between."""
    ia, ib = wm.z.index(a), wm.z.index(b)
    return ia < ib and all(not wm.wins[h].visible for h in wm.z[ia + 1:ib])


def topmost(wm, h):
    return bool(wm.wins[h].ex & C["WS_EX_TOPMOST"])


def test_find_host_ignores_file_explorer_windows(env):
    wm, d = env
    prog = wm.new("Progman", top=False, pid=EXPLORER_PID)  # DefView not created yet
    wm.shell = prog
    cab = wm.new("CabinetWClass", pid=EXPLORER_PID)
    wm.new("SHELLDLL_DefView", child_of=cab, pid=EXPLORER_PID)
    assert d.find_desktop_host() == prog
    wm.new("SHELLDLL_DefView", child_of=prog, pid=EXPLORER_PID)
    assert d.find_desktop_host() == prog


def test_attach_places_widget_directly_on_the_desktop_with_styles(env):
    wm, d = env
    prog = wm.explorer_24h2()
    wm.taskbar()
    wm.new("Notepad")
    wm.new("Chrome")
    w = make_widget(wm)
    layer = d.Win32DesktopLayer("bottom")
    layer.attach(w, click_through=True)
    assert directly_above(wm, 0x9000, prog)
    ex = wm.wins[0x9000].ex
    assert ex & C["WS_EX_TRANSPARENT"] and ex & C["WS_EX_NOACTIVATE"] and ex & C["WS_EX_TOOLWINDOW"]
    assert wm.wins[0x9000].owner == 0
    assert ("exclude_from_peek", 0x9000) in wm.calls
    layer.start()
    assert not layer._raised and not topmost(wm, 0x9000)
    layer.set_click_through(w, False)
    assert not wm.wins[0x9000].ex & C["WS_EX_TRANSPARENT"]
    layer.stop()


def test_win_d_on_24h2_lifts_and_restore_drops_again(env):
    wm, d = env
    prog = wm.explorer_24h2()
    tb = wm.taskbar()
    app = wm.new("Notepad")
    w = make_widget(wm)
    layer = d.Win32DesktopLayer("bottom")
    layer.attach(w, click_through=True)
    layer.start()

    wm.win_d_24h2()  # apps minimized, Progman raised
    layer._tick()
    assert layer._raised
    assert topmost(wm, 0x9000)
    assert wm.z.index(tb) < wm.z.index(0x9000) < wm.z.index(prog)  # under the taskbar, above the desktop

    wm._move(prog, wm._first_normal_index())  # Explorer raises the desktop once more
    layer._tick()
    assert wm.z.index(0x9000) < wm.z.index(prog)

    wm.restore_app(app, prog)  # user clicks the app on the taskbar
    layer._tick()
    assert not layer._raised
    assert not topmost(wm, 0x9000)
    assert directly_above(wm, 0x9000, prog)
    assert wm.z.index(app) < wm.z.index(0x9000)
    layer.stop()


def test_win_d_on_windows_10_split_desktop(env):
    wm, d = env
    prog = wm.explorer_win10()
    wm.taskbar()
    app = wm.new("Notepad")
    w = make_widget(wm)
    layer = d.Win32DesktopLayer("bottom")
    layer.attach(w, click_through=True)
    layer.start()
    assert directly_above(wm, 0x9000, prog)

    worker = wm.win_d_win10()
    layer._tick()
    assert d.find_desktop_host() == worker
    assert layer._raised and topmost(wm, 0x9000)
    assert wm.z.index(0x9000) < wm.z.index(worker)

    wm.restore_app(app, worker)
    layer._tick()
    assert not layer._raised and not topmost(wm, 0x9000)
    assert directly_above(wm, 0x9000, worker)
    assert wm.z.index(app) < wm.z.index(0x9000)
    layer.stop()


def test_explorer_restart_reattaches(env):
    wm, d = env
    wm.explorer_24h2()
    wm.new("Notepad")
    w = make_widget(wm)
    layer = d.Win32DesktopLayer("bottom")
    layer.attach(w, click_through=True)
    layer.start()
    new_prog = wm.restart_explorer()
    layer._tick()
    assert d.find_desktop_host() == new_prog
    assert directly_above(wm, 0x9000, new_prog)
    assert 0x9000 in wm.wins  # never destroyed: nothing ties it to Explorer
    layer.stop()


def test_window_that_slips_underneath_is_put_back_on_top(env):
    wm, d = env
    prog = wm.explorer_24h2()
    w = make_widget(wm)
    layer = d.Win32DesktopLayer("bottom")
    layer.attach(w, click_through=True)
    layer.start()
    sneaky = wm.new("SomeApp")
    wm.z.remove(sneaky)
    wm.z.insert(wm.z.index(prog), sneaky)  # between the widget and the desktop
    layer._tick()
    assert directly_above(wm, 0x9000, prog)
    assert wm.z.index(sneaky) < wm.z.index(0x9000)
    layer.stop()


def test_other_desktop_gadgets_are_not_fought(env):
    wm, d = env
    prog = wm.explorer_24h2()
    w = make_widget(wm)
    layer = d.Win32DesktopLayer("bottom")
    layer.attach(w, click_through=True)
    layer.start()
    gadget = wm.new("RainmeterMeterWindow", ex=C["WS_EX_TOOLWINDOW"] | C["WS_EX_LAYERED"])
    wm.z.remove(gadget)
    wm.z.insert(wm.z.index(prog), gadget)
    before = list(wm.z)
    layer._tick()
    assert wm.z == before
    layer.stop()


def test_fight_with_another_program_pauses(env):
    wm, d = env
    prog = wm.explorer_24h2()
    w = make_widget(wm)
    layer = d.Win32DesktopLayer("bottom")
    layer.attach(w, click_through=True)
    layer.start()
    sneaky = wm.new("Fighter")
    fixes = 0
    for _ in range(30):
        wm.z.remove(sneaky)
        wm.z.insert(wm.z.index(prog), sneaky)
        n = len(wm.calls)
        layer._tick()
        fixes += any(c[0] == "SetWindowPos" and c[1] == 0x9000 for c in wm.calls[n:])
    assert fixes <= d.FIGHT_LIMIT + 1
    layer.stop()


def test_veto_turns_foreign_zorder_changes_into_noops(env):
    wm, d = env
    wm.explorer_24h2()
    layer = d.Win32DesktopLayer("bottom")
    wp = WINDOWPOS(None, None, 0, 0, 0, 0, C["SWP_NOMOVE"] | C["SWP_NOSIZE"])
    msg = wintypes.MSG()
    msg.message = C["WM_WINDOWPOSCHANGING"]
    msg.lParam = ctypes.addressof(wp)
    layer.native_filter(ctypes.addressof(msg))
    assert wp.flags & C["SWP_NOZORDER"]
    assert layer._vetoes == 1
    other = wintypes.MSG()
    other.message = 0x0200  # WM_MOUSEMOVE
    layer.native_filter(ctypes.addressof(other))  # ignored, no crash
    layer.native_filter(0)  # garbage pointer guarded? must never raise
    assert layer._vetoes == 1


def test_hidden_widget_is_left_alone_and_explorer_missing_is_harmless(env):
    wm, d = env
    w = make_widget(wm)
    layer = d.Win32DesktopLayer("bottom")
    layer.attach(w, click_through=True)  # no Explorer at all
    layer.start()
    layer._tick()
    w._visible = False
    layer._tick()
    assert "desktop host" in d.describe_desktop()
    layer.stop()


def test_dropping_after_show_desktop_ignores_a_paused_fight_limiter(env):
    wm, d = env
    prog = wm.explorer_24h2()
    wm.taskbar()
    app = wm.new("Notepad")
    w = make_widget(wm)
    layer = d.Win32DesktopLayer("bottom")
    layer.attach(w, click_through=True)
    layer.start()
    sneaky = wm.new("Fighter")
    for _ in range(d.FIGHT_LIMIT + 3):  # trip the limiter
        wm.z.remove(sneaky)
        wm.z.insert(wm.z.index(prog), sneaky)
        layer._tick()
    wm.destroy(sneaky)
    wm.win_d_24h2()
    layer._tick()
    assert topmost(wm, 0x9000)
    wm.restore_app(app, prog)
    for _ in range(3):
        layer._tick()
    assert not topmost(wm, 0x9000)
    assert wm.z.index(app) < wm.z.index(0x9000)
    assert directly_above(wm, 0x9000, prog)
    layer.stop()


def test_new_and_clicked_widgets_come_to_the_front_of_our_group(env):
    """A zone created later (or clicked) must not hide under the older widgets; the group
    as a whole stays directly above the desktop, below every app window."""
    wm, d = env
    prog = wm.explorer_24h2()
    wm.taskbar()
    app = wm.new("Notepad")
    verse, zone_a, zone_b = make_widget(wm, 0x9000), make_widget(wm, 0x9100), make_widget(wm, 0x9200)
    layer = d.Win32DesktopLayer("bottom")
    for w in (verse, zone_a, zone_b):
        layer.attach(w)
    assert wm.z.index(0x9200) > wm.z.index(0x9100)  # attach alone puts the newest lowest
    layer.bring_to_front(zone_b)
    assert wm.z.index(0x9200) < wm.z.index(0x9100) and wm.z.index(0x9200) < wm.z.index(0x9000)
    layer.bring_to_front(zone_a)
    assert wm.z.index(0x9100) < wm.z.index(0x9200)
    assert wm.z.index(app) < min(wm.z.index(h) for h in (0x9000, 0x9100, 0x9200))  # still below the app
    layer._tick()
    assert wm.z.index(0x9100) < wm.z.index(0x9200)  # the keeper does not undo the order
    assert all(not topmost(wm, h) for h in (0x9000, 0x9100, 0x9200))
    assert max(wm.z.index(h) for h in (0x9000, 0x9100, 0x9200)) < wm.z.index(prog)


def test_our_own_stacking_order_survives_show_desktop(env):
    """A zone brought to the front stays in front of the other widgets when Win+D lifts
    them and when they sink back afterwards."""
    wm, d = env
    prog = wm.explorer_24h2()
    wm.taskbar()
    app = wm.new("Notepad")
    a, b = make_widget(wm, 0x9100), make_widget(wm, 0x9200)
    layer = d.Win32DesktopLayer("bottom")
    layer.attach(a)
    layer.attach(b)
    layer.start()
    layer.bring_to_front(b)
    assert wm.z.index(0x9200) < wm.z.index(0x9100)
    wm.win_d_24h2()
    layer._tick()
    assert topmost(wm, 0x9100) and topmost(wm, 0x9200)
    assert wm.z.index(0x9200) < wm.z.index(0x9100), "raised: order kept"
    wm.restore_app(app, prog)
    for _ in range(3):
        layer._tick()
    assert not topmost(wm, 0x9100) and not topmost(wm, 0x9200)
    assert wm.z.index(0x9200) < wm.z.index(0x9100), "dropped: order kept"
    assert wm.z.index(app) < wm.z.index(0x9200)
