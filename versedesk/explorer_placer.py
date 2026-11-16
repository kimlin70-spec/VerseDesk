"""Open File Explorer windows in the user's fixed place ("탐색기 창 자리 고정").

``ExplorerPlacer`` ties together
  * the slot kept in settings.json (versedesk/explorer_slot.py),
  * the frame shown in 배치 편집 (versedesk/ui/slot_frame.py), and
  * a *watcher* that reports Explorer windows as they appear and can move them
    (versedesk/win32/explorer.py on Windows; none elsewhere, so nothing happens there).

Rules (kept deliberately narrow):
  * off by default; while it is off nothing is watched at all;
  * only Explorer windows that come on screen after the feature was switched on are placed,
    each once - windows that were already open, and windows the user moves afterwards, are
    left alone;
  * a window is placed when it is really on screen (visible, not cloaked), never earlier;
  * nothing is moved while the mouse button is held: a double-click that is still held is
    waited for, a window that was dragged meanwhile (a tab pulled out of another window)
    stays where the user dropped it, and once the user grabs something the app lets go;
  * moving never waits for Explorer (asynchronous requests); the result is looked at a
    moment later and corrected a limited number of times, then the window is left alone;
  * every failure is logged and ignored - this must never disturb the rest of the app.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from typing import Callable, Sequence

from PySide6.QtCore import QObject, QTimer

from versedesk.explorer_slot import (
    NativeRect,
    ScreenInfo,
    SlotSettings,
    close_enough,
    default_rect,
    fit_into,
    outer_rect,
    to_native,
)
from versedesk.geometry import Rect, best_screen, place_on_screens
from versedesk.settings import LoadResult, SettingsStore

log = logging.getLogger("versedesk.explorer")

MAX_MOVES = 3  # the first move plus two corrections (e.g. after crossing to a monitor with another scale)
CHECK_MS = 150  # how soon after a request the result is looked at
MAX_CHECKS = 40  # ...and how often at most (about 6 s for an Explorer that is slow to respond)
CONFIRM_MS = 400  # one more look after the window first sat in the slot
MOUSE_WAIT_MS = 200  # while the mouse button is held: look again this often
MAX_MOUSE_WAITS = 150  # ...for at most 30 s
MAX_HIDDEN_CHECKS = 20  # a window reported while hidden or cloaked: wait about 3 s, then forget it
REFUSED_AFTER = 4  # looks without any change after a repeated request: the window keeps its own size
TOLERANCE = 1  # native pixels
MAX_AGAIN_LOGS = 5


def create_explorer_watcher():
    """The Windows watcher, or None elsewhere (and if it cannot be set up: the feature then
    simply does nothing, the rest of the app is unaffected)."""
    if sys.platform != "win32":
        return None
    try:
        from versedesk.win32.explorer import ExplorerWatcher

        return ExplorerWatcher()
    except Exception:
        log.exception("explorer window slot: Windows support could not be initialised")
        return None


@dataclass
class _Job:
    first_rect: NativeRect  # the window rectangle when the window was first seen
    moves: int = 0
    checks: int = 0
    hidden_checks: int = 0
    mouse_waits: int = 0
    unchanged: int = 0  # looks at which the window was still where it was when last asked to move
    restore_asked: bool = False
    in_slot: bool = False  # it sat in the slot at the last look (one confirming look follows)
    counted: bool = False
    asked_from: NativeRect | None = None  # the window rectangle when the last move was requested


class ExplorerPlacer(QObject):
    def __init__(
        self,
        store: SettingsStore,
        *,
        work_areas: Callable[[], tuple[list[Rect], Rect]],
        screens: Callable[[], Sequence[ScreenInfo]],
        apply_reload: Callable[[LoadResult | None], None],
        watcher=None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._store = store
        self._work_areas = work_areas
        self._screens = screens
        self._apply_reload = apply_reload
        self._watcher = watcher
        self._watching = False
        self._edit = False
        self._frame = None
        self._seen: set[int] = set()
        self._jobs: dict[int, _Job] = {}
        self._again_logs = 0
        self.placed = 0  # windows put into the slot since the start (for diagnostics and tests)

    # ------------------------------------------------------------------ settings and frame

    @property
    def slot(self) -> SlotSettings:
        return self._store.settings.explorer_window

    def slot_rect(self) -> Rect:
        """The slot in logical pixels: the saved place (brought back onto a screen if its
        monitor is gone) or, before the user placed it, the middle of the main screen."""
        rects, primary = self._work_areas()
        s = self.slot
        if not s.has_position:
            return default_rect(primary, s.width, s.height)
        r = place_on_screens(Rect(s.x, s.y, s.width, s.height), rects, primary)
        i, _overlap = best_screen(r, rects)
        return fit_into(r, rects[i] if i >= 0 else primary)  # a slot larger than this screen is shown smaller

    def native_target(self) -> NativeRect | None:
        return to_native(self.slot_rect(), list(self._screens()))

    def start(self) -> None:
        self.sync_from_settings()

    def stop(self) -> None:
        try:
            self._unwatch()
            if self._frame is not None:
                self._frame.hide()
        except Exception:  # quitting must never be held up by this feature
            log.exception("explorer window slot: stop failed")

    def set_edit_mode(self, on: bool) -> None:
        self._edit = on
        try:
            self._update_frame()
        except Exception:  # 배치 편집 itself must keep working
            log.exception("explorer window slot: could not show or hide the frame")

    def sync_from_settings(self) -> None:
        """Follow settings.json (start-up, the tray item, edits made outside the app)."""
        try:
            if self.slot.enabled and not self._watching:
                self._watch()
            elif not self.slot.enabled and self._watching:
                self._unwatch()
            self._update_frame()
        except Exception:
            log.exception("explorer window slot: could not apply the settings")

    def reposition(self) -> None:
        """Screens changed: keep the frame on a screen and the watcher alive."""
        try:
            self._update_frame()
            if self._watching and self._watcher is not None:
                self._watcher.refresh()
        except Exception:
            log.exception("explorer window slot: reposition failed")

    def _update_frame(self) -> None:
        show = self._edit and self.slot.enabled
        if not show:
            if self._frame is not None:
                self._frame.hide()
            return
        if self._frame is None:
            from versedesk.ui.slot_frame import SlotFrame

            self._frame = SlotFrame()
            self._frame.geometry_edited.connect(self._on_frame_edited)
        r = self.slot_rect()
        g = self._frame.geometry()
        if (g.x(), g.y(), g.width(), g.height()) != (r.x, r.y, r.w, r.h):
            self._frame.setGeometry(r.x, r.y, r.w, r.h)
        if not self._frame.isVisible():
            self._frame.show()

    def _on_frame_edited(self, x: int, y: int, width: int, height: int) -> None:
        try:
            rects, primary = self._work_areas()
            placed = place_on_screens(Rect(x, y, width, height), rects, primary)

            def mutate(s):
                slot = s.explorer_window
                slot.x, slot.y, slot.width, slot.height = placed.x, placed.y, placed.w, placed.h

            self._apply_reload(self._store.update(mutate))
            self._update_frame()  # the frame shows exactly what was saved
            log.info("explorer window slot set to (%d, %d) %dx%d -> native %s%s",
                     placed.x, placed.y, placed.w, placed.h, self.native_target(), self._frame_on_screen())
        except Exception:
            log.exception("explorer window slot: could not save the new place")

    def _frame_on_screen(self) -> str:
        """Where Windows really has the frame (for log.txt): must equal the computed native slot."""
        if self._frame is None or not self._frame.isVisible() or self._watcher is None:
            return ""
        return f"; the frame window is at {self._watcher.window_rect(int(self._frame.winId()))}"

    # ------------------------------------------------------------------ watching

    def _watch(self) -> None:
        if self._watcher is None:
            return  # not on Windows: the setting and the frame work, nothing is moved
        # What the user has open now is never touched. (A window Explorer keeps hidden for
        # later is not "open": it is placed when it first comes on screen.)
        self._seen = set(self._watcher.open_explorer_windows())
        if self._watcher.start(self._on_window_event):
            self._watching = True
            log.info("explorer window slot on: slot %s -> native %s; %d Explorer window(s) already open are left alone\n%s",
                     self.slot_rect(), self.native_target(), len(self._seen), self._watcher.describe_all())
        else:
            log.warning("explorer window slot: could not start watching for new windows")

    def _unwatch(self) -> None:
        was = self._watching
        self._watching = False
        self._jobs.clear()
        self._seen.clear()
        if was and self._watcher is not None:
            self._watcher.stop()
            log.info("explorer window slot off")

    def _on_window_event(self, hwnd: int, created: bool = True) -> None:
        """An Explorer window was shown (``created``) or activated; called by the watcher on
        the GUI thread.  Activation is the fallback for a window whose showing was not
        reported or happened while it could not be placed yet."""
        try:
            w = self._watcher
            if not self._watching or not hwnd:
                return
            self._seen = {h for h in self._seen if w.exists(h)}  # forget closed windows (handles get reused)
            if hwnd in self._seen:
                if created and hwnd not in self._jobs and self._again_logs < MAX_AGAIN_LOGS:
                    self._again_logs += 1
                    log.info("explorer window shown again, left alone (placed or already open before): %s", w.describe(hwnd))
                return
            if not w.is_explorer_window(hwnd):
                return
            self._seen.add(hwnd)
            self._jobs[hwnd] = _Job(first_rect=w.window_rect(hwnd))
            self._step(hwnd)
        except Exception:
            log.exception("explorer window slot: new-window handling failed")

    def _later(self, hwnd: int, ms: int) -> None:
        QTimer.singleShot(ms, lambda: self._step(hwnd))

    def _step(self, hwnd: int) -> None:
        job = self._jobs.get(hwnd)
        if job is None:
            return
        try:
            done = self._advance(hwnd, job)
        except Exception:
            log.exception("explorer window slot: placing failed")
            done = True
        if done:
            self._jobs.pop(hwnd, None)

    def _advance(self, hwnd: int, job: _Job) -> bool:
        """One look at the window. Returns True when there is nothing more to do with it."""
        w = self._watcher
        if not self._watching or not w.exists(hwnd):
            return True
        if not w.is_visible(hwnd) or w.is_cloaked(hwnd):
            # Not on screen (yet): it is not placed now, and it does not count as handled, so
            # that it is placed when it really appears (reported again, or activated).
            job.hidden_checks += 1
            if job.hidden_checks > MAX_HIDDEN_CHECKS:
                self._seen.discard(hwnd)
                log.info("explorer window is not on screen yet (hidden or cloaked); it will be placed when it shows: %s",
                         w.describe(hwnd))
                return True
            self._later(hwnd, CHECK_MS)
            return False
        if w.is_minimized(hwnd):
            return True
        if w.mouse_button_down():
            if job.moves:
                return True  # the user has taken hold of something: hands off from now on
            job.mouse_waits += 1
            if job.mouse_waits > MAX_MOUSE_WAITS:
                return True
            self._later(hwnd, MOUSE_WAIT_MS)
            return False
        window = w.window_rect(hwnd)
        if job.mouse_waits and not job.moves and window != job.first_rect:
            log.info("explorer window was dragged while it opened; left where the user put it: %s", w.describe(hwnd))
            return True
        target = self.native_target()
        if target is None:
            return True
        job.checks += 1
        if job.checks > MAX_CHECKS:
            log.warning("explorer window: gave up waiting for it to respond: %s", w.describe(hwnd))
            return True
        if w.is_maximized(hwnd):
            # Ask once to un-maximise, then only wait: a maximised window must not be moved,
            # and its borders cannot be measured.
            if not job.restore_asked:
                job.restore_asked = True
                log.info("explorer window opened maximised; restoring it before placing: %s", w.describe(hwnd))
                if not w.restore(hwnd):
                    log.warning("explorer window: could not be restored (error %s): %s", w.last_error(), w.describe(hwnd))
                    return True
            self._later(hwnd, CHECK_MS)
            return False
        visible = w.visible_rect(hwnd) or window
        if close_enough(visible, target, TOLERANCE):
            if not job.in_slot:
                job.in_slot = True
                if job.moves:
                    if not job.counted:
                        job.counted = True
                        self.placed += 1
                    log.info("explorer window placed in the slot %s after %d move(s): %s", target, job.moves, w.describe(hwnd))
                    self._later(hwnd, CONFIRM_MS)  # ...and one more look: did it stay?
                    return False
                log.info("explorer window opened in the slot %s by itself: %s", target, w.describe(hwnd))
            return True
        job.in_slot = False
        if job.asked_from is not None and window == job.asked_from:
            # Explorer has not carried out the last request (yet): wait, do not pile up requests.
            job.unchanged += 1
            if job.moves >= 2 and job.unchanged >= REFUSED_AFTER:
                log.warning("explorer window keeps its own size or place: visible frame %s, wanted %s; left as it is: %s",
                            visible, target, w.describe(hwnd))
                return True
            self._later(hwnd, CHECK_MS)
            return False
        if job.moves >= MAX_MOVES:
            log.warning("explorer window: visible frame %s after %d moves, wanted %s; left as it is: %s",
                        visible, job.moves, target, w.describe(hwnd))
            return True
        if not w.move(hwnd, outer_rect(target, window, visible)):
            log.warning("explorer window: Windows refused the move (error %s): %s", w.last_error(), w.describe(hwnd))
            return True
        job.moves += 1
        job.unchanged = 0
        job.asked_from = window
        self._later(hwnd, CHECK_MS)
        return False

    def diagnostics(self) -> str:
        try:
            s = self.slot
            state = "on" if s.enabled else "off"
            if s.enabled and not self._watching:
                state += " (not watching)"
            return (f"explorer window slot: {state}, slot {self.slot_rect()} -> native {self.native_target()}, "
                    f"{self.placed} placed, {len(self._jobs)} in progress")
        except Exception as e:  # diagnostics must never fail
            return f"explorer window slot: (diagnostics failed: {e})"
