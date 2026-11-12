"""Platform facade for what folder zones need from the operating system.

On Windows the real work is in ``versedesk.win32.shell``; elsewhere (development, the Linux
test run) there are simple stand-ins.  All of these may block on slow or network paths,
so they are only called from worker threads (see ``versedesk.zone_io``).
"""

from __future__ import annotations

import logging
import ntpath
import os
import subprocess
import sys

log = logging.getLogger("versedesk.shell")

IS_WINDOWS = sys.platform == "win32"


def probe(path: str) -> tuple[bool, bool]:
    """(exists, is_dir). Never raises."""
    try:
        if os.path.isdir(path):
            return True, True
        return os.path.exists(path), False
    except (OSError, ValueError):
        return False, False


def guess_is_dir(path: str) -> bool:
    """For a path that cannot be reached: no extension usually means a folder."""
    return not ntpath.splitext(path.rstrip("\\/"))[1]


def icon_bgra(path: str, exists: bool, is_dir: bool) -> tuple[int, int, bytes] | None:
    """The system icon as (width, height, BGRA bytes), or None to use a generic icon."""
    if not IS_WINDOWS:
        return None
    try:
        from versedesk.win32 import shell as win_shell

        return win_shell.file_icon_bgra(path, exists, is_dir)
    except Exception:
        log.exception("could not get the icon of %s", path)
        return None


def open_path(path: str) -> str | None:
    """Open a folder in the file manager or a file in its program. None or an error text."""
    try:
        if IS_WINDOWS:
            from versedesk.win32 import shell as win_shell

            return win_shell.open_path(path)
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([opener, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return None
    except Exception as e:  # never let a failed open reach the GUI
        log.exception("could not open %s", path)
        return str(e) or e.__class__.__name__


def init_worker_thread() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        from versedesk.win32 import shell as win_shell

        return win_shell.init_thread_com()
    except Exception:
        log.exception("COM initialisation failed in a worker thread")
        return False


def end_worker_thread(com_initialised: bool) -> None:
    if com_initialised and IS_WINDOWS:
        try:
            from versedesk.win32 import shell as win_shell

            win_shell.uninit_thread_com()
        except Exception:
            pass
