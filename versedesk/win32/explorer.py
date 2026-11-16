"""Windows side of "탐색기 창 자리 고정": notice File Explorer windows as they appear, measure and move them.

Noticing: the shell hook.  ``RegisterShellHookWindow`` makes Windows post a "SHELLHOOK"
message to one of our windows whenever a top-level application window is shown
(HSHELL_WINDOWCREATED) or activated (HSHELL_WINDOWACTIVATED) - the notifications the taskbar
itself uses for its buttons.  It is far quieter than a system-wide event hook: nothing
arrives for menus, tooltips or child controls.  The receiving window is a Qt widget that is
never shown, so no window procedure of our own is involved.  (Checked on the real Windows
desktops of the CI runners, Windows 10 and 11 layouts.)

Moving: always asynchronously (SWP_ASYNCWINDOWPOS, ShowWindowAsync): the request is posted
to Explorer's own thread, so a busy or hung Explorer can never make VerseDesk wait.  For the
same reason nothing here sends a message to an Explorer window.

``ExplorerWatcher`` is the object ``ExplorerPlacer`` talks to; it holds no policy.
"""

from __future__ import annotations

import logging
from ctypes import wintypes
from typing import Callable

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

from versedesk.win32 import api

log = logging.getLogger("versedesk.explorer")

EXPLORER_CLASS = "CabinetWClass"  # File Explorer windows (and the classic Control Panel) on Windows 10/11
MOVE_FLAGS = api.SWP_NOZORDER | api.SWP_NOACTIVATE | api.SWP_NOOWNERZORDER | api.SWP_ASYNCWINDOWPOS
SHOWN_OR_ACTIVATED = (api.HSHELL_WINDOWCREATED, api.HSHELL_WINDOWACTIVATED)  # the only codes whose lParam is read


class _Receiver(QWidget):
    """Never shown. Windows posts the shell hook messages to its native window."""

    def __init__(self, on_message: Callable[[object], None], on_new_handle: Callable[[], None]):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("explorer-watch")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._on_message = on_message
        self._on_new_handle = on_new_handle

    def nativeEvent(self, event_type, message):  # noqa: N802 - Qt naming
        try:
            self._on_message(message)
        except Exception:
            pass
        return False, 0  # always let Qt handle the message normally

    def event(self, event):
        if event.type() == QEvent.Type.WinIdChange:
            # Qt is in the middle of creating or destroying the native window: only take
            # note now, and register the new window once Qt has finished.
            QTimer.singleShot(0, self._handle_changed)
        return super().event(event)

    def _handle_changed(self) -> None:
        try:
            self._on_new_handle()
        except Exception:
            pass


class ExplorerWatcher:
    def __init__(self):
        self._message = api.RegisterWindowMessageW("SHELLHOOK")
        self._taskbar_created = api.RegisterWindowMessageW("TaskbarCreated")  # broadcast when Explorer (re)starts
        self._receiver: _Receiver | None = None
        self._registered = 0
        self._callback: Callable[[int, bool], None] | None = None

    # ------------------------------------------------------------------ watching

    def start(self, callback: Callable[[int, bool], None]) -> bool:
        """Call ``callback(hwnd, created)`` on the GUI thread when an Explorer window is shown
        (created=True) or activated (created=False)."""
        self._callback = callback
        if self._receiver is None:
            self._receiver = _Receiver(self._on_native, self.refresh)
        return self._register()

    def stop(self) -> None:
        self._callback = None
        if self._registered:
            if api.IsWindow(self._registered):
                api.DeregisterShellHookWindow(self._registered)
            self._registered = 0

    def refresh(self) -> None:
        """Make sure the hook is on the receiver's current native window."""
        if self._callback is not None and self._receiver is not None:
            self._register()

    def _register(self, again: bool = False) -> bool:
        if not QGuiApplication.screens():
            return False  # no screen at the moment (e.g. remote session closing): try at the next refresh
        hwnd = int(self._receiver.winId())  # creates the native window on first use
        if hwnd == self._registered and api.IsWindow(hwnd) and not again:
            return True
        if self._registered:
            log.info("explorer window slot: registering the window watcher again (%s)",
                     "Explorer restarted" if again else "new receiver window")
        if self._registered and api.IsWindow(self._registered):
            api.DeregisterShellHookWindow(self._registered)
        self._registered = hwnd if api.RegisterShellHookWindow(hwnd) else 0
        if not self._registered:
            log.warning("RegisterShellHookWindow failed for %s (error %s)", api.describe(hwnd), api.last_error())
        return bool(self._registered)

    def _on_native(self, message) -> None:
        address = int(message)
        if not address or self._callback is None:
            return
        msg = wintypes.MSG.from_address(address)
        if msg.message == self._taskbar_created:
            # Explorer restarted: register again in case the new shell does not know us
            QTimer.singleShot(0, lambda: self._callback is not None and self._register(again=True))
            return
        if msg.message != self._message:
            return
        code = msg.wParam & 0x7FFF
        if code not in SHOWN_OR_ACTIVATED:
            return
        hwnd = api.h(msg.lParam) & 0xFFFFFFFFFFFFFFFF
        if not hwnd or api.class_name(hwnd) != EXPLORER_CLASS:
            return  # another program's window: nothing more to do, no timer
        created = code == api.HSHELL_WINDOWCREATED
        # out of the message filter first; the callback looks at and moves windows
        QTimer.singleShot(0, lambda: self._deliver(hwnd, created))

    def _deliver(self, hwnd: int, created: bool) -> None:
        callback = self._callback
        if callback is not None:
            callback(hwnd, created)

    # ------------------------------------------------------------------ looking at windows

    def _all_explorer_windows(self) -> list[int]:
        return [w for w in api.top_level_windows() if api.class_name(w) == EXPLORER_CLASS]

    def open_explorer_windows(self) -> list[int]:
        """Explorer windows the user has open: visible (minimised counts), and not cloaked
        unless by the shell (= on another virtual desktop). A window Explorer keeps hidden
        for a faster start is not open."""
        out = []
        for w in self._all_explorer_windows():
            cloak = api.cloak_state(w)
            if api.IsWindowVisible(w) and (cloak == 0 or cloak & api.DWM_CLOAKED_SHELL):
                out.append(w)
        return out

    def describe_all(self) -> str:
        """One line per Explorer window, for log.txt (what was open when the feature started)."""
        lines = []
        for w in self._all_explorer_windows():
            lines.append(f"  {api.describe(w)} cloak={api.cloak_state(w)} minimised={bool(api.IsIconic(w))}")
        return "\n".join(lines) or "  (no Explorer window exists)"

    def is_explorer_window(self, hwnd: int) -> bool:
        return bool(api.IsWindow(hwnd)) and api.class_name(hwnd) == EXPLORER_CLASS

    def exists(self, hwnd: int) -> bool:
        return bool(api.IsWindow(hwnd))

    def is_visible(self, hwnd: int) -> bool:
        return bool(api.IsWindowVisible(hwnd))

    def is_cloaked(self, hwnd: int) -> bool:
        return api.is_cloaked(hwnd)

    def is_minimized(self, hwnd: int) -> bool:
        return bool(api.IsIconic(hwnd))

    def is_maximized(self, hwnd: int) -> bool:
        return bool(api.IsZoomed(hwnd))

    def window_rect(self, hwnd: int) -> tuple[int, int, int, int]:
        return api.window_rect(hwnd)

    def visible_rect(self, hwnd: int) -> tuple[int, int, int, int] | None:
        return api.frame_bounds(hwnd)

    def mouse_button_down(self) -> bool:
        """Is the main mouse button held (the one that drags; the right one if they are swapped)?"""
        key = api.VK_RBUTTON if api.GetSystemMetrics(api.SM_SWAPBUTTON) else api.VK_LBUTTON
        return bool(api.GetAsyncKeyState(key) & 0x8000)

    def describe(self, hwnd: int) -> str:
        return api.describe(hwnd)

    def last_error(self) -> int:
        return api.last_error()

    # ------------------------------------------------------------------ moving (never waits)

    def restore(self, hwnd: int) -> bool:
        """Ask a maximised window to go back to its normal size, without activating it."""
        return bool(api.ShowWindowAsync(hwnd, api.SW_SHOWNOACTIVATE))

    def move(self, hwnd: int, rect: tuple[int, int, int, int]) -> bool:
        """Ask the window to take this window rectangle. True = the request was accepted
        (it is carried out by Explorer's own thread a moment later)."""
        left, top, right, bottom = rect
        return bool(api.SetWindowPos(hwnd, None, left, top, right - left, bottom - top, MOVE_FLAGS))
