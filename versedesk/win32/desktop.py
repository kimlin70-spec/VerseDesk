"""Glue VerseDesk widget windows to the Windows desktop (Rainmeter "On Desktop" behaviour).

Requirements: never above normal app windows, not in taskbar/Alt+Tab, still visible after
Win+D ("Show desktop"), re-attach after explorer.exe restarts, keep Qt's per-pixel-alpha
(layered) rendering, still receive mouse input when needed.

Approach
--------
* Each widget stays a *top-level* Qt.Tool | FramelessWindowHint window (Qt makes it
  WS_EX_LAYERED for the translucent background).  We add WS_EX_TOOLWINDOW +
  WS_EX_NOACTIVATE (no taskbar/Alt+Tab entry, clicking never activates or raises it),
  and WS_EX_TRANSPARENT when it should be click-through.
* The "desktop host" is the top-level window that currently contains SHELLDLL_DefView
  (the desktop icon view): "Progman" normally and on Windows 11 24H2+, or a "WorkerW" in
  some Windows 10 states.
* mode "owner" (default): the widget's owner (GWLP_HWNDPARENT) is set to the desktop host.
  An owned window is always kept above its owner, so when Show desktop raises the desktop
  window, Windows raises our widgets with it, synchronously.
* mode "bottom": no owner relationship; the keeper alone tracks the desktop's position.
* Keeper: every second, and right after any foreground-window change (a WinEvent hook),
  we re-find the desktop host (explorer restarted? DefView moved?), re-apply owner and
  styles (Qt resets the owner when it shows a window), and if any visible foreign
  window has slipped between a widget and the desktop, we put the widget back directly
  above the desktop window.
"""

from __future__ import annotations

import ctypes
import logging
import os
import platform
import sys
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QWindow
from PySide6.QtWidgets import QWidget

from versedesk.win32 import api

log = logging.getLogger("versedesk.desktop")

TICK_MS = 1000
SOON_MS = 40
DESKTOP_CLASSES = ("Progman", "WorkerW")
MAX_WALK = 4096
FIGHT_WINDOW_S = 10.0
FIGHT_LIMIT = 8
FIGHT_PAUSE_S = 30.0
MAX_INFO_FIX_LOGS = 25


# ----------------------------------------------------------------------------- finding the desktop


def _defview_in(parent: int) -> int:
    return api.h(api.FindWindowExW(parent, None, "SHELLDLL_DefView", None))


def top_level_workerws(limit: int = 256) -> list[int]:
    out, w = [], 0
    for _ in range(limit):
        w = api.h(api.FindWindowExW(None, w or None, "WorkerW", None))
        if not w:
            break
        out.append(w)
    return out


def find_desktop_host() -> int:
    """HWND of the top-level window hosting the desktop icons (0 if explorer is not running)."""
    progman = api.h(api.FindWindowW("Progman", None))
    if progman and _defview_in(progman):
        return progman
    for w in top_level_workerws():
        if _defview_in(w):
            return w
    return progman


def describe_desktop() -> str:
    try:
        lines = [f"Windows {platform.version()} ({platform.release()}), {platform.machine()}"]
        progman = api.h(api.FindWindowW("Progman", None))
        shell = api.h(api.GetShellWindow())
        lines.append(f"  Progman: {api.describe(progman)} defview=0x{_defview_in(progman) if progman else 0:X}")
        lines.append(f"  GetShellWindow: {api.describe(shell)}")
        for w in top_level_workerws(32):
            lines.append(f"  WorkerW: {api.describe(w)} defview=0x{_defview_in(w):X}")
        host = find_desktop_host()
        lines.append(f"  desktop host: {api.describe(host)}")
        if host:
            above, below = [], []
            w = host
            for _ in range(6):
                w = api.h(api.GetWindow(w, api.GW_HWNDPREV))
                if not w:
                    break
                above.append(api.describe(w))
            w = host
            for _ in range(3):
                w = api.h(api.GetWindow(w, api.GW_HWNDNEXT))
                if not w:
                    break
                below.append(api.describe(w))
            lines.append("  z-order just above host (nearest first):")
            lines += [f"    {d}" for d in above] or ["    (none)"]
            lines.append("  z-order just below host:")
            lines += [f"    {d}" for d in below] or ["    (none)"]
        return "\n".join(lines)
    except Exception as e:  # diagnostics must never break the app
        return f"describe_desktop failed: {e}"


def _flags(ex: int) -> str:
    names = [
        ("TOOLWINDOW", api.WS_EX_TOOLWINDOW),
        ("NOACTIVATE", api.WS_EX_NOACTIVATE),
        ("LAYERED", api.WS_EX_LAYERED),
        ("TRANSPARENT", api.WS_EX_TRANSPARENT),
        ("TOPMOST", api.WS_EX_TOPMOST),
        ("APPWINDOW", api.WS_EX_APPWINDOW),
    ]
    return "|".join(n for n, bit in names if ex & bit) or "-"


def is_blocking(w: int, host: int) -> bool:
    """Would this window be wrongly covered by a widget sitting above it?"""
    if not api.IsWindowVisible(w) or api.IsIconic(w):
        return False
    ex = api.ex_style(w)
    if ex & (api.WS_EX_TOOLWINDOW | api.WS_EX_NOACTIVATE):
        return False  # other desktop gadgets, palettes, overlays: do not fight them
    if (ex & api.WS_EX_LAYERED) and (ex & api.WS_EX_TRANSPARENT):
        return False  # click-through overlay
    if host and api.h(api.GetWindow(w, api.GW_OWNER)) == host:
        return False
    left, top, right, bottom = api.window_rect(w)
    if right - left <= 0 or bottom - top <= 0:
        return False
    if api.class_name(w) in DESKTOP_CLASSES:
        return False
    if api.is_cloaked(w):
        return False  # e.g. windows on another virtual desktop, suspended UWP apps
    return True


def check_placement(hwnd: int, host: int, own: set[int] | frozenset[int] = frozenset()) -> tuple[bool, int]:
    """Is ``hwnd`` sitting directly on the desktop?

    Walks down the z-order from the widget. Returns (True, 0) when the desktop host is
    reached without meeting a visible foreign window; (False, blocker) when a window that
    should be above the widget is below it; (False, 0) when the host is not below the
    widget at all (the desktop is covering it).
    """
    if not host:
        return True, 0
    w = api.h(api.GetWindow(hwnd, api.GW_HWNDNEXT))
    for _ in range(MAX_WALK):
        if not w:
            return False, 0
        if w == host:
            return True, 0
        if w not in own and is_blocking(w, host):
            return False, w
        w = api.h(api.GetWindow(w, api.GW_HWNDNEXT))
    return False, 0


# ----------------------------------------------------------------------------- the keeper


@dataclass
class _Pinned:
    widget: QWidget
    click_through: bool
    hwnd: int = 0
    fixes: list[float] = field(default_factory=list)
    pause_until: float = 0.0
    warned_not_layered: bool = False


class Win32DesktopLayer(QObject):
    def __init__(self, mode: str = "owner", parent: QObject | None = None):
        super().__init__(parent)
        self.mode = mode if mode in ("owner", "bottom") else "owner"
        self._pinned: dict[int, _Pinned] = {}
        self._host = 0
        self._info_fix_logs = 0
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._soon = QTimer(self)
        self._soon.setSingleShot(True)
        self._soon.setInterval(SOON_MS)
        self._soon.timeout.connect(self._tick)
        self._hook = None
        # Keep a reference: if this callback object were garbage-collected Windows would
        # call freed memory.
        self._hook_proc = api.WINEVENTPROC(self._on_win_event)
        # QWindow wrappers of desktop host windows (QWindow.fromWinId), used as Qt
        # "transient parent" so Qt itself keeps the owner when it shows a window.
        # Never deleted: destroying a foreign QWindow must not risk touching explorer's window.
        self._foreign: dict[int, QWindow] = {}

    # ---- public API

    @property
    def extra_window_flags(self) -> Qt.WindowType:
        """Flags widgets must be created with.

        In owner mode, Qt.WindowStaysOnBottomHint makes Qt (a) skip its HWND_TOP raise when
        a Qt.Tool window is shown and (b) turn every z-order request for the window into
        HWND_BOTTOM, which Windows resolves to "just above the owner" for an owned window.
        In bottom mode there is no owner, so HWND_BOTTOM could sink the widget *below* the
        desktop; there the keeper does all z-order work itself.
        """
        if self.mode == "owner":
            return Qt.WindowType.WindowStaysOnBottomHint
        return Qt.WindowType.Widget

    def attach(self, widget: QWidget, *, click_through: bool = False) -> None:
        """Call before the widget is first shown: the native window is created hidden,
        owned and placed just above the desktop, so it never flashes above other windows."""
        key = id(widget)
        entry = _Pinned(widget, click_through)
        self._pinned[key] = entry
        widget.installEventFilter(self)
        widget.destroyed.connect(lambda *_a, k=key: self._pinned.pop(k, None))
        self._sync_entry(entry, self._current_host(), force=True, allow_hidden=True)

    def detach(self, widget: QWidget) -> None:
        entry = self._pinned.pop(id(widget), None)
        if entry is not None:
            try:
                widget.removeEventFilter(self)
            except RuntimeError:
                pass

    def set_click_through(self, widget: QWidget, enabled: bool) -> None:
        entry = self._pinned.get(id(widget))
        if entry is None:
            return
        entry.click_through = enabled
        if entry.hwnd and api.IsWindow(entry.hwnd):
            self._apply_styles(entry)

    def is_click_through(self, widget: QWidget) -> bool:
        entry = self._pinned.get(id(widget))
        return bool(entry and entry.click_through)

    def start(self) -> None:
        log.info("desktop layer mode=%s\n%s", self.mode, describe_desktop())
        self._timer.start()
        if not self._hook:
            flags = api.WINEVENT_OUTOFCONTEXT | api.WINEVENT_SKIPOWNPROCESS
            self._hook = api.SetWinEventHook(
                api.EVENT_SYSTEM_FOREGROUND, api.EVENT_SYSTEM_FOREGROUND, None, self._hook_proc, 0, 0, flags
            )
            if not self._hook:
                log.warning("SetWinEventHook failed (error %s); relying on the 1 s timer", ctypes.get_last_error())
        self._tick()

    def stop(self) -> None:
        self._timer.stop()
        self._soon.stop()
        if self._hook:
            api.UnhookWinEvent(self._hook)
            self._hook = None

    def request_sync(self) -> None:
        if not self._soon.isActive():
            self._soon.start()

    def diagnostics(self) -> str:
        lines = [describe_desktop()]
        host = find_desktop_host()
        for entry in self._pinned.values():
            hwnd = entry.hwnd
            if not hwnd or not api.IsWindow(hwnd):
                lines.append(f"  widget {entry.widget.objectName()!r}: no window")
                continue
            owner = api.h(api.GetWindow(hwnd, api.GW_OWNER))
            lines.append(
                f"  widget {entry.widget.objectName()!r}: {api.describe(hwnd)} "
                f"ex={_flags(api.ex_style(hwnd))} owner={api.describe(owner)} "
                f"owner_is_host={owner == host} directly_above_desktop={self._placed_ok(hwnd, host)}"
            )
        return "\n".join(lines)

    # ---- Qt hooks

    def eventFilter(self, obj, event):  # noqa: N802 - Qt naming
        try:
            if event.type() in (QEvent.Type.Show, QEvent.Type.WinIdChange):
                # Qt resets the owner while showing a window: re-apply it as soon as the
                # show has completed (next event-loop pass), and once more a bit later.
                QTimer.singleShot(0, self._tick)
                self.request_sync()
        except Exception:
            log.exception("desktop event filter failed")
        return False

    def _on_win_event(self, hook, event, hwnd, id_object, id_child, thread, ms):  # noqa: ARG002
        try:
            self.request_sync()
        except Exception:
            pass

    # ---- the work

    def _current_host(self) -> int:
        host = find_desktop_host()
        if host != self._host:
            log.info(
                "desktop host changed: %s -> %s\n%s",
                f"0x{self._host:X}" if self._host else "none",
                api.describe(host),
                describe_desktop(),
            )
            self._host = host
        return host

    def _tick(self) -> None:
        try:
            host = self._current_host()
            for entry in list(self._pinned.values()):
                self._sync_entry(entry, host)
        except Exception:
            log.exception("desktop sync failed")

    def _sync_entry(self, entry: _Pinned, host: int, force: bool = False, allow_hidden: bool = False) -> None:
        widget = entry.widget
        try:
            if not widget.isVisible() and not allow_hidden:
                return
            hwnd = int(widget.winId())  # creates the native window if needed
        except RuntimeError:  # the C++ object is gone
            return
        if hwnd != entry.hwnd:
            log.info("widget %r has window 0x%X", widget.objectName(), hwnd)
            entry.hwnd = hwnd
            force = True
        if not hwnd or not api.IsWindow(hwnd):
            return
        self._apply_styles(entry)
        if not host:
            return
        if self.mode == "owner":
            self._ensure_transient_parent(widget, host)
            owner = api.h(api.GetWindow(hwnd, api.GW_OWNER))
            if owner != host:
                api.SetWindowLongPtrW(hwnd, api.GWLP_HWNDPARENT, host)
                log.debug("widget %r owner 0x%X -> 0x%X", widget.objectName(), owner, host)
                force = True
        if force or not self._placed_ok(hwnd, host):
            if self._may_fix(entry):
                self._place_above(entry, host)

    def _ensure_transient_parent(self, widget: QWidget, host: int) -> None:
        """Make Qt aware of the owner. Qt 6.10 re-applies a foreign transient parent as the
        native owner whenever it shows the window, instead of resetting the owner to NULL."""
        try:
            handle = widget.windowHandle()
            if handle is None:
                return
            foreign = self._foreign.get(host)
            if foreign is None:
                foreign = QWindow.fromWinId(host)
                if foreign is None:
                    return
                self._foreign[host] = foreign
            if handle.transientParent() is not foreign:
                handle.setTransientParent(foreign)
        except Exception:
            log.exception("could not set the desktop as transient parent; using the owner only")

    def _apply_styles(self, entry: _Pinned) -> None:
        hwnd = entry.hwnd
        ex = api.ex_style(hwnd)
        want = (ex | api.WS_EX_TOOLWINDOW | api.WS_EX_NOACTIVATE) & ~api.WS_EX_APPWINDOW
        if entry.click_through:
            want |= api.WS_EX_TRANSPARENT
            if not ex & api.WS_EX_LAYERED and not entry.warned_not_layered:
                entry.warned_not_layered = True
                log.warning("widget window 0x%X is not layered; click-through may not work", hwnd)
        else:
            want &= ~api.WS_EX_TRANSPARENT
        if want != ex:
            api.SetWindowLongPtrW(hwnd, api.GWL_EXSTYLE, want)

    def _placed_ok(self, hwnd: int, host: int) -> bool:
        own = {e.hwnd for e in self._pinned.values() if e.hwnd}
        ok, _blocker = check_placement(hwnd, host, own)
        return ok

    def _may_fix(self, entry: _Pinned) -> bool:
        now = time.monotonic()
        if now < entry.pause_until:
            return False
        entry.fixes = [t for t in entry.fixes if now - t < FIGHT_WINDOW_S]
        entry.fixes.append(now)
        if len(entry.fixes) > FIGHT_LIMIT:
            entry.fixes.clear()
            entry.pause_until = now + FIGHT_PAUSE_S
            log.warning(
                "widget %r needed %d z-order corrections within %.0f s; pausing corrections for %.0f s "
                "(another program may be fighting for the desktop layer)\n%s",
                entry.widget.objectName(),
                FIGHT_LIMIT,
                FIGHT_WINDOW_S,
                FIGHT_PAUSE_S,
                describe_desktop(),
            )
            return False
        return True

    def _place_above(self, entry: _Pinned, host: int) -> None:
        hwnd = entry.hwnd
        above = api.h(api.GetWindow(host, api.GW_HWNDPREV))
        if above == hwnd:
            return
        insert_after = above if above else api.HWND_TOP
        flags = api.SWP_NOMOVE | api.SWP_NOSIZE | api.SWP_NOACTIVATE | api.SWP_NOOWNERZORDER
        ok = api.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, flags)
        level = logging.INFO if self._info_fix_logs < MAX_INFO_FIX_LOGS else logging.DEBUG
        self._info_fix_logs += 1
        log.log(
            level,
            "placed widget %r just above the desktop (insert after %s) ok=%s",
            entry.widget.objectName(),
            api.describe(above) if above else "HWND_TOP",
            bool(ok),
        )


def pid() -> int:  # pragma: no cover - tiny helper for diagnostics
    return os.getpid()


def is_windows() -> bool:  # pragma: no cover
    return sys.platform == "win32"
