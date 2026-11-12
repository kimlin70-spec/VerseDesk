"""Keep widget windows on the desktop layer (like Rainmeter's "On Desktop").

``create_desktop_layer()`` returns the Windows implementation on Windows and a
do-nothing stand-in elsewhere (development and the Linux test run).

The contract every widget relies on:
  * create the widget with ``layer.extra_window_flags`` OR-ed into its window flags;
  * ``attach(widget, click_through=...)`` once, after creating it and before showing it;
  * ``set_click_through(widget, on)`` when edit mode toggles;
  * ``bring_to_front(widget)`` to put a widget above VerseDesk's other widgets (the group
    itself stays on the desktop layer);
  * ``detach(widget)`` before deleting a widget;
  * ``start()`` / ``stop()`` around the application's lifetime.
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QWidget

log = logging.getLogger("versedesk.desktop")


class NullDesktopLayer(QObject):
    """Non-Windows stand-in: remembers state so tests can check it."""

    def __init__(self, mode: str = "bottom", parent: QObject | None = None):
        super().__init__(parent)
        self.mode = mode
        self.attached: dict[int, QWidget] = {}
        self.click_through: dict[int, bool] = {}
        self.front: int | None = None

    @property
    def extra_window_flags(self) -> Qt.WindowType:
        return Qt.WindowType.Widget

    def attach(self, widget: QWidget, *, click_through: bool = False) -> None:
        self.attached[id(widget)] = widget
        self.click_through[id(widget)] = click_through

    def detach(self, widget: QWidget) -> None:
        self.attached.pop(id(widget), None)
        self.click_through.pop(id(widget), None)

    def set_click_through(self, widget: QWidget, enabled: bool) -> None:
        self.click_through[id(widget)] = enabled

    def is_click_through(self, widget: QWidget) -> bool:
        return self.click_through.get(id(widget), False)

    def bring_to_front(self, widget: QWidget) -> None:
        self.front = id(widget)

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def request_sync(self) -> None:
        pass

    def diagnostics(self) -> str:
        return f"desktop layer: none on {sys.platform}"


def create_desktop_layer(mode: str = "bottom", parent: QObject | None = None):
    if sys.platform == "win32":
        try:
            from versedesk.win32.desktop import Win32DesktopLayer

            return Win32DesktopLayer(mode=mode, parent=parent)
        except Exception:
            log.exception("could not initialise the Windows desktop layer; widgets will float normally")
    return NullDesktopLayer(mode=mode, parent=parent)
