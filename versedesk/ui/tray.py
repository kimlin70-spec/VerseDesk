"""The tray icon and its menu — the app has no main window."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QCursor, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

log = logging.getLogger("versedesk.ui.tray")

TEXT_EDIT_ON = "배치 편집 켜기"
TEXT_EDIT_OFF = "배치 편집 끄기 (위치 저장됨)"
TEXT_ADD_ZONE = "새 구역 추가"
TEXT_ADD_ZONE_LATER = "새 구역 추가 (다음 단계에서 제공)"
TEXT_AUTOSTART = "Windows 시작 시 자동 실행"
TEXT_AUTOSTART_DEV = "Windows 시작 시 자동 실행 (exe에서만 가능)"
TEXT_OPEN_FOLDER = "설정·로그 폴더 열기"
TEXT_EXPORT_VERSES = "구절 목록 파일 만들기 (편집용)"
TEXT_QUIT = "종료"


class TrayController(QObject):
    edit_mode_toggled = Signal(bool)
    add_zone_requested = Signal()
    autostart_toggled = Signal(bool)
    open_folder_requested = Signal()
    export_verses_requested = Signal()
    quit_requested = Signal()

    def __init__(self, icon: QIcon, autostart_supported: bool, zones_available: bool = False, parent=None):
        super().__init__(parent)
        self._edit = False
        self.tray = QSystemTrayIcon(icon)
        self.menu = QMenu()

        self.act_edit = QAction(TEXT_EDIT_ON, self.menu)
        self.act_edit.triggered.connect(lambda: self.edit_mode_toggled.emit(not self._edit))
        self.menu.addAction(self.act_edit)

        self.act_zone = QAction(TEXT_ADD_ZONE if zones_available else TEXT_ADD_ZONE_LATER, self.menu)
        self.act_zone.setEnabled(zones_available)
        self.act_zone.triggered.connect(self.add_zone_requested.emit)
        self.menu.addAction(self.act_zone)

        self.menu.addSeparator()
        self.act_autostart = QAction(TEXT_AUTOSTART if autostart_supported else TEXT_AUTOSTART_DEV, self.menu)
        self.act_autostart.setCheckable(True)
        self.act_autostart.setEnabled(autostart_supported)
        self.act_autostart.triggered.connect(lambda checked: self.autostart_toggled.emit(bool(checked)))
        self.menu.addAction(self.act_autostart)

        self.act_export = QAction(TEXT_EXPORT_VERSES, self.menu)
        self.act_export.triggered.connect(self.export_verses_requested.emit)
        self.menu.addAction(self.act_export)

        self.act_folder = QAction(TEXT_OPEN_FOLDER, self.menu)
        self.act_folder.triggered.connect(self.open_folder_requested.emit)
        self.menu.addAction(self.act_folder)

        self.menu.addSeparator()
        self.act_quit = QAction(TEXT_QUIT, self.menu)
        self.act_quit.triggered.connect(self.quit_requested.emit)
        self.menu.addAction(self.act_quit)

        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_activated)

    def show(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.warning("system tray not available (yet); the icon will appear when it is")
        self.tray.show()

    def hide(self) -> None:
        self.tray.hide()

    def set_edit_mode(self, on: bool) -> None:
        self._edit = on
        self.act_edit.setText(TEXT_EDIT_OFF if on else TEXT_EDIT_ON)

    def set_autostart_checked(self, on: bool) -> None:
        self.act_autostart.setChecked(on)

    def set_tooltip(self, text: str) -> None:
        self.tray.setToolTip(text[:120])  # Windows truncates tray tooltips (~128 chars)

    def notify(self, title: str, message: str, warning: bool = False, msecs: int = 8000) -> None:
        icon = QSystemTrayIcon.MessageIcon.Warning if warning else QSystemTrayIcon.MessageIcon.Information
        try:
            self.tray.showMessage(title, message, icon, msecs)
        except Exception:
            log.exception("tray notification failed")

    def _on_activated(self, reason) -> None:
        # Left click opens the same menu as right click: there is no main window to show.
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.menu.popup(QCursor.pos())
