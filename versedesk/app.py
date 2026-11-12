"""Wires everything together: settings, the verse list, the verse widget, the tray, timers."""

from __future__ import annotations

import datetime as _dt
import functools
import logging
import os
import sys
import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QApplication

from versedesk import paths
from versedesk.autostart import Autostart
from versedesk.desktop_layer import create_desktop_layer
from versedesk.geometry import Rect, place_on_screens, top_right
from versedesk.rotation import RotationClock, interval_label, verse_index
from versedesk.settings import LoadResult, SettingsStore, atomic_write_text
from versedesk.ui.icon import app_icon
from versedesk.ui.tray import TrayController
from versedesk.ui.verse_widget import VerseAppearance, VerseWidget
from versedesk.verses import FALLBACK, Verse, list_document, load_builtin, load_verse_file
from versedesk.version import version_string
from versedesk.zone_manager import ZoneManager

log = logging.getLogger("versedesk.app")

POLL_FILES_MS = 2000
SCREEN_DEBOUNCE_MS = 600
STRAY_CLICK_LOG_INTERVAL_S = 10.0
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
        now: Callable[[], _dt.datetime] = _dt.datetime.now,
        user_verses_path: Path | None = None,
        embedded_verses_path: Path | None = None,
    ):
        super().__init__()
        self.qapp = qapp
        self.store = store
        self.first_run = load_result.first_run
        self._now = now
        self.autostart = autostart or Autostart.for_this_process()
        self.user_verses_path = user_verses_path or paths.user_verses_path()
        self.edit_mode = False
        self._quitting = False

        # verses: the user's own list (verses.json) when there is one, else the built-in list
        self.builtin = load_builtin(embedded_verses_path or paths.embedded_verses_path())
        if not self.builtin:
            log.error("the built-in verse list is empty")
        self.user_list: list[Verse] | None = None
        self._verses_sig: tuple[int, int] | None = None
        self._verses_error_sig: tuple[int, int] | None = None
        self._dated_file_kept = False  # an old one-verse-per-date verses.json could not be moved aside
        self.current_verse: Verse | None = None
        self.current_index = 0
        self._editor = None

        # widgets
        self.layer = create_desktop_layer(store.settings.desktop_mode, parent=self)
        self.verse_widget = VerseWidget(
            VerseAppearance.from_settings(store.settings.verse), extra_flags=self.layer.extra_window_flags
        )
        self.verse_widget.moved.connect(self._on_verse_moved)
        self.verse_widget.stray_click.connect(self._on_stray_click)
        self._last_stray_log = -1e9

        self.tray = TrayController(
            app_icon(), autostart_supported=self.autostart.supported, zones_available=True, parent=self
        )
        self.tray.edit_mode_toggled.connect(self.set_edit_mode)
        self.tray.autostart_toggled.connect(self.set_autostart)
        self.tray.open_folder_requested.connect(self.open_data_folder)
        self.tray.edit_verses_requested.connect(self.open_verse_editor)
        self.tray.quit_requested.connect(self.quit)

        # folder zones
        self.zones = ZoneManager(
            store,
            self.layer,
            notify=self.tray.notify,
            screen_rects=self._screen_rects,
            apply_reload=self._apply_reload,
            parent=self,
        )
        self.tray.add_zone_requested.connect(self._add_zone)

        # timers
        self.rotation = RotationClock(self._on_rotation, store.settings.verse.interval_minutes, now=now)
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
        self._show_current()

        effective = self.autostart.sync_at_startup(self.store.settings.autostart)
        self.tray.set_autostart_checked(effective)
        if self.first_run:
            self.store.save()  # create settings.json with the defaults so it can be edited

        self._position_verse()  # before the first show, so it appears in the right place
        self.layer.attach(self.verse_widget, click_through=True)
        self.verse_widget.show()
        self.zones.start()
        self.layer.start()

        self.rotation.start()
        self._poll.start()
        self._connect_screens()

        if self.first_run:
            self.tray.notify(
                "VerseDesk가 실행되었습니다",
                "바탕화면 오른쪽 위에 말씀이 표시되고 차례대로 바뀝니다. 이 트레이 아이콘을 누르면 메뉴가 열립니다.",
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
        self.rotation.stop()
        self._poll.stop()
        if self._editor is not None:
            self._editor.close()
        self.layer.stop()
        self.zones.stop()
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
        lines.append(self.zones.diagnostics())
        lines.append(self.layer.diagnostics())
        log.info("\n".join(lines))

    # ------------------------------------------------------------------ verses

    def active_verses(self) -> list[Verse]:
        """What rotates on the desktop: the user's list, or the built-in one while the user
        has no list (or emptied it)."""
        return self.user_list or self.builtin or [FALLBACK]

    @safe
    def _load_user_verses(self, initial: bool = False) -> bool:
        """(Re)load %APPDATA%\\VerseDesk\\verses.json. Returns True if the list changed."""
        sig = _file_sig(self.user_verses_path)
        if not initial and sig == self._verses_sig:
            return False
        self._verses_sig = sig
        if sig is None:
            self._dated_file_kept = False
            if self.user_list is not None:
                log.info("user verses.json removed; using the built-in list")
                self.user_list = None
                return True
            return False
        result = load_verse_file(self.user_verses_path, "user")
        if result.dated:
            self._retire_dated_file()
            changed, self.user_list = self.user_list is not None, None
            return changed
        if result.error:
            log.error("user verses: %s", result.error)
            if sig != self._verses_error_sig:
                self._verses_error_sig = sig
                self.tray.notify(
                    "verses.json 형식 오류",
                    f"{result.error}\n고칠 때까지 이전 목록을 그대로 사용합니다.",
                    warning=True,
                )
            return False
        self._verses_error_sig = None
        self._dated_file_kept = False
        for w in result.warnings:
            log.warning("user verses: %s", w)
        if result.warnings and not initial:
            self.tray.notify("verses.json", f"{len(result.warnings)}개 항목을 건너뛰었습니다. log.txt에 이유가 있습니다.",
                             warning=True)
        log.info("user verse list: %d verses", len(result.verses))
        self.user_list = result.verses
        return True

    def _retire_dated_file(self) -> None:
        """An older VerseDesk kept one verse per calendar day in verses.json. That file is not
        a list: move it aside (never delete it) so the user's new list can take its place."""
        backup = self.user_verses_path.with_name(f"verses.backup-{_dt.datetime.now():%Y%m%d-%H%M%S}.json")
        try:
            self.user_verses_path.rename(backup)
        except OSError as e:
            if not self._dated_file_kept:
                log.warning("old date-based verses.json could not be moved aside (%s); it is not used", e)
            self._dated_file_kept = True
            return
        self._verses_sig = None
        self._dated_file_kept = False
        log.info("old date-based verses.json moved to %s; it is no longer used", backup.name)
        self.tray.notify(
            "말씀 목록",
            f"예전 날짜별 목록(verses.json)은 이제 쓰지 않아 {backup.name}(으)로 보관했습니다. "
            "트레이 메뉴 '말씀 목록 편집'에서 내 목록을 만들 수 있습니다.",
        )

    def _show_current(self, *, force: bool = False) -> None:
        verses = self.active_verses()
        interval = self.store.settings.verse.interval_minutes
        index = verse_index(self._now(), interval, len(verses))
        verse = verses[index]
        if not force and verse == self.current_verse and index == self.current_index:
            return
        self.current_verse, self.current_index = verse, index
        self.verse_widget.set_verse(verse.text, verse.reference)
        self.tray.set_tooltip(f"VerseDesk — {verse.reference or '말씀'}")
        self._position_verse()
        log.info("verse %d/%d (%s): %s [%s]", index + 1, len(verses), interval_label(interval),
                 verse.reference or "(no reference)", verse.source)

    @safe
    def _on_rotation(self) -> None:
        self._show_current()

    # ------------------------------------------------------------------ verse list editor

    @safe
    def open_verse_editor(self) -> None:
        if self._editor is not None:
            self._editor.present()
            return
        from versedesk.ui.verse_editor import VerseEditor

        using_builtin = self.user_list is None
        editor = VerseEditor(
            list(self.builtin if using_builtin else self.user_list),
            self.store.settings.verse.interval_minutes,
            using_builtin=using_builtin,
            icon=app_icon(),
        )
        editor.list_changed.connect(self._on_editor_list)
        editor.interval_changed.connect(self._on_editor_interval)
        editor.closed.connect(self._on_editor_closed)
        self._editor = editor
        editor.present()
        log.info("verse list editor opened")

    @safe
    def _on_editor_closed(self, *_args) -> None:
        self._editor = None
        log.info("verse list editor closed")

    @safe
    def _on_editor_list(self, verses: list) -> None:
        ok = self.save_user_list(verses)
        if self._editor is not None:
            self._editor.set_save_result(ok)

    def save_user_list(self, verses: list[Verse]) -> bool:
        """Write the user's list to verses.json and show it right away."""
        path = self.user_verses_path
        verses = [Verse(v.reference, v.text, "user") for v in verses]
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if self._dated_file_kept and path.exists():  # keep the old file, never overwrite it
                import shutil

                shutil.copy2(path, path.with_name(f"verses.backup-{_dt.datetime.now():%Y%m%d-%H%M%S}.json"))
                self._dated_file_kept = False
            atomic_write_text(path, list_document(verses))
        except OSError:
            log.exception("could not save the verse list")
            self.tray.notify("말씀 목록", "목록을 저장하지 못했습니다. log.txt를 확인해 주세요.", warning=True)
            return False
        self._verses_sig = _file_sig(path)
        self._verses_error_sig = None
        self.user_list = verses
        log.info("verse list saved: %d verses", len(verses))
        self._show_current()
        return True

    @safe
    def _on_editor_interval(self, minutes: int) -> None:
        def mutate(s):
            s.verse.interval_minutes = minutes

        self._apply_reload(self.store.update(mutate))
        self._apply_interval()

    def _apply_interval(self) -> None:
        minutes = self.store.settings.verse.interval_minutes
        if minutes != self.rotation.interval:
            log.info("the verse now changes %s", interval_label(minutes))
            self.rotation.set_interval(minutes)
            self._show_current()

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
    def _on_stray_click(self, x: int, y: int) -> None:
        """A click reached the verse window outside edit mode: it should have gone through to
        the desktop. Log what the window and the desktop look like right now (rate-limited)."""
        now = time.monotonic()
        if now - self._last_stray_log < STRAY_CLICK_LOG_INTERVAL_S:
            return
        self._last_stray_log = now
        log.warning(
            "a click at (%d, %d) reached the verse window although clicks should pass through to the desktop\n%s",
            x, y, self.layer.diagnostics(),
        )

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
        self.zones.reposition()
        self.layer.request_sync()

    # ------------------------------------------------------------------ edit mode, autostart, folder

    @safe
    def set_edit_mode(self, on: bool) -> None:
        self.edit_mode = on
        self.verse_widget.set_edit_mode(on)
        self.layer.set_click_through(self.verse_widget, not on)
        self.zones.set_edit_mode(on)
        self.tray.set_edit_mode(on)
        log.info("edit mode %s", "on" if on else "off")

    @safe
    def _add_zone(self) -> None:
        self.zones.add_zone()

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
            self._show_current(force=True)
            if self._editor is not None:  # edited outside while the editor is open
                using_builtin = self.user_list is None
                self._editor.set_list(list(self.builtin if using_builtin else self.user_list), using_builtin)

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
        self._apply_interval()
        if s.desktop_mode != self.layer.mode:
            log.info("desktop_mode=%s takes effect after a restart", s.desktop_mode)
        if self.autostart.supported and s.autostart != self.autostart.is_enabled():
            self.tray.set_autostart_checked(self.autostart.sync_at_startup(s.autostart))
        self.zones.sync_from_settings()
