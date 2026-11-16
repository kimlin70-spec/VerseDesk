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
    def __init__(self, rect, cls="CabinetWClass", maximized=False, minimized=False, visible=True, cloak=0):
        self.rect = rect  # the window rectangle (with the invisible borders)
        self.cls = cls
        self.maximized = maximized
        self.minimized = minimized
        self.visible = visible
        self.cloak = cloak  # 0 = on screen, 1 = cloaked by the program, 2 = by the shell (other virtual desktop)
        self.refuse_moves = False  # SetWindowPos returns FALSE (e.g. an elevated window)
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

    def open_explorer_windows(self):
        return [h for h, w in self.windows.items()
                if w.cls == "CabinetWClass" and w.visible and (w.cloak == 0 or w.cloak & 2)]

    def describe_all(self):
        return "\n".join(f"  0x{h:X} visible={w.visible} cloak={w.cloak}" for h, w in self.windows.items())

    def is_cloaked(self, hwnd):
        return self.windows[hwnd].cloak != 0

    def last_error(self):
        return 5

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
        return True

    def move(self, hwnd, rect):
        if self.windows[hwnd].refuse_moves:
            return False
        self.windows[hwnd].pending.append(("move", rect))
        self._maybe_pump(hwnd)
        return True

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
            self.callback(hwnd, True)
        return self.windows[hwnd]

    def activate(self, hwnd):
        if self.callback:
            self.callback(hwnd, False)


SLOT = {"enabled": True, "x": 300, "y": 120, "width": 900, "height": 600}
TARGET = (300, 120, 1200, 720)  # at 100 % native == logical


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(explorer_placer, "CHECK_MS", 5)
    monkeypatch.setattr(explorer_placer, "CONFIRM_MS", 10)
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
    w.callback(0x300, True)  # even if Windows reports it again (e.g. after a virtual desktop switch)
    w.activate(0x300)  # ...or the user clicks it
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
    w.callback(0x400, True)  # a repeated notification changes nothing
    settle()
    assert win.rect == (10, 10, 600, 500) and win.moves == 1
    placer.stop()


def test_a_closed_window_is_forgotten_so_a_reused_handle_is_placed_again(qapp, home, fast):
    placer, w, _ = make(home)
    w.open(0x500)
    settle()
    del w.windows[0x500]
    w.open(0x501)  # (handles come back only after very many other windows; any Explorer event forgets closed ones)
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


def test_a_maximised_window_of_a_slow_explorer_is_still_placed(qapp, home, fast):
    """Explorer carries out the restore late (first window after start-up, busy PC): keep waiting."""
    placer, w, _ = make(home)
    w.responsive = False
    win = w.open(0x801, rect=(-7, -7, 1927, 1047), maximized=True)
    settle(60)  # many looks later...
    assert len(win.pending) == 1 and win.pending[0][0] == "restore"  # asked once, nothing piled up, no move yet
    w.responsive = True
    w.pump(0x801)
    settle()
    assert not win.maximized and w.visible_rect(0x801) == TARGET
    placer.stop()


def test_a_window_minimised_right_after_it_was_moved_is_not_placed_again(qapp, home, fast):
    """Only a window that has not been moved yet is waited for while it is minimised."""
    placer, w, _ = make(home)
    w.responsive = False
    win = w.open(0x905)  # the move is asked for...
    w.responsive = True
    w.pump(0x905)  # ...carried out...
    win.minimized = True  # ...and the window is minimised before the app looks again
    settle(500)  # (longer than the app waits for a window that is not on screen)
    assert 0x905 in placer._seen and not placer._jobs  # it has had its turn
    win.minimized = False
    win.rect = (10, 10, 600, 500)  # brought up and moved by the user
    w.activate(0x905)
    settle()
    assert win.rect == (10, 10, 600, 500) and win.moves == 1
    placer.stop()


def test_a_maximised_window_that_opens_during_a_held_click_is_still_placed(qapp, home, fast):
    """The second click of the double-click is still down when the window appears maximised. The
    app's own restore changes the window's rectangle: that must not be taken for a drag."""
    placer, w, _ = make(home)
    w.button_down = True
    win = w.open(0x802, rect=(-7, -7, 1927, 1047), maximized=True)
    settle(40)
    assert win.restores == 0 and win.moves == 0 and win.maximized  # nothing while the button is held
    w.button_down = False
    settle()
    assert win.restores == 1 and w.visible_rect(0x802) == TARGET and placer.placed == 1
    placer.stop()


def test_a_click_while_a_maximised_window_is_being_restored_does_not_end_the_placing(qapp, home, fast):
    placer, w, _ = make(home)
    w.responsive = False
    win = w.open(0x803, rect=(-7, -7, 1927, 1047), maximized=True)  # the restore is asked for...
    w.button_down = True  # ...and the user clicks somewhere before Explorer has carried it out
    settle(30)
    w.responsive = True
    w.pump(0x803)
    assert win.restores == 1 and win.moves == 0
    w.button_down = False
    settle()
    assert w.visible_rect(0x803) == TARGET and win.moves == 1
    placer.stop()


def test_a_window_explorer_keeps_hidden_is_placed_when_it_is_first_shown(qapp, home, fast):
    """Windows 11 can keep an Explorer window ready in the background: it is not "open"."""
    w = FakeWatcher()
    hidden = w.open(0x810, visible=False)  # exists before the feature is switched on
    placer, w, _ = make(home, watcher=w)
    assert 0x810 not in placer._seen
    hidden.visible = True
    w.callback(0x810, True)  # shown: reported as a new window
    settle()
    assert w.visible_rect(0x810) == TARGET and hidden.moves == 1
    placer.stop()


def test_a_window_on_another_virtual_desktop_counts_as_open(qapp, home, fast):
    w = FakeWatcher()
    other_desktop = w.open(0x820, cloak=2)
    placer, w, _ = make(home, watcher=w)
    other_desktop.cloak = 0  # the user switches to that desktop and clicks the window
    w.activate(0x820)
    settle()
    assert other_desktop.moves == 0
    placer.stop()


def test_a_cloaked_window_is_placed_only_once_it_is_on_screen(qapp, home, fast):
    placer, w, _ = make(home)
    win = w.open(0x830, cloak=1)  # reported while still cloaked
    settle(40)
    assert win.moves == 0  # never moved while it cannot be seen
    win.cloak = 0  # ...uncloaked within the waiting time: placed without another notification
    settle()
    assert w.visible_rect(0x830) == TARGET and win.moves == 1
    placer.stop()


def test_a_window_that_stays_hidden_is_forgotten_and_placed_on_activation(qapp, home, fast):
    placer, w, _ = make(home)
    win = w.open(0x840, cloak=1)
    settle(500)  # longer than the waiting time
    assert win.moves == 0 and 0x840 not in placer._seen and not placer._jobs
    win.cloak = 0
    w.activate(0x840)  # the user opens it: Windows reports the activation
    settle()
    assert w.visible_rect(0x840) == TARGET and win.moves == 1
    w.activate(0x840)  # later activations (every click on it) do nothing
    win.rect = (10, 10, 600, 500)
    w.activate(0x840)
    settle()
    assert win.rect == (10, 10, 600, 500) and win.moves == 1
    placer.stop()


def test_activating_a_window_that_was_already_open_does_nothing(qapp, home, fast):
    w = FakeWatcher()
    old = w.open(0x850)
    placer, w, _ = make(home, watcher=w)
    for _ in range(3):
        w.activate(0x850)
    settle()
    assert old.moves == 0
    placer.stop()


def test_a_refused_move_ends_quietly(qapp, home, fast, caplog):
    placer, w, _ = make(home)
    win = w.open(0x860, notify=False)
    win.refuse_moves = True  # e.g. an Explorer started "as administrator"
    w.callback(0x860, True)
    settle()
    assert win.moves == 0 and not placer._jobs
    assert any("refused the move" in r.message for r in caplog.records)
    placer.stop()


def test_a_window_that_keeps_its_own_size_is_left_after_two_tries(qapp, home, fast, caplog):
    """A slot smaller than the window's minimum size: the same result every time."""
    placer, w, _ = make(home)
    win = w.open(0x870, notify=False)

    def minimum_size(window):
        l, t, r, b = window.rect
        window.rect = (l, t, max(r, l + 1100), max(b, t + 800))
        window.after_move = minimum_size

    win.after_move = minimum_size
    w.callback(0x870, True)
    settle(250)
    assert win.moves == 2 and not placer._jobs  # asked twice, then left alone - not 40 idle looks
    assert any("keeps its own size" in r.message for r in caplog.records)
    placer.stop()


def test_a_late_change_after_the_window_sat_in_the_slot_is_corrected_once(qapp, home, fast):
    """E.g. the window resizes itself for another monitor's scale a moment after the move."""
    placer, w, _ = make(home)
    win = w.open(0x880)
    assert w.visible_rect(0x880) == TARGET  # the first look already found it in the slot...
    l, t, r, b = win.rect
    win.rect = (l, t, r + 150, b + 100)  # ...then it changes by itself
    settle()
    assert w.visible_rect(0x880) == TARGET and win.moves == 2 and placer.placed == 1
    placer.stop()


def test_a_minimised_window_is_left_alone(qapp, home, fast):
    placer, w, _ = make(home)
    win = w.open(0x900, minimized=True)
    settle()
    assert win.moves == 0
    placer.stop()


def test_a_window_that_opens_minimised_is_placed_when_it_is_brought_up(qapp, home, fast):
    """Like a window that is still hidden: it has not been on screen yet, so it is not used up."""
    placer, w, _ = make(home)
    soon = w.open(0x901, minimized=True)
    settle(30)
    soon.minimized = False  # brought up within the waiting time: placed without another notification
    settle()
    assert w.visible_rect(0x901) == TARGET and soon.moves == 1

    late = w.open(0x902, minimized=True)
    settle(500)  # longer than the waiting time
    assert late.moves == 0 and 0x902 not in placer._seen and not placer._jobs
    late.minimized = False
    w.activate(0x902)  # the user clicks its taskbar button: Windows reports the activation
    settle()
    assert w.visible_rect(0x902) == TARGET and late.moves == 1
    placer.stop()


def test_minimising_never_makes_a_window_the_users_own_be_placed_again(qapp, home, fast):
    w = FakeWatcher()
    old = w.open(0x903, minimized=True)  # was open (minimised) before the feature was switched on
    placer, w, _ = make(home, watcher=w)
    old.minimized = False
    w.activate(0x903)
    settle()
    assert old.moves == 0

    win = w.open(0x904)  # placed once...
    settle()
    assert win.moves == 1
    win.minimized = True  # ...then minimised, brought up again and moved by the user
    w.activate(0x904)
    settle(500)
    win.minimized = False
    win.rect = (10, 10, 600, 500)
    w.activate(0x904)
    settle()
    assert win.rect == (10, 10, 600, 500) and win.moves == 1
    placer.stop()


def test_crossing_to_a_monitor_with_another_scale_is_corrected(qapp, home, fast):
    """Windows makes the window resize itself for the new scale: look again and correct once."""
    placer, w, _ = make(home)
    win = w.open(0xA00, notify=False)

    def dpi_change(window):
        l, t, r, b = window.rect
        window.rect = (l, t, l + int((r - l) * 1.25), t + int((b - t) * 1.25))

    win.after_move = dpi_change
    w.callback(0xA00, True)
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
    w.callback(0xC00, True)
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


def test_grabbing_the_window_right_after_it_opened_stops_corrections(qapp, home, fast, caplog):
    caplog.set_level("INFO", logger="versedesk.explorer")
    placer, w, _ = make(home)
    w.responsive = False
    win = w.open(0xF00)
    w.button_down = True  # the user starts dragging before the first move was even carried out
    w.responsive = True
    w.pump(0xF00)
    settle()
    assert win.moves == 1 and not placer._jobs  # no second request
    said = [r.message for r in caplog.records if "mouse button down after 1 move(s)" in r.message]
    assert len(said) == 1 and "0xF00" in said[0]  # ...and log.txt says why this window was left
    placer.stop()


def test_a_click_after_the_window_was_seen_in_the_slot_adds_nothing_to_the_log(qapp, home, fast, caplog, monkeypatch):
    caplog.set_level("INFO", logger="versedesk.explorer")
    monkeypatch.setattr(explorer_placer, "CONFIRM_MS", 200)
    placer, w, _ = make(home)
    w.open(0xF01)
    settle(80)  # moved, then seen in the slot; only the confirming look is still to come
    assert placer.placed == 1 and placer._jobs
    w.button_down = True
    settle(350)
    assert not placer._jobs and placer.placed == 1
    assert sum("placed in the slot" in r.message for r in caplog.records) == 1
    assert not any("mouse button down" in r.message for r in caplog.records)
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


def test_a_slot_saved_on_a_bigger_monitor_is_shown_smaller_here(qapp, home, fast):
    """Laptop taken off its docking station: the saved size must not hang over the screen."""
    small = [ScreenInfo(Rect(0, 0, 1366, 728), 1.0)]
    placer, w, store = make(home, slot={"enabled": True, "x": 100, "y": 50, "width": 1600, "height": 1000}, screens=small)
    assert placer.slot_rect() == Rect(0, 0, 1366, 728)
    w.open(0x1500)
    settle()
    assert w.visible_rect(0x1500) == (0, 0, 1366, 728)
    assert store.settings.explorer_window.width == 1600  # the saved numbers stay for the big monitor
    placer.stop()


def test_quitting_and_edit_mode_never_fail_because_of_this_feature(qapp, home, fast):
    class Exploding(FakeWatcher):
        def stop(self):
            raise OSError("boom")

    placer, w, _ = make(home, watcher=Exploding())
    placer.set_edit_mode(True)
    placer._frame.hide = lambda: (_ for _ in ()).throw(RuntimeError("frame gone"))
    placer.set_edit_mode(False)  # must not raise
    placer.stop()  # must not raise
    assert "explorer window slot" in placer.diagnostics()
    del placer._frame.hide  # (tidy up: the frame of this test must not stay on screen)
    placer._frame.hide()


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
