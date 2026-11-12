"""Glue VerseDesk widget windows to the Windows desktop (Rainmeter "On Desktop" behaviour).

Requirements: never above normal app windows, not in taskbar/Alt+Tab, still visible after
Win+D ("Show desktop"), survive explorer.exe restarts, keep Qt's per-pixel-alpha
(layered) rendering, still receive mouse input when needed.

Approach (default mode "bottom", modelled on Rainmeter's ZPOSITION_ONDESKTOP)
---------------------------------------------------------------------------
* Each widget is an *unowned* top-level Qt.Tool | FramelessWindowHint |
  WindowDoesNotAcceptFocus window with a translucent background (Qt makes it
  WS_EX_LAYERED).  We make sure it has WS_EX_TOOLWINDOW + WS_EX_NOACTIVATE (no
  taskbar/Alt+Tab entry; clicking never activates or raises it) and WS_EX_TRANSPARENT
  while it should be click-through.  It is excluded from Aero Peek.
* Veto: the widget's nativeEvent() turns every z-order change requested by anyone else
  (Qt's raise on show, the system, other programs) into SWP_NOZORDER.  Our own moves use
  SWP_NOSENDCHANGING, which bypasses that message, so only the keeper decides.
* The "desktop host" is the top-level window that currently contains SHELLDLL_DefView
  (the desktop icons): Progman normally and on Windows 11 24H2+, or a WorkerW of
  explorer.exe after the desktop was "split" on older builds.
* Normal state: every widget sits *directly above the desktop host* in the z-order. The
  host is at the bottom, so the widgets are below every app window.
* Show desktop (Win+D) first minimizes the app windows, then raises the host above all
  non-topmost windows — and Explorer may raise it again a moment later.  So while the
  desktop is raised the widgets are made *topmost*, just below the lowest foreign
  topmost window (taskbar etc.); when the desktop drops they become non-topmost and go
  back directly above the host.  "Raised" is detected like Rainmeter does: a hidden
  sentinel window kept at HWND_BOTTOM ends up *below* the host only when the host was
  raised; additionally no visible normal app window may be above the host.
* The keeper runs every 500 ms, every 150 ms while the desktop is raised, and in a short
  burst after every foreground-window change (WinEvent hook): Win+D makes the desktop
  the foreground window, and Explorer finishes re-ordering a few ms later.
* explorer.exe restart: nothing is owned by Explorer, so nothing is destroyed; the
  keeper simply finds the new host on its next pass.

mode "owner" (experimental fallback, settings.json "desktop_mode": "owner"): the host is
also set as the widget's owner (and Qt transient parent), so Windows lifts the widgets
together with the desktop.  Research shows owner groups can drag the desktop up when a
widget is activated and couple input queues with Explorer, so it is not the default.
"""

from __future__ import annotations

import ctypes
import logging
import platform
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QWindow
from PySide6.QtWidgets import QWidget

from versedesk.win32 import api

log = logging.getLogger("versedesk.desktop")

TICK_MS = 500
RAISED_TICK_MS = 150
SOON_MS = 30
BURST_MS = (10, 40, 120, 300, 700, 1200)  # re-checks after a foreground change
SENTINEL_TITLE = "VerseDesk z-order sentinel"
DESKTOP_CLASSES = ("Progman", "WorkerW")
MAX_WALK = 4096
FIGHT_WINDOW_S = 10.0
FIGHT_LIMIT = 12
FIGHT_PAUSE_S = 30.0
MAX_INFO_FIX_LOGS = 40
OUR_ZORDER_FLAGS = (
    api.SWP_NOMOVE | api.SWP_NOSIZE | api.SWP_NOACTIVATE | api.SWP_NOOWNERZORDER | api.SWP_NOSENDCHANGING
)


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


def shell_window() -> int:
    """Explorer's desktop window (class Progman), or 0 if Explorer is not the shell."""
    shell = api.h(api.GetShellWindow())
    if shell and api.class_name(shell) == "Progman":
        return shell
    return api.h(api.FindWindowW("Progman", None))


def find_desktop_host() -> int:
    """HWND of the top-level window hosting the desktop icons (0 if Explorer is not running).

    No Windows-version checks: Progman if it contains SHELLDLL_DefView (normal state, and
    always on Windows 11 24H2+); otherwise the visible top-level WorkerW of Explorer's
    process that contains it (older builds after the desktop was split, e.g. by Win+D or a
    wallpaper slideshow).  File Explorer windows also contain a SHELLDLL_DefView, so only
    Progman/WorkerW windows of the shell's process are considered.
    """
    shell = shell_window()
    if not shell:
        return 0
    if _defview_in(shell):
        return shell
    shell_pid = api.process_id(shell)
    for w in top_level_workerws():
        if api.IsWindowVisible(w) and api.process_id(w) == shell_pid and _defview_in(w):
            return w
    return shell  # transitional (DefView being moved) — re-checked on the next pass


def is_blocking(w: int, host: int) -> bool:
    """Would this window be wrongly covered by a widget sitting above it?"""
    if not api.IsWindowVisible(w) or api.IsIconic(w):
        return False
    ex = api.ex_style(w)
    if ex & (api.WS_EX_TOOLWINDOW | api.WS_EX_NOACTIVATE):
        return False  # other desktop gadgets (e.g. Rainmeter skins), palettes, overlays: no fights
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
    widget at all (the desktop is covering it, e.g. right after Win+D).
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


def blocking_window_above(host: int, own: set[int] | frozenset[int] = frozenset()) -> int:
    """First visible normal (non-topmost) app window above the host, or 0."""
    w = api.h(api.GetWindow(host, api.GW_HWNDPREV))
    for _ in range(MAX_WALK):
        if not w:
            return 0
        if w not in own and not api.is_topmost(w) and is_blocking(w, host):
            return w
        w = api.h(api.GetWindow(w, api.GW_HWNDPREV))
    return 0


def lowest_foreign_topmost_above(host: int, own: set[int] | frozenset[int] = frozenset()) -> int:
    """The topmost window closest above the host (taskbar, overlays...), ignoring ours."""
    w = api.h(api.GetWindow(host, api.GW_HWNDPREV))
    for _ in range(MAX_WALK):
        if not w:
            return 0
        if w not in own and api.is_topmost(w):
            return w
        w = api.h(api.GetWindow(w, api.GW_HWNDPREV))
    return 0


def is_below(target: int, start: int) -> bool:
    """True if ``target`` comes after ``start`` in the z-order (is beneath it)."""
    w = api.h(api.GetWindow(start, api.GW_HWNDNEXT))
    for _ in range(MAX_WALK):
        if not w:
            return False
        if w == target:
            return True
        w = api.h(api.GetWindow(w, api.GW_HWNDNEXT))
    return False


def describe_desktop(own: set[int] | frozenset[int] = frozenset()) -> str:
    try:
        lines = [f"Windows {platform.version()} ({platform.release()}), {platform.machine()}"]
        shell = shell_window()
        lines.append(
            f"  shell (Progman): {api.describe(shell)} defview=0x{_defview_in(shell) if shell else 0:X} "
            f"new_layout={bool(shell and api.ex_style(shell) & api.WS_EX_NOREDIRECTIONBITMAP)}"
        )
        for w in top_level_workerws(32):
            lines.append(f"  WorkerW: {api.describe(w)} defview=0x{_defview_in(w):X}")
        host = find_desktop_host()
        above = blocking_window_above(host, own) if host else 0
        lines.append(f"  desktop host: {api.describe(host)}; first app window above it: {api.describe(above)}")
        # the visible z-order, top to bottom (usually 10-40 windows)
        lines.append("  visible top-level windows, top to bottom:")
        w = api.h(api.GetTopWindow(None))
        n = 0
        for _ in range(MAX_WALK):
            if not w:
                break
            if api.IsWindowVisible(w) or w == host:
                ex = api.ex_style(w)
                tags = []
                if ex & api.WS_EX_TOPMOST:
                    tags.append("TOPMOST")
                if w == host:
                    tags.append("<= DESKTOP HOST")
                if w in own:
                    tags.append("<= VerseDesk")
                if api.IsIconic(w):
                    tags.append("minimized")
                if api.is_cloaked(w):
                    tags.append("cloaked")
                lines.append(f"    {api.describe(w)} {' '.join(tags)}")
                n += 1
                if n >= 60:
                    lines.append("    ...")
                    break
            w = api.h(api.GetWindow(w, api.GW_HWNDNEXT))
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
    def __init__(self, mode: str = "bottom", parent: QObject | None = None):
        super().__init__(parent)
        self.mode = mode if mode in ("bottom", "owner") else "bottom"
        self._pinned: dict[int, _Pinned] = {}
        self._host = 0
        self._raised = False
        self._sentinel = 0
        self._info_fix_logs = 0
        self._vetoes = 0
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
        # owner mode only: QWindow wrappers of desktop hosts used as Qt transient parent.
        # Never deleted: destroying a foreign QWindow must not risk touching Explorer's window.
        self._foreign: dict[int, QWindow] = {}

    # ---- public API

    @property
    def extra_window_flags(self) -> Qt.WindowType:
        return Qt.WindowType.Widget  # no Qt.WindowStaysOnBottomHint: it would fight the Show-desktop lift

    def attach(self, widget: QWidget, *, click_through: bool = False) -> None:
        """Call before the widget is first shown: its native window is created hidden and
        placed on the desktop layer, so it never flashes above other windows."""
        key = id(widget)
        entry = _Pinned(widget, click_through)
        self._pinned[key] = entry
        widget.installEventFilter(self)
        widget.destroyed.connect(lambda *_a, k=key: self._pinned.pop(k, None))
        if hasattr(widget, "set_native_filter"):
            widget.set_native_filter(self.native_filter)
        self._sync_entry(entry, self._current_host(), force=True, allow_hidden=True)

    def detach(self, widget: QWidget) -> None:
        entry = self._pinned.pop(id(widget), None)
        if entry is not None:
            try:
                widget.removeEventFilter(self)
                if hasattr(widget, "set_native_filter"):
                    widget.set_native_filter(None)
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

    def bring_to_front(self, widget: QWidget) -> None:
        """Put the widget above VerseDesk's other widgets (e.g. a new or clicked zone), while
        the group as a whole stays where it is (on the desktop, below every app window)."""
        entry = self._pinned.get(id(widget))
        if entry is None or not entry.hwnd or not api.IsWindow(entry.hwnd):
            return
        own = self._own() - {entry.hwnd}
        highest = 0
        w = api.h(api.GetTopWindow(None))
        for _ in range(MAX_WALK):
            if not w:
                break
            if w in own:
                highest = w
                break
            w = api.h(api.GetWindow(w, api.GW_HWNDNEXT))
        if not highest:
            return
        above = api.h(api.GetWindow(highest, api.GW_HWNDPREV))
        if above == entry.hwnd:
            return  # already directly above the others
        if api.is_topmost(highest) != api.is_topmost(entry.hwnd):
            return  # mid-transition (Show desktop); the next tick sorts the bands out
        ok = api.SetWindowPos(entry.hwnd, above if above else api.HWND_TOP, 0, 0, 0, 0, OUR_ZORDER_FLAGS)
        self._log_fix(entry, f"brought above the other widgets (after {api.describe(above) if above else 'HWND_TOP'})", ok)

    def start(self) -> None:
        log.info("desktop layer mode=%s\n%s", self.mode, describe_desktop(self._own()))
        self._ensure_sentinel()
        self._timer.start()
        if not self._hook:
            flags = api.WINEVENT_OUTOFCONTEXT | api.WINEVENT_SKIPOWNPROCESS
            self._hook = api.SetWinEventHook(
                api.EVENT_SYSTEM_FOREGROUND, api.EVENT_SYSTEM_FOREGROUND, None, self._hook_proc, 0, 0, flags
            )
            if not self._hook:
                log.warning("SetWinEventHook failed (error %s); relying on the timer", ctypes.get_last_error())
        self._tick()

    def stop(self) -> None:
        self._timer.stop()
        self._soon.stop()
        if self._hook:
            api.UnhookWinEvent(self._hook)
            self._hook = None
        if self._sentinel:
            api.DestroyWindow(self._sentinel)
            self._sentinel = 0

    def request_sync(self) -> None:
        if not self._soon.isActive():
            self._soon.start()

    def diagnostics(self) -> str:
        own = self._own()
        lines = [describe_desktop(own)]
        host = find_desktop_host()
        for entry in self._pinned.values():
            hwnd = entry.hwnd
            if not hwnd or not api.IsWindow(hwnd):
                lines.append(f"  widget {entry.widget.objectName()!r}: no window")
                continue
            owner = api.h(api.GetWindow(hwnd, api.GW_OWNER))
            ok, blocker = check_placement(hwnd, host, own)
            lines.append(
                f"  widget {entry.widget.objectName()!r}: {api.describe(hwnd)} ex={_flags(api.ex_style(hwnd))} "
                f"owner={api.describe(owner)} directly_above_desktop={ok}"
                + (f" blocker={api.describe(blocker)}" if blocker else "")
            )
        lines.append(f"  raised={self._raised} sentinel={api.describe(self._sentinel)} vetoes={self._vetoes}")
        return "\n".join(lines)

    # ---- the z-order veto (called from the widget's nativeEvent)

    def native_filter(self, message) -> None:
        """Turn z-order changes requested by anyone else into no-ops. Never raises."""
        try:
            address = int(message)
            if not address:
                return
            msg = api.wintypes.MSG.from_address(address)
            if msg.message != api.WM_WINDOWPOSCHANGING or not msg.lParam:
                return
            wp = api.WINDOWPOS.from_address(msg.lParam)
            if not wp.flags & api.SWP_NOZORDER:
                wp.flags |= api.SWP_NOZORDER
                self._vetoes += 1
                self.request_sync()
        except Exception:
            pass

    # ---- Qt hooks

    def eventFilter(self, obj, event):  # noqa: N802 - Qt naming
        try:
            if event.type() in (QEvent.Type.Show, QEvent.Type.WinIdChange):
                QTimer.singleShot(0, self._tick)
                self.request_sync()
        except Exception:
            log.exception("desktop event filter failed")
        return False

    def _on_win_event(self, hook, event, hwnd, id_object, id_child, thread, ms):  # noqa: ARG002
        try:
            # Win+D makes the desktop the foreground window; Explorer may finish raising it a
            # little later, so look again a few times over the next second.
            for delay in BURST_MS:
                QTimer.singleShot(delay, self._tick)
        except Exception:
            pass

    # ---- the work

    def _own(self) -> set[int]:
        return {e.hwnd for e in self._pinned.values() if e.hwnd}

    def _current_host(self) -> int:
        host = find_desktop_host()
        if host != self._host:
            log.info(
                "desktop host changed: %s -> %s\n%s",
                f"0x{self._host:X}" if self._host else "none",
                api.describe(host),
                describe_desktop(self._own()),
            )
            self._host = host
        return host

    def _ensure_sentinel(self) -> None:
        """A hidden window kept at HWND_BOTTOM (Rainmeter's trick): it lies below the
        desktop host only while Show desktop has raised the host."""
        if self._sentinel and api.IsWindow(self._sentinel):
            return
        self._sentinel = api.h(
            api.CreateWindowExW(
                api.WS_EX_TOOLWINDOW | api.WS_EX_NOACTIVATE,
                "Static",
                SENTINEL_TITLE,
                api.WS_POPUP | api.WS_DISABLED,
                0, 0, 0, 0,
                None, None, api.GetModuleHandleW(None), None,
            )
        )
        if not self._sentinel:
            log.warning("could not create the z-order sentinel (error %s)", ctypes.get_last_error())
            return
        api.SetWindowPos(self._sentinel, api.HWND_BOTTOM, 0, 0, 0, 0, OUR_ZORDER_FLAGS)

    def _is_raised(self, host: int) -> bool:
        if not host or not self._sentinel or not api.IsWindowVisible(host):
            return False
        # FindWindowEx with a child-after window searches the windows *below* it, in the kernel
        if not api.h(api.FindWindowExW(None, host, "Static", SENTINEL_TITLE)):
            return False
        return blocking_window_above(host, self._own()) == 0

    def _tick(self) -> None:
        try:
            host = self._current_host()
            self._ensure_sentinel()
            raised = self._is_raised(host)
            if raised != self._raised:
                self._raised = raised
                log.info("desktop %s", "raised (Show desktop): lifting widgets" if raised else "back to normal")
                self._timer.setInterval(RAISED_TICK_MS if raised else TICK_MS)
            for entry in list(self._pinned.values()):
                self._sync_entry(entry, host)
            if not raised and self._sentinel and host and api.h(api.FindWindowExW(None, host, "Static", SENTINEL_TITLE)):
                # the desktop dropped without passing the sentinel: put it back to the bottom
                api.SetWindowPos(self._sentinel, api.HWND_BOTTOM, 0, 0, 0, 0, OUR_ZORDER_FLAGS)
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
            api.exclude_from_peek(hwnd)
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
                force = True
        if self._raised and self.mode == "bottom":  # (owned widgets rise with their owner)
            if not api.is_topmost(hwnd) or not is_below(host, hwnd):
                self._lift(entry, host)
            return
        if api.is_topmost(hwnd):
            # The desktop dropped again: leave the topmost band and sink in one go. Never
            # gated or counted by the fight limiter, or a paused keeper could leave the
            # widget at the top of the normal band, above every app window.
            api.SetWindowPos(hwnd, api.HWND_NOTOPMOST, 0, 0, 0, 0, OUR_ZORDER_FLAGS)
            self._place_above(entry, host)
            return
        if force or not check_placement(hwnd, host, self._own())[0]:
            if self._may_fix(entry):
                self._place_above(entry, host)

    def _ensure_transient_parent(self, widget: QWidget, host: int) -> None:
        """owner mode: Qt 6.10 re-applies a foreign transient parent as the native owner
        whenever it shows the window, instead of resetting the owner to NULL."""
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
                describe_desktop(self._own()),
            )
            return False
        return True

    def _place_above(self, entry: _Pinned, host: int) -> None:
        """Normal state: put the widget directly above the desktop host in the z-order."""
        hwnd = entry.hwnd
        above = api.h(api.GetWindow(host, api.GW_HWNDPREV))
        if above == hwnd:
            return
        insert_after = above if above else api.HWND_TOP
        ok = api.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, OUR_ZORDER_FLAGS)
        self._log_fix(entry, f"just above the desktop (after {api.describe(above) if above else 'HWND_TOP'})", ok)

    def _lift(self, entry: _Pinned, host: int) -> None:
        """Show desktop: topmost, just below the lowest foreign topmost window."""
        hwnd = entry.hwnd
        ok = api.SetWindowPos(hwnd, api.HWND_TOPMOST, 0, 0, 0, 0, OUR_ZORDER_FLAGS)
        anchor = lowest_foreign_topmost_above(host, self._own())
        if anchor:
            ok = api.SetWindowPos(hwnd, anchor, 0, 0, 0, 0, OUR_ZORDER_FLAGS) and ok
            if not api.is_topmost(hwnd):  # be sure we stayed in the topmost band
                ok = api.SetWindowPos(hwnd, api.HWND_TOPMOST, 0, 0, 0, 0, OUR_ZORDER_FLAGS)
        self._log_fix(entry, f"lifted above the raised desktop (below {api.describe(anchor)})", ok)

    def _log_fix(self, entry: _Pinned, what: str, ok) -> None:
        level = logging.INFO if self._info_fix_logs < MAX_INFO_FIX_LOGS else logging.DEBUG
        self._info_fix_logs += 1
        log.log(level, "widget %r %s ok=%s topmost=%s", entry.widget.objectName(), what, bool(ok),
                api.is_topmost(entry.hwnd))
