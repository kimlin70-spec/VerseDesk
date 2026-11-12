"""Base class for every window that lives on the desktop layer (verse now, zones later).

It only adds a hook so the desktop layer can see the window's native messages (to veto
z-order changes on Windows).  Everything else is plain QWidget.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

DESKTOP_WINDOW_FLAGS = (
    Qt.WindowType.Tool
    | Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.WindowDoesNotAcceptFocus
    | Qt.WindowType.NoDropShadowWindowHint
)


class DesktopWidget(QWidget):
    def __init__(self, extra_flags=Qt.WindowType.Widget):
        super().__init__(None, DESKTOP_WINDOW_FLAGS | extra_flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._native_filter: Callable[[object], None] | None = None

    def set_native_filter(self, fn: Callable[[object], None] | None) -> None:
        self._native_filter = fn

    def nativeEvent(self, event_type, message):  # noqa: N802 - Qt naming
        fn = self._native_filter
        if fn is not None:
            fn(message)  # may adjust the message in place; never raises
        return False, 0  # always let Qt handle the message normally
