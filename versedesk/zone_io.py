"""Background work for folder zones, so a slow or unreachable path never freezes the desktop.

Two worker threads:
  * "zone-probe": does each path still exist, is it a folder, and what is its icon;
  * "zone-open":  opens items (Explorer for folders, the associated program for files).
Results come back as Qt signals, delivered on the GUI thread.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from versedesk import shell
from versedesk.zones import path_key

log = logging.getLogger("versedesk.zone_io")

_STOP = object()


def bgra_to_qimage(data: tuple[int, int, bytes] | None) -> QImage:
    if not data:
        return QImage()
    width, height, pixels = data
    img = QImage(pixels, width, height, width * 4, QImage.Format.Format_ARGB32)
    return img.copy()  # own the pixels (the bytes object goes away)


class ZoneIO(QObject):
    # path, exists, is_dir, icon (a null QImage means: use a generic icon)
    state_ready = Signal(str, bool, bool, QImage)
    # path, error text ("" when it opened)
    open_finished = Signal(str, str)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        probe: Callable[[str], tuple[bool, bool]] = shell.probe,
        icon: Callable[[str, bool, bool], tuple[int, int, bytes] | None] = shell.icon_bgra,
        opener: Callable[[str], str | None] = shell.open_path,
    ):
        super().__init__(parent)
        self._probe = probe
        self._icon = icon
        self._opener = opener
        self._probe_q: queue.Queue = queue.Queue()
        self._open_q: queue.Queue = queue.Queue()
        self._pending: set[str] = set()
        self._pending_lock = threading.Lock()
        self._known: dict[str, tuple[bool, bool]] = {}  # last state per path key (worker side)
        self._threads = [
            threading.Thread(target=self._probe_loop, name="zone-probe", daemon=True),
            threading.Thread(target=self._open_loop, name="zone-open", daemon=True),
        ]
        self._started = False

    def start(self) -> None:
        if not self._started:
            self._started = True
            for t in self._threads:
                t.start()

    def stop(self) -> None:
        if self._started:
            self._probe_q.put(_STOP)
            self._open_q.put(_STOP)

    def check(self, paths, force_icon: bool = False) -> None:
        """Queue paths for an existence check (and an icon when it is new or changed)."""
        self.start()
        for p in paths:
            k = path_key(p)
            with self._pending_lock:
                if k in self._pending:
                    continue
                self._pending.add(k)
            self._probe_q.put((p, force_icon))

    def open(self, path: str) -> None:
        self.start()
        self._open_q.put(path)

    # ---- worker threads

    def _probe_loop(self) -> None:
        com = shell.init_worker_thread()
        try:
            while True:
                job = self._probe_q.get()
                if job is _STOP:
                    return
                path, force_icon = job
                k = path_key(path)
                with self._pending_lock:
                    self._pending.discard(k)
                try:
                    exists, is_dir = self._probe(path)
                    if not exists:
                        is_dir = self._known.get(k, (False, shell.guess_is_dir(path)))[1]
                    changed = self._known.get(k) != (exists, is_dir)
                    self._known[k] = (exists, is_dir)
                    image = bgra_to_qimage(self._icon(path, exists, is_dir)) if (changed or force_icon) else QImage()
                    if changed or force_icon:
                        self.state_ready.emit(path, exists, is_dir, image)
                except Exception:
                    log.exception("checking %s failed", path)
        finally:
            shell.end_worker_thread(com)

    def _open_loop(self) -> None:
        com = shell.init_worker_thread()
        try:
            while True:
                path = self._open_q.get()
                if path is _STOP:
                    return
                try:
                    error = self._opener(path)
                except Exception as e:  # the opener should not raise; belt and braces
                    log.exception("opening %s failed", path)
                    error = str(e) or e.__class__.__name__
                self.open_finished.emit(path, error or "")
        finally:
            shell.end_worker_thread(com)
