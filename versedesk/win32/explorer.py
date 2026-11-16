"""Windows side of "탐색기 창 자리 고정": notice new File Explorer windows, measure and move them.

Noticing: the shell hook.  ``RegisterShellHookWindow`` makes Windows post a "SHELLHOOK"
message to one of our windows whenever a top-level application window appears
(HSHELL_WINDOWCREATED) - the notification the taskbar itself uses for its buttons.  It is
far quieter than a system-wide event hook: nothing arrives for menus, tooltips or child
controls.  The receiving window is a Qt widget that is never shown, so no window procedure
of our own is involved.

Moving: always asynchronously (SWP_ASYNCWINDOWPOS, ShowWindowAsync): the request is posted
to Explorer's own thread, so a busy or hung Explorer can never make VerseDesk wait.

``ExplorerWatcher`` is the object ``ExplorerPlacer`` talks to; it holds no policy.
"""

from __future__ import annotations

import logging
from ctypes import wintypes
from typing import Callable

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import QWidget

from versedesk.win32 import api

log = logging.getLogger("versedesk.explorer")

EXPLORER_CLASS = "CabinetWClass"  # File Explorer windows (and the classic Control Panel) on Windows 10/11
MOVE_FLAGS = api.SWP_NOZORDER | api.SWP_NOACTIVATE | api.SWP_NOOWNERZORDER | api.SWP_ASYNCWINDOWPOS


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
        if event.type() == QEvent.Type.WinIdChange:  # Qt made a new native window: register that one
            try:
                self._on_new_handle()
            except Exception:
                pass
        return super().event(event)


class ExplorerWatcher:
    def __init__(self):
        self._message = api.RegisterWindowMessageW("SHELLHOOK")
        self._receiver: _Receiver | None = None
        self._registered = 0
        self._callback: Callable[[int], None] | None = None

    # ------------------------------------------------------------------ watching

    def start(self, callback: Callable[[int], None]) -> bool:
        """Call ``callback(hwnd)`` (on the GUI thread) for every new top-level application window."""
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

    def _register(self) -> bool:
        hwnd = int(self._receiver.winId())  # creates the native window on first use
        if hwnd == self._registered and api.IsWindow(hwnd):
            return True
        if self._registered and api.IsWindow(self._registered):
            api.DeregisterShellHookWindow(self._registered)
        self._registered = hwnd if api.RegisterShellHookWindow(hwnd) else 0
        if not self._registered:
            log.warning("RegisterShellHookWindow failed for %s", api.describe(hwnd))
        return bool(self._registered)

    def _on_native(self, message) -> None:
        address = int(message)
        if not address or self._callback is None:
            return
        msg = wintypes.MSG.from_address(address)
        if msg.message != self._message or (msg.wParam & 0x7FFF) != api.HSHELL_WINDOWCREATED:
            return
        hwnd = api.h(msg.lParam) & 0xFFFFFFFFFFFFFFFF
        # out of the message filter first; the callback may look at and move windows
        QTimer.singleShot(0, lambda: self._deliver(hwnd))

    def _deliver(self, hwnd: int) -> None:
        callback = self._callback
        if callback is not None:
            callback(hwnd)

    # ------------------------------------------------------------------ looking at windows

    def explorer_windows(self) -> list[int]:
        return [w for w in api.top_level_windows() if api.class_name(w) == EXPLORER_CLASS]

    def is_explorer_window(self, hwnd: int) -> bool:
        return bool(api.IsWindow(hwnd)) and api.class_name(hwnd) == EXPLORER_CLASS

    def exists(self, hwnd: int) -> bool:
        return bool(api.IsWindow(hwnd))

    def is_visible(self, hwnd: int) -> bool:
        return bool(api.IsWindowVisible(hwnd))

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

    # ------------------------------------------------------------------ moving (never waits)

    def restore(self, hwnd: int) -> None:
        api.ShowWindowAsync(hwnd, api.SW_SHOWNOACTIVATE)

    def move(self, hwnd: int, rect: tuple[int, int, int, int]) -> None:
        left, top, right, bottom = rect
        if not api.SetWindowPos(hwnd, None, left, top, right - left, bottom - top, MOVE_FLAGS):
            log.debug("SetWindowPos refused for %s", api.describe(hwnd))
