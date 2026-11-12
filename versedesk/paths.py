"""Where VerseDesk keeps its files.

Windows:  %APPDATA%\\VerseDesk\\settings.json, log.txt, verses.json (the user's verse list, if saved)
Elsewhere (development only): ~/.config/VerseDesk/...
The VERSEDESK_HOME environment variable overrides the folder (used by tests and CI).
"""

from __future__ import annotations

import os
from pathlib import Path

from versedesk import APP_NAME

PACKAGE_DIR = Path(__file__).resolve().parent


def app_data_dir() -> Path:
    override = os.environ.get("VERSEDESK_HOME")
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / APP_NAME
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / APP_NAME


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


def log_path() -> Path:
    return app_data_dir() / "log.txt"


def crash_path() -> Path:
    return app_data_dir() / "crash.txt"


def user_verses_path() -> Path:
    return app_data_dir() / "verses.json"


def embedded_verses_path() -> Path:
    return PACKAGE_DIR / "data" / "verses.json"


def embedded_bible_path() -> Path:
    return PACKAGE_DIR / "data" / "bsb.txt.xz"


def embedded_psalm_titles_path() -> Path:
    return PACKAGE_DIR / "data" / "psalm_titles.json"


def asset_path(name: str) -> Path:
    return PACKAGE_DIR / "assets" / name
