"""versedesk/win32/explorer.py against a minimal stand-in for the Win32 API (runs on any OS):
catches wrong names, flags and message parsing before the real-Windows check in CI."""

import ctypes
import importlib
import sys
import types
from ctypes import wintypes

import pytest
from PySide6.QtTest import QTest

SHELLHOOK = 0xC123


class FakeApi(types.SimpleNamespace):
    def __init__(self):
        super().__init__(
            SWP_NOZORDER=0x4, SWP_NOACTIVATE=0x10, SWP_NOOWNERZORDER=0x200, SWP_ASYNCWINDOWPOS=0x4000,
            SW_SHOWNOACTIVATE=4, HSHELL_WINDOWCREATED=1, VK_LBUTTON=1, VK_RBUTTON=2, SM_SWAPBUTTON=23,
        )
        self.classes = {0x10: "CabinetWClass", 0x11: "Notepad", 0x12: "CabinetWClass"}
        self.registered = []
        self.deregistered = []
        self.moves = []
        self.shows = []
        self.keys = {}
        self.swapped = 0
        self.visible_frames = {0x10: (100, 100, 900, 600)}

    def RegisterWindowMessageW(self, name):  # noqa: N802
        assert name == "SHELLHOOK"
        return SHELLHOOK

    def RegisterShellHookWindow(self, hwnd):  # noqa: N802
        self.registered.append(hwnd)
        return 1

    def DeregisterShellHookWindow(self, hwnd):  # noqa: N802
        self.deregistered.append(hwnd)
        return 1

    def IsWindow(self, hwnd):  # noqa: N802
        return 1 if hwnd in self.classes or hwnd in self.registered else 0

    def IsWindowVisible(self, hwnd):  # noqa: N802
        return 1

    def IsIconic(self, hwnd):  # noqa: N802
        return 0

    def IsZoomed(self, hwnd):  # noqa: N802
        return 1 if hwnd == 0x12 else 0

    def class_name(self, hwnd):
        return self.classes.get(hwnd, "")

    def top_level_windows(self):
        return list(self.classes)

    def window_rect(self, hwnd):
        return (93, 100, 907, 607)

    def frame_bounds(self, hwnd):
        return self.visible_frames.get(hwnd)

    def describe(self, hwnd):
        return f"0x{hwnd:X}"

    def h(self, value):
        return int(value or 0)

    def GetSystemMetrics(self, index):  # noqa: N802
        assert index == 23
        return self.swapped

    def GetAsyncKeyState(self, key):  # noqa: N802
        return self.keys.get(key, 0)

    def SetWindowPos(self, hwnd, after, x, y, w, h, flags):  # noqa: N802
        self.moves.append((hwnd, after, x, y, w, h, flags))
        return 1

    def ShowWindowAsync(self, hwnd, cmd):  # noqa: N802
        self.shows.append((hwnd, cmd))
        return 1


@pytest.fixture
def explorer(monkeypatch, qapp):
    fake = FakeApi()
    monkeypatch.setitem(sys.modules, "versedesk.win32.api", fake)
    import versedesk.win32 as win32_package

    monkeypatch.setattr(win32_package, "api", fake, raising=False)
    sys.modules.pop("versedesk.win32.explorer", None)
    module = importlib.import_module("versedesk.win32.explorer")
    yield module, fake
    sys.modules.pop("versedesk.win32.explorer", None)


def _post(watcher, message, wparam, lparam):
    msg = wintypes.MSG()
    msg.message, msg.wParam, msg.lParam = message, wparam, lparam
    watcher._receiver.nativeEvent(b"windows_generic_MSG", ctypes.addressof(msg))


def test_new_window_notifications_reach_the_callback(explorer):
    module, fake = explorer
    watcher = module.ExplorerWatcher()
    seen = []
    assert watcher.start(seen.append) is True
    assert len(fake.registered) == 1 and fake.registered[0] == int(watcher._receiver.winId())
    _post(watcher, SHELLHOOK, 1, 0x10)  # HSHELL_WINDOWCREATED
    _post(watcher, SHELLHOOK, 0x8001, 0x12)  # the same with the high bit some builds set
    _post(watcher, SHELLHOOK, 4, 0x11)  # HSHELL_WINDOWACTIVATED: not ours
    _post(watcher, 0x0046, 1, 0x11)  # some other message
    QTest.qWait(20)
    assert seen == [0x10, 0x12]
    watcher.stop()
    assert fake.deregistered == fake.registered
    _post(watcher, SHELLHOOK, 1, 0x10)  # after stop: ignored
    QTest.qWait(20)
    assert seen == [0x10, 0x12]


def test_restart_registers_again_and_refresh_is_harmless(explorer):
    module, fake = explorer
    watcher = module.ExplorerWatcher()
    watcher.start(lambda h: None)
    watcher.refresh()  # same native window: nothing to do
    assert len(fake.registered) == 1
    watcher.stop()
    watcher.refresh()  # stopped: nothing
    watcher.start(lambda h: None)
    assert len(fake.registered) == 2
    watcher.stop()


def test_looking_at_windows(explorer):
    module, fake = explorer
    watcher = module.ExplorerWatcher()
    assert watcher.explorer_windows() == [0x10, 0x12]
    assert watcher.is_explorer_window(0x10) and not watcher.is_explorer_window(0x11)
    assert not watcher.is_explorer_window(0x99)  # no such window
    assert watcher.exists(0x10) and not watcher.exists(0x99)
    assert watcher.is_visible(0x10) and not watcher.is_minimized(0x10)
    assert watcher.is_maximized(0x12) and not watcher.is_maximized(0x10)
    assert watcher.window_rect(0x10) == (93, 100, 907, 607)
    assert watcher.visible_rect(0x10) == (100, 100, 900, 600) and watcher.visible_rect(0x12) is None


def test_moving_never_waits_for_explorer(explorer):
    module, fake = explorer
    watcher = module.ExplorerWatcher()
    watcher.move(0x10, (293, 120, 1207, 727))
    hwnd, after, x, y, w, h, flags = fake.moves[0]
    assert (hwnd, after, x, y, w, h) == (0x10, None, 293, 120, 914, 607)
    assert flags & 0x4000, "SWP_ASYNCWINDOWPOS: a hung Explorer must not hang VerseDesk"
    assert flags & 0x4 and flags & 0x10, "no z-order change, no activation"
    watcher.restore(0x12)
    assert fake.shows == [(0x12, 4)]


def test_mouse_button_follows_swapped_buttons(explorer):
    module, fake = explorer
    watcher = module.ExplorerWatcher()
    assert watcher.mouse_button_down() is False
    fake.keys = {1: -32768}  # left button held (high bit set in a signed short)
    assert watcher.mouse_button_down() is True
    fake.swapped = 1  # left-handed mouse: the right physical button is the main one
    assert watcher.mouse_button_down() is False
    fake.keys = {2: -32768}
    assert watcher.mouse_button_down() is True
