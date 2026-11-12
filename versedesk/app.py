"""Wires everything together: settings, verses, the verse widget, the tray, timers."""

from __future__ import annotations

import datetime as _dt
import functools
import logging
import os
import sys
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QApplication

from versedesk import paths
from versedesk.autostart import Autostart
from versedesk.daywatch import DayWatcher
from versedesk.desktop_layer import create_desktop_layer
from versedesk.geometry import Rect, place_on_screens, top_right
from versedesk.settings import LoadResult, SettingsStore
from versedesk.ui.icon import app_icon
from versedesk.ui.tray import TrayController
from versedesk.ui.verse_widget import VerseAppearance, VerseWidget
from versedesk.verses import Verse, VerseLibrary, date_key, load_embedded, load_verse_file
from versedesk.version import version_string

log = logging.getLogger("versedesk.app")

POLL_FILES_MS = 2000
SCREEN_DEBOUNCE_MS = 600
DEFAULT_MARGIN_X = 40
DEFAULT_MARGIN_Y = 40


def safe(fn: Callable) -> Callable:
    """Slots must never raise into Qt: log and carry on."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            log.exception("error in %s", fn.__name__)
            return None

    return wrapper


def _file_sig(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _warnings_notice(warnings: list[str]) -> str:
    keys = ", ".join(dict.fromkeys(w.split(" ", 1)[0] for w in warnings))
    return f"settings.json의 일부 값이 올바르지 않아 적용하지 않았습니다: {keys}. 자세한 내용은 log.txt에 있습니다."


def _to_rect(qrect) -> Rect:
    return Rect(qrect.x(), qrect.y(), qrect.width(), qrect.height())


class VerseDeskApp(QObject):
    def __init__(
        self,
        qapp: QApplication,
        store: SettingsStore,
        load_result: LoadResult,
        *,
        autostart: Autostart | None = None,
        today: Callable[[], _dt.date] = _dt.date.today,
        user_verses_path: Path | None = None,
        embedded_verses_path: Path | None = None,
    ):
        super().__init__()
        self.qapp = qapp
        self.store = store
        self.first_run = load_result.first_run
        self._today = today
        self.autostart = autostart or Autostart.for_this_process()
        self.user_verses_path = user_verses_path or paths.user_verses_path()
        self.edit_mode = False
        self._quitting = False

        # verses
        embedded = load_embedded(embedded_verses_path or paths.embedded_verses_path())
        self.library = VerseLibrary(embedded)
        missing = self.library.missing_embedded_dates()
        if missing:
            log.error("embedded verse data is missing %d dates (e.g. %s)", len(missing), missing[:5])
        self._verses_sig: tuple[int, int] | None = None
        self._verses_error_sig: tuple[int, int] | None = None
        self.current_verse: Verse | None = None

        # widgets
        self.layer = create_desktop_layer(store.settings.desktop_mode, parent=self)
        self.verse_widget = VerseWidget(
            VerseAppearance.from_settings(store.settings.verse), extra_flags=self.layer.extra_window_flags
        )
        self.verse_widget.moved.connect(self._on_verse_moved)

        self.tray = TrayController(app_icon(), autostart_supported=self.autostart.supported, parent=self)
        self.tray.edit_mode_toggled.connect(self.set_edit_mode)
        self.tray.autostart_toggled.connect(self.set_autostart)
        self.tray.open_folder_requested.connect(self.open_data_folder)
        self.tray.quit_requested.connect(self.quit)

        # timers
        self.day_watch = DayWatcher(self._on_date_changed, today=today)
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_FILES_MS)
        self._poll.timeout.connect(self._poll_files)
        self._screen_timer = QTimer(self)
        self._screen_timer.setSingleShot(True)
        self._screen_timer.setInterval(SCREEN_DEBOUNCE_MS)
        self._screen_timer.timeout.connect(self._on_screens_settled)
        self._watched_screens: set[int] = set()

        for problem in load_result.warnings:
            log.warning("settings: %s", problem)
        self._startup_notice = None
        if load_result.error and load_result.unreadable:
            log.error("%s — starting with defaults and retrying", load_result.error)
            self._startup_notice = (
                "settings.json을 지금 열 수 없어(다른 프로그램이 사용 중일 수 있음) 기본 설정으로 시작했습니다. "
                "파일을 열 수 있게 되면 자동으로 다시 적용합니다."
            )
        elif load_result.error:
            log.error("%s — using defaults (a copy was kept as settings.json.bad)", load_result.error)
            self._startup_notice = (
                "settings.json을 읽지 못해 기본 설정으로 시작했습니다. 원래 파일은 settings.json.bad로 보관했습니다."
            )
        elif load_result.warnings:
            self._startup_notice = _warnings_notice(load_result.warnings)

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        log.info("starting VerseDesk %s", version_string())
        self.tray.show()  # first, so notifications raised during startup are not dropped
        self._load_user_verses(initial=True)
        self._show_verse_for(self._today())

        effective = self.autostart.sync_at_startup(self.store.settings.autostart)
        self.tray.set_autostart_checked(effective)
        if self.first_run:
            self.store.save()  # create settings.json with the defaults so it can be edited

        self._position_verse()  # before the first show, so it appears in the right place
        self.layer.attach(self.verse_widget, click_through=True)
        self.verse_widget.show()
        self.layer.start()

        self.day_watch.start()
        self._poll.start()
        self._connect_screens()

        if self.first_run:
            self.tray.notify(
                "VerseDesk가 실행되었습니다",
                "바탕화면 오른쪽 위에 오늘의 말씀이 표시됩니다. 이 트레이 아이콘을 누르면 메뉴가 열립니다.",
            )
        elif self._startup_notice:
            self.tray.notify("VerseDesk", self._startup_notice, warning=True)
        QTimer.singleShot(3000, self._log_diagnostics)

    @safe
    def quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        log.info("quitting")
        self.day_watch.stop()
        self._poll.stop()
        self.layer.stop()
        self.tray.hide()
        self.verse_widget.hide()
        self.qapp.quit()

    @safe
    def _log_diagnostics(self) -> None:
        screens = QGuiApplication.screens()
        lines = [f"screens ({len(screens)}):"]
        for s in screens:
            lines.append(
                f"  {s.name()!r} geometry={s.geometry().getRect()} available={s.availableGeometry().getRect()} "
                f"dpr={s.devicePixelRatio()} logicalDpi={s.logicalDotsPerInch():.0f}"
                f"{' (primary)' if s is QGuiApplication.primaryScreen() else ''}"
            )
        g = self.verse_widget.geometry()
        lines.append(f"verse widget at {g.getRect()} on screen {self.verse_widget.screen().name()!r}")
        lines.append(self.layer.diagnostics())
        log.info("\n".join(lines))

    # ------------------------------------------------------------------ verses

    @safe
    def _load_user_verses(self, initial: bool = False) -> bool:
        """(Re)load %APPDATA%\\VerseDesk\\verses.json. Returns True if the overrides changed."""
        sig = _file_sig(self.user_verses_path)
        if not initial and sig == self._verses_sig:
            return False
        self._verses_sig = sig
        if sig is None:
            if self.library.overrides:
                log.info("user verses.json removed; using the built-in verses")
                self.library = self.library.with_overrides({})
                return True
            return False
        entries, warnings, error = load_verse_file(self.user_verses_path, "user")
        if error:
            log.error("user verses: %s", error)
            if sig != self._verses_error_sig:
                self._verses_error_sig = sig
                self.tray.notify(
                    "verses.json 형식 오류",
                    f"{error}\n고칠 때까지 내장 구절을 사용합니다.",
                    warning=True,
                )
            return False
        self._verses_error_sig = None
        for w in warnings:
            log.warning("user verses: %s", w)
        if warnings and not initial:
            self.tray.notify("verses.json", f"{len(warnings)}개 항목을 건너뛰었습니다. log.txt에 이유가 있습니다.", warning=True)
        log.info("user verses.json: %d dates override the built-in verses", len(entries))
        self.library = self.library.with_overrides(entries)
        return True

    def _show_verse_for(self, day: _dt.date) -> None:
        verse = self.library.verse_for(day)
        self.current_verse = verse
        self.verse_widget.set_verse(verse.text, verse.reference)
        self.tray.set_tooltip(f"VerseDesk — {verse.reference or '오늘의 말씀'}")
        log.info("verse for %s: %s [%s]", date_key(day), verse.reference or "(no reference)", verse.source)

    @safe
    def _on_date_changed(self, day: _dt.date) -> None:
        self._show_verse_for(day)
        self._position_verse()

    # ------------------------------------------------------------------ positioning

    def _screen_rects(self) -> tuple[list[Rect], Rect]:
        screens = QGuiApplication.screens()
        rects = [_to_rect(s.availableGeometry()) for s in screens]
        primary = QGuiApplication.primaryScreen()
        if primary is not None:
            prim = _to_rect(primary.availableGeometry())
        elif rects:
            prim = rects[0]
        else:
            prim = Rect(0, 0, 1280, 720)
        return rects, prim

    def _position_verse(self) -> None:
        w = self.verse_widget
        vs = self.store.settings.verse
        rects, prim = self._screen_rects()
        if vs.has_custom_position:
            placed = place_on_screens(Rect(vs.x, vs.y, w.width(), w.height()), rects, prim)
        else:
            placed = top_right(prim, w.width(), w.height(), DEFAULT_MARGIN_X, DEFAULT_MARGIN_Y)
        if (placed.x, placed.y) != (w.x(), w.y()):
            w.move(placed.x, placed.y)

    @safe
    def _on_verse_moved(self, x: int, y: int) -> None:
        w = self.verse_widget
        rects, prim = self._screen_rects()
        placed = place_on_screens(Rect(x, y, w.width(), w.height()), rects, prim)
        if (placed.x, placed.y) != (x, y):
            w.move(placed.x, placed.y)

        def mutate(s):
            s.verse.x, s.verse.y = placed.x, placed.y

        self._apply_reload(self.store.update(mutate))
        log.info("verse moved to (%d, %d)", placed.x, placed.y)

    def _connect_screens(self) -> None:
        app = QGuiApplication.instance()
        app.screenAdded.connect(self._on_screen_added)
        app.screenRemoved.connect(lambda *_: self._screen_timer.start())
        app.primaryScreenChanged.connect(lambda *_: self._screen_timer.start())
        for s in QGuiApplication.screens():
            self._watch_screen(s)

    def _watch_screen(self, screen) -> None:
        if id(screen) in self._watched_screens:
            return
        self._watched_screens.add(id(screen))
        screen.availableGeometryChanged.connect(lambda *_: self._screen_timer.start())
        screen.geometryChanged.connect(lambda *_: self._screen_timer.start())
        screen.logicalDotsPerInchChanged.connect(lambda *_: self._screen_timer.start())

    @safe
    def _on_screen_added(self, screen) -> None:
        self._watch_screen(screen)
        self._screen_timer.start()

    @safe
    def _on_screens_settled(self) -> None:
        if self._quitting:
            return
        log.info("screen configuration changed; re-checking widget positions")
        self.verse_widget.relayout()
        self._position_verse()
        if not self.verse_widget.isVisible():
            # Qt destroys a window whose last screen disappeared (e.g. remote desktop); bring it back
            log.info("verse window was hidden by a screen change; showing it again")
            self.verse_widget.show()
        self.layer.request_sync()

    # ------------------------------------------------------------------ edit mode, autostart, folder

    @safe
    def set_edit_mode(self, on: bool) -> None:
        self.edit_mode = on
        self.verse_widget.set_edit_mode(on)
        self.layer.set_click_through(self.verse_widget, not on)
        self.tray.set_edit_mode(on)
        log.info("edit mode %s", "on" if on else "off")

    @safe
    def set_autostart(self, on: bool) -> None:
        ok = self.autostart.enable() if on else self.autostart.disable()
        effective = self.autostart.is_enabled()
        self.tray.set_autostart_checked(effective)

        def mutate(s):
            s.autostart = on

        self._apply_reload(self.store.update(mutate))
        if not ok:
            self.tray.notify("자동 실행", "자동 실행 설정을 바꾸지 못했습니다. log.txt를 확인해 주세요.", warning=True)

    @safe
    def open_data_folder(self) -> None:
        folder = paths.app_data_dir()
        folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(folder))  # type: ignore[attr-defined]
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # ------------------------------------------------------------------ outside edits

    @safe
    def _poll_files(self) -> None:
        self._apply_reload(self.store.poll())
        if self._load_user_verses():
            self._show_verse_for(self.day_watch.current)
            self._position_verse()

    def _apply_reload(self, result: LoadResult | None) -> None:
        """React to settings.json having been edited outside the app."""
        if result is None:
            return
        if result.error:
            if result.unreadable:
                log.warning("%s — will retry", result.error)
                return
            log.error("%s — keeping the previous settings until the file is fixed", result.error)
            self.tray.notify(
                "settings.json 형식 오류",
                f"{result.error}\n고칠 때까지 이전 설정을 그대로 사용합니다.",
                warning=True,
            )
            return
        for problem in result.warnings:
            log.warning("settings: %s", problem)
        if result.warnings:
            self.tray.notify("settings.json", _warnings_notice(result.warnings), warning=True)
        s = self.store.settings
        log.info("settings.json changed outside the app; applying it")
        self.verse_widget.set_appearance(VerseAppearance.from_settings(s.verse))
        self._position_verse()
        if s.desktop_mode != self.layer.mode:
            log.info("desktop_mode=%s takes effect after a restart", s.desktop_mode)
        if self.autostart.supported and s.autostart != self.autostart.is_enabled():
            self.tray.set_autostart_checked(self.autostart.sync_at_startup(s.autostart))
