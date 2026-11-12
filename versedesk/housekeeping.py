"""Remove leftovers of earlier runs of the one-file exe.

PyInstaller's one-file exe unpacks itself into %TEMP%\\_MEIxxxxxx and deletes that folder
when the program ends normally.  A resident app is often ended by Windows shutting down,
which can leave the folder behind (tens of MB each time).  At startup we delete such
folders, but only when it is certain they are VerseDesk's and unused:
  * the name starts with _MEI and it contains versedesk/data/verses.json,
  * it is not the folder this process runs from,
  * it can be renamed — Windows refuses to rename a folder while any program has a file
    inside it open, so a folder still in use by another instance is never touched.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

log = logging.getLogger("versedesk.housekeeping")


def stale_extraction_dirs(temp_dir: Path, current: Path | None) -> list[Path]:
    out = []
    try:
        entries = list(temp_dir.iterdir())
    except OSError:
        return out
    for d in entries:
        try:
            if not d.name.startswith("_MEI") or not d.is_dir():
                continue
            if current is not None and d.resolve() == current.resolve():
                continue
            if (d / "versedesk" / "data" / "verses.json").is_file():
                out.append(d)
        except OSError:
            continue
    return out


def remove_if_unused(d: Path) -> bool:
    trash = d.with_name(d.name + ".versedesk-old")
    try:
        os.rename(d, trash)  # fails if anything inside is in use
    except OSError:
        return False
    shutil.rmtree(trash, ignore_errors=True)
    return True


def clean_stale_extractions(temp_dir: Path | None = None, current: Path | None = None) -> int:
    temp_dir = Path(temp_dir or tempfile.gettempdir())
    if current is None and getattr(sys, "_MEIPASS", None):
        current = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    removed = 0
    for d in stale_extraction_dirs(temp_dir, current):
        if remove_if_unused(d):
            removed += 1
    # also finish deleting anything a previous cleanup could not remove completely
    try:
        for leftover in temp_dir.glob("_MEI*.versedesk-old"):
            shutil.rmtree(leftover, ignore_errors=True)
    except OSError:
        pass
    if removed:
        log.info("removed %d leftover temporary folder(s) from earlier runs", removed)
    return removed


def clean_in_background() -> None:
    """Only for the frozen exe; never blocks startup."""
    if not getattr(sys, "frozen", False):
        return

    def run():
        try:
            clean_stale_extractions()
        except Exception:
            log.exception("cleanup of temporary folders failed")

    threading.Thread(target=run, name="housekeeping", daemon=True).start()
