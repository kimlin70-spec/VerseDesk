"""Placing new Explorer windows in the slot, against a fake window system.

The fake behaves like Windows where it matters: move requests are asynchronous (carried out
later), windows have invisible borders, a maximised window must be restored first, a window
that crosses to a monitor with another scale resizes itself, and Explorer can be slow.
"""

import pytest
from PySide6.QtTest import QTest

from versedesk import explorer_placer
from versedesk.explorer_placer import ExplorerPlacer
from versedesk.explorer_slot import ScreenInfo
from versedesk.geometry import Rect
from versedesk.settings import SettingsStore

BORDER = 7  # invisible resize border left/right/bottom


class FakeWindow:
    def __init__(self, rect, cls="CabinetWClass", maximized=False, minimized=False, visible=True):
        self.rect = rect  # the window rectangle (with the invisible borders)
        self.cls = cls
        self.maximized = maximized
        self.minimized = minimized
        self.visible = visible
        self.pending = []  # requests Explorer has not carried out yet
        self.moves = 0
        self.restores = 0
        self.after_move = None  # hook: what the window does to itself after a move


class FakeWatcher:
    """What versedesk.win32.explorer provides, without Windows."""

    def __init__(self):
        self.windows: dict[int, FakeWindow] = {}
        self.callback = None
        self.button_down = False
        self.responsive = True  # False: requests pile up until pump()
        self.started = 0
        self.stopped = 0
        self.refreshed = 0

    # -- the interface used by ExplorerPlacer
    def start(self, callback) -> bool:
        self.callback = callback
        self.started += 1
        return True

    def stop(self) -> None:
        self.callback = None
        self.stopped += 1

    def refresh(self) -> None:
        self.refreshed += 1

    def explorer_windows(self):
        return [h for h, w in self.windows.items() if w.cls == "CabinetWClass"]

    def is_explorer_window(self, hwnd):
        return hwnd in self.windows and self.windows[hwnd].cls == "CabinetWClass"

    def exists(self, hwnd):
        return hwnd in self.windows

    def is_visible(self, hwnd):
        return self.windows[hwnd].visible

    def is_minimized(self, hwnd):
        return self.windows[hwnd].minimized

    def is_maximized(self, hwnd):
        return self.windows[hwnd].maximized

    def window_rect(self, hwnd):
        return self.windows[hwnd].rect

    def visible_rect(self, hwnd):
        l, t, r, b = self.windows[hwnd].rect
        if self.windows[hwnd].maximized:
            return (l + BORDER, t + BORDER, r - BORDER, b - BORDER)
        return (l + BORDER, t, r - BORDER, b - BORDER)

    def restore(self, hwnd):
        self.windows[hwnd].pending.append(("restore", None))
        self._maybe_pump(hwnd)

    def move(self, hwnd, rect):
        self.windows[hwnd].pending.append(("move", rect))
        self._maybe_pump(hwnd)

    def mouse_button_down(self):
        return self.button_down

    def describe(self, hwnd):
        return f"0x{hwnd:X}"

    # -- the test's side
    def _maybe_pump(self, hwnd):
        if self.responsive:
            self.pump(hwnd)

    def pump(self, hwnd):
        w = self.windows[hwnd]
        while w.pending:
            kind, rect = w.pending.pop(0)
            if kind == "restore":
                w.maximized = False
                w.restores += 1
                w.rect = (50, 60, 850, 660)  # its last normal place
            else:
                w.rect = rect
                w.moves += 1
                if w.after_move:
                    hook, w.after_move = w.after_move, None
                    hook(w)

    def open(self, hwnd, rect=(93, 100, 907, 607), notify=True, **kw):
        self.windows[hwnd] = FakeWindow(rect, **kw)
        if notify and self.callback:
            self.callback(hwnd)
        return self.windows[hwnd]


SLOT = {"enabled": True, "x": 300, "y": 120, "width": 900, "height": 600}
TARGET = (300, 120, 1200, 720)  # at 100 % native == logical


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(explorer_placer, "CHECK_MS", 5)
    monkeypatch.setattr(explorer_placer, "MOUSE_WAIT_MS", 5)


def make(home, slot=SLOT, screens=None, watcher=None):
    import json

    home.mkdir(parents=True, exist_ok=True)
    (home / "settings.json").write_text(json.dumps({"explorer_window": slot}), encoding="utf-8")
    store = SettingsStore(home / "settings.json")
    store.load()
    screens = screens or [ScreenInfo(Rect(0, 0, 1920, 1080), 1.0)]
    watcher = watcher if watcher is not None else FakeWatcher()
    placer = ExplorerPlacer(
        store,
        work_areas=lambda: ([s.rect for s in screens], screens[0].rect),
        screens=lambda: screens,
        apply_reload=lambda result: None,
        watcher=watcher,
    )
    placer.start()
    return placer, watcher, store


def settle(ms=120):
    QTest.qWait(ms)


def test_a_new_explorer_window_lands_exactly_in_the_slot(qapp, home, fast):
    placer, w, _ = make(home)
    win = w.open(0x100)
    settle()
    assert w.visible_rect(0x100) == TARGET  # what is seen equals the slot...
    assert win.rect == (293, 120, 1207, 727)  # ...so the window rectangle includes the invisible borders
    assert win.moves == 1 and placer.placed == 1
    placer.stop()


def test_only_explorer_windows_are_touched(qapp, home, fast):
    placer, w, _ = make(home)
    other = w.open(0x200, cls="Notepad")
    dialog = w.open(0x201, cls="#32770")
    settle()
    assert other.moves == 0 and dialog.moves == 0 and placer.placed == 0
    placer.stop()


def test_windows_that_were_already_open_are_left_alone(qapp, home, fast):
    w = FakeWatcher()
    old = w.open(0x300)  # open before the feature starts
    placer, w, _ = make(home, watcher=w)
    w.callback(0x300)  # even if Windows reports it again (e.g. after a virtual desktop switch)
    settle()
    assert old.moves == 0
    new = w.open(0x301)
    settle()
    assert new.moves == 1 and old.moves == 0
    placer.stop()


def test_a_window_is_placed_once_and_then_belongs_to_the_user(qapp, home, fast):
    placer, w, _ = make(home)
    win = w.open(0x400)
    settle()
    win.rect = (10, 10, 600, 500)  # the user drags it somewhere else
    w.callback(0x400)  # a repeated notification changes nothing
    settle()
    assert win.rect == (10, 10, 600, 500) and win.moves == 1
    placer.stop()


def test_a_closed_window_is_forgotten_so_a_reused_handle_is_placed_again(qapp, home, fast):
    placer, w, _ = make(home)
    w.open(0x500)
    settle()
    del w.windows[0x500]
    w.open(0x999, cls="Notepad")  # any later event prunes closed windows
    again = w.open(0x500)
    settle()
    assert again.moves == 1
    placer.stop()


def test_off_by_default_and_nothing_is_watched(qapp, home, fast):
    placer, w, _ = make(home, slot={"enabled": False})
    assert w.started == 0
    win = w.open(0x600)
    settle()
    assert win.moves == 0
    placer.stop()
    assert w.stopped == 0


def test_switching_on_and_off_follows_the_settings(qapp, home, fast):
    placer, w, store = make(home, slot={"enabled": False})
    store.update(lambda s: setattr(s.explorer_window, "enabled", True))
    placer.sync_from_settings()
    assert w.started == 1
    first = w.open(0x700)
    settle()
    assert first.moves == 1
    store.update(lambda s: setattr(s.explorer_window, "enabled", False))
    placer.sync_from_settings()
    assert w.stopped == 1
    second = w.open(0x701)
    settle()
    assert second.moves == 0
    placer.stop()


def test_a_maximised_window_is_restored_and_then_placed(qapp, home, fast):
    placer, w, _ = make(home)
    win = w.open(0x800, rect=(-7, -7, 1927, 1047), maximized=True)
    settle()
    assert win.restores == 1 and not win.maximized
    assert w.visible_rect(0x800) == TARGET
    placer.stop()


def test_a_minimised_window_is_left_alone(qapp, home, fast):
    placer, w, _ = make(home)
    win = w.open(0x900, minimized=True)
    settle()
    assert win.moves == 0
    placer.stop()


def test_crossing_to_a_monitor_with_another_scale_is_corrected(qapp, home, fast):
    """Windows makes the window resize itself for the new scale: look again and correct once."""
    placer, w, _ = make(home)
    win = w.open(0xA00, notify=False)

    def dpi_change(window):
        l, t, r, b = window.rect
        window.rect = (l, t, l + int((r - l) * 1.25), t + int((b - t) * 1.25))

    win.after_move = dpi_change
    w.callback(0xA00)
    settle()
    assert w.visible_rect(0xA00) == TARGET and win.moves == 2
    placer.stop()


def test_a_slow_explorer_is_waited_for_without_piling_up_requests(qapp, home, fast):
    placer, w, _ = make(home)
    w.responsive = False
    win = w.open(0xB00)
    settle(60)
    assert len(win.pending) == 1  # one request, not one per look
    w.responsive = True
    w.pump(0xB00)
    settle()
    assert w.visible_rect(0xB00) == TARGET and win.moves == 1
    placer.stop()


def test_a_window_that_will_not_fit_is_given_up_after_a_few_moves(qapp, home, fast, caplog):
    placer, w, _ = make(home)
    win = w.open(0xC00, notify=False)
    stubborn = {"n": 0}

    def refuse(window):
        stubborn["n"] += 1
        window.rect = (0, 0, 800 + stubborn["n"], 500)  # always somewhere else
        window.after_move = refuse

    win.after_move = refuse
    w.callback(0xC00)
    settle(200)
    assert win.moves == explorer_placer.MAX_MOVES  # bounded: no endless tug of war
    assert placer.placed == 0 and not placer._jobs
    placer.stop()


def test_nothing_moves_while_a_mouse_button_is_held(qapp, home, fast):
    """A tab dragged out of an Explorer window becomes a new window under the mouse."""
    placer, w, _ = make(home)
    w.button_down = True
    win = w.open(0xD00)
    settle(40)
    assert win.moves == 0
    win.rect = (500, 300, 1300, 900)  # it follows the mouse
    w.button_down = False
    settle()
    assert win.moves == 0 and win.rect == (500, 300, 1300, 900)  # left where the user dropped it
    placer.stop()


def test_a_slow_double_click_release_still_gets_the_window_placed(qapp, home, fast):
    placer, w, _ = make(home)
    w.button_down = True  # the second click is still held when the window appears
    win = w.open(0xE00)
    settle(40)
    assert win.moves == 0
    w.button_down = False  # released without the window having moved
    settle()
    assert w.visible_rect(0xE00) == TARGET
    placer.stop()


def test_grabbing_the_window_right_after_it_opened_stops_corrections(qapp, home, fast):
    placer, w, _ = make(home)
    w.responsive = False
    win = w.open(0xF00)
    w.button_down = True  # the user starts dragging before the first move was even carried out
    w.responsive = True
    w.pump(0xF00)
    settle()
    assert win.moves == 1 and not placer._jobs  # no second request
    placer.stop()


def test_scaled_screen_and_second_monitor(qapp, home, fast):
    screens = [ScreenInfo(Rect(0, 0, 1280, 720), 1.5), ScreenInfo(Rect(1920, 0, 2560, 1440), 1.0)]
    placer, w, _ = make(home, slot={"enabled": True, "x": 100, "y": 60, "width": 800, "height": 500}, screens=screens)
    w.open(0x1100)
    settle()
    assert w.visible_rect(0x1100) == (150, 90, 1350, 840)  # 150 % main screen
    placer.stop()
    placer2, w2, _ = make(home, slot={"enabled": True, "x": 2100, "y": 200, "width": 900, "height": 600}, screens=screens)
    w2.open(0x1200)
    settle()
    assert w2.visible_rect(0x1200) == (2100, 200, 3000, 800)  # the 100 % monitor to the right
    placer2.stop()


def test_a_slot_on_a_monitor_that_is_gone_moves_to_the_main_screen(qapp, home, fast):
    placer, w, _ = make(home, slot={"enabled": True, "x": 5000, "y": 200, "width": 900, "height": 600})
    r = placer.slot_rect()
    assert Rect(0, 0, 1920, 1080).contains_rect(r) and (r.w, r.h) == (900, 600)
    placer.stop()


def test_before_the_user_placed_it_the_slot_is_centred(qapp, home, fast):
    placer, w, _ = make(home, slot={"enabled": True})
    assert placer.slot_rect() == Rect(510, 240, 900, 600)
    placer.stop()


def test_the_frame_shows_only_in_edit_mode_and_saves_what_the_user_drags(qapp, home, fast):
    import json

    placer, w, store = make(home)
    assert placer._frame is None
    placer.set_edit_mode(True)
    frame = placer._frame
    assert frame.isVisible()
    assert (frame.x(), frame.y(), frame.width(), frame.height()) == (300, 120, 900, 600)
    frame.setGeometry(400, 200, 1000, 640)
    frame.geometry_edited.emit(400, 200, 1000, 640)
    saved = json.loads((home / "settings.json").read_text(encoding="utf-8"))["explorer_window"]
    assert saved == {"enabled": True, "x": 400, "y": 200, "width": 1000, "height": 640}
    win = w.open(0x1300)  # the new place is used at once
    settle()
    assert w.visible_rect(0x1300) == (400, 200, 1400, 840)
    placer.set_edit_mode(False)
    assert not frame.isVisible()
    placer.stop()


def test_the_frame_is_not_shown_while_the_feature_is_off(qapp, home, fast):
    placer, w, store = make(home, slot={"enabled": False})
    placer.set_edit_mode(True)
    assert placer._frame is None
    store.update(lambda s: setattr(s.explorer_window, "enabled", True))
    placer.sync_from_settings()
    assert placer._frame is not None and placer._frame.isVisible()
    placer.stop()
    assert not placer._frame.isVisible()


def test_a_frame_dragged_off_screen_is_brought_back(qapp, home, fast):
    placer, w, store = make(home)
    placer.set_edit_mode(True)
    placer._frame.geometry_edited.emit(1800, 900, 900, 600)  # mostly off the 1920x1080 screen
    s = store.settings.explorer_window
    assert Rect(0, 0, 1920, 1080).contains_rect(Rect(s.x, s.y, s.width, s.height))
    placer.stop()


def test_errors_in_the_watcher_never_escape(qapp, home, fast):
    class Broken(FakeWatcher):
        def window_rect(self, hwnd):
            raise OSError("access denied")

    placer, w, _ = make(home, watcher=Broken())
    w.open(0x1400)  # must not raise
    settle(30)
    assert not placer._jobs
    placer.stop()


def test_without_a_watcher_the_setting_and_frame_still_work(qapp, home, fast):
    import json

    home.mkdir(parents=True, exist_ok=True)
    (home / "settings.json").write_text(json.dumps({"explorer_window": SLOT}), encoding="utf-8")
    store = SettingsStore(home / "settings.json")
    store.load()
    area = Rect(0, 0, 1920, 1080)
    placer = ExplorerPlacer(store, work_areas=lambda: ([area], area), screens=lambda: [ScreenInfo(area, 1.0)],
                            apply_reload=lambda r: None, watcher=None)
    placer.start()
    placer.set_edit_mode(True)
    assert placer._frame.isVisible() and "not watching" in placer.diagnostics()
    placer.stop()
