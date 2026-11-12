"""settings.json — load, validate, save atomically, and notice edits made outside the app.

Pure Python (no Qt) so it can be unit-tested on any OS.

File layout (all keys optional; anything missing or invalid falls back to the default):

    {
      "version": 1,
      "autostart": true,
      "desktop_mode": "bottom",
      "verse": {
        "x": null, "y": null,          # top-left position; null = default (top-right of main screen)
        "width": 520,                  # text box width in pixels (at 100% scaling)
        "font_family": "Georgia",
        "font_size": 20,               # points
        "reference_font_size": null,   # points; null = 65% of font_size
        "color": "#FFFFFF",
        "shadow": true,
        "align": "right"               # left | center | right
      }
    }

Unknown top-level keys (for example "zones" written by a newer version) are kept as-is.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("versedesk.settings")

SETTINGS_VERSION = 1

ALIGN_CHOICES = ("left", "center", "right")
DESKTOP_MODES = ("bottom", "owner")
_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


@dataclass
class VerseSettings:
    x: int | None = None
    y: int | None = None
    width: int = 520
    font_family: str = "Georgia"
    font_size: float = 20.0
    reference_font_size: float | None = None
    color: str = "#FFFFFF"
    shadow: bool = True
    align: str = "right"

    @property
    def has_custom_position(self) -> bool:
        return self.x is not None and self.y is not None

    def effective_reference_font_size(self) -> float:
        if self.reference_font_size is not None:
            return self.reference_font_size
        return max(6.0, round(self.font_size * 0.65, 1))


@dataclass
class Settings:
    autostart: bool = True
    desktop_mode: str = "bottom"
    verse: VerseSettings = field(default_factory=VerseSettings)
    extra: dict[str, Any] = field(default_factory=dict)  # unknown keys, preserved verbatim

    def copy(self) -> "Settings":
        return copy.deepcopy(self)


# --------------------------------------------------------------------------- validation


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _int_in(v: Any, lo: int, hi: int) -> int | None:
    if _is_number(v) and v == v and lo <= v <= hi:  # v == v rejects NaN
        return int(round(v))
    return None


def _float_in(v: Any, lo: float, hi: float) -> float | None:
    if _is_number(v) and v == v and lo <= v <= hi:
        return float(v)
    return None


def _coord(v: Any) -> int | None:
    # Positions may be negative on multi-monitor setups; reject absurd values.
    return _int_in(v, -100_000, 100_000)


def settings_from_dict(data: Any) -> tuple[Settings, list[str]]:
    """Build Settings from parsed JSON. Returns (settings, warnings)."""
    warnings: list[str] = []
    s = Settings()
    if not isinstance(data, dict):
        warnings.append("settings.json top level is not an object; using defaults")
        return s, warnings

    known = {"version", "autostart", "desktop_mode", "verse"}
    s.extra = {k: copy.deepcopy(v) for k, v in data.items() if k not in known}

    if "autostart" in data:
        if isinstance(data["autostart"], bool):
            s.autostart = data["autostart"]
        else:
            warnings.append("autostart must be true or false")

    if "desktop_mode" in data:
        if data["desktop_mode"] in DESKTOP_MODES:
            s.desktop_mode = data["desktop_mode"]
        else:
            warnings.append(f"desktop_mode must be one of {DESKTOP_MODES}")

    v = data.get("verse", {})
    if not isinstance(v, dict):
        warnings.append("verse must be an object")
        v = {}
    vs = s.verse

    x, y = v.get("x"), v.get("y")
    if x is None and y is None:
        pass
    elif _coord(x) is not None and _coord(y) is not None:
        vs.x, vs.y = _coord(x), _coord(y)
    else:
        warnings.append("verse.x / verse.y must both be numbers (or both null)")

    def take(key: str, conv: Callable[[Any], Any], what: str) -> None:
        if key not in v:
            return
        val = conv(v[key])
        if val is None:
            warnings.append(f"verse.{key} {what}; using default {getattr(vs, key)!r}")
        else:
            setattr(vs, key, val)

    take("width", lambda a: _int_in(a, 150, 4000), "must be a number from 150 to 4000")
    take(
        "font_family",
        lambda a: a.strip() if isinstance(a, str) and a.strip() and len(a) <= 100 else None,
        "must be a font name",
    )
    take("font_size", lambda a: _float_in(a, 6, 200), "must be a number from 6 to 200")
    if "reference_font_size" in v and v["reference_font_size"] is None:
        vs.reference_font_size = None
    else:
        take("reference_font_size", lambda a: _float_in(a, 4, 200), "must be null or a number from 4 to 200")
    take("color", lambda a: a if isinstance(a, str) and _COLOR_RE.match(a) else None, "must look like #FFFFFF")
    take("shadow", lambda a: a if isinstance(a, bool) else None, "must be true or false")
    take("align", lambda a: a if a in ALIGN_CHOICES else None, f"must be one of {ALIGN_CHOICES}")
    return s, warnings


def settings_to_dict(s: Settings) -> dict[str, Any]:
    vs = s.verse
    out: dict[str, Any] = {
        "version": SETTINGS_VERSION,
        "autostart": s.autostart,
        "desktop_mode": s.desktop_mode,
        "verse": {
            "x": vs.x,
            "y": vs.y,
            "width": vs.width,
            "font_family": vs.font_family,
            "font_size": int(vs.font_size) if float(vs.font_size).is_integer() else vs.font_size,
            "reference_font_size": (
                None
                if vs.reference_font_size is None
                else int(vs.reference_font_size)
                if float(vs.reference_font_size).is_integer()
                else vs.reference_font_size
            ),
            "color": vs.color,
            "shadow": vs.shadow,
            "align": vs.align,
        },
    }
    for k, val in s.extra.items():
        out.setdefault(k, copy.deepcopy(val))
    return out


def dumps(s: Settings) -> str:
    return json.dumps(settings_to_dict(s), ensure_ascii=False, indent=2) + "\n"


# --------------------------------------------------------------------------- file helpers


def read_text_lenient(path: Path) -> str:
    """Read a text file the user may have edited with Notepad (UTF-8, UTF-8 BOM or ANSI)."""
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return raw.decode("mbcs")  # Windows ANSI code page (e.g. CP949 on Korean Windows)
        except (LookupError, UnicodeDecodeError):
            return raw.decode("cp1252", errors="replace")


def describe_json_error(name: str, e: json.JSONDecodeError) -> str:
    return f"{name}: line {e.lineno}, column {e.colno}: {e.msg}"


def atomic_write_text(path: Path, text: str) -> None:
    """Write via a temporary file + rename so a crash never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    last_err: OSError | None = None
    for attempt in range(6):
        try:
            os.replace(tmp, path)
            return
        except PermissionError as e:  # another program briefly has the file open
            last_err = e
            time.sleep(0.05 * (attempt + 1))
    log.warning("atomic replace of %s failed (%s); writing in place", path, last_err)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    try:
        tmp.unlink()
    except OSError:
        pass


@dataclass(frozen=True)
class _Signature:
    mtime_ns: int
    size: int


def _stat_signature(path: Path) -> _Signature | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return _Signature(st.st_mtime_ns, st.st_size)


@dataclass
class LoadResult:
    settings: Settings
    first_run: bool = False  # the file did not exist
    error: str | None = None  # the file existed but could not be used
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- store


class SettingsStore:
    """Owns the in-memory Settings and its file.

    * ``load()`` at startup.
    * ``update(fn)`` for every change made by the app: it first picks up edits the user
      made to the file in the meantime, then applies ``fn`` and saves.
    * ``poll()`` periodically: returns a LoadResult when the file was changed from outside.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.settings = Settings()
        self._sig: _Signature | None = None
        self._digest: str | None = None
        self._broken_sig: _Signature | None = None  # signature of a file we failed to parse

    # ---- reading

    def load(self) -> LoadResult:
        if not self.path.exists():
            self.settings = Settings()
            self._sig, self._digest = None, None
            return LoadResult(self.settings.copy(), first_run=True)
        result = self._read()
        if result.error is None:
            self.settings = result.settings.copy()
        else:
            self._backup_broken()
            self.settings = Settings()
            result.settings = self.settings.copy()
        return result

    def _read(self) -> LoadResult:
        sig = _stat_signature(self.path)
        try:
            raw = self.path.read_bytes()
            text = read_text_lenient(self.path)
            data = json.loads(text)
        except json.JSONDecodeError as e:
            self._broken_sig = sig
            return LoadResult(Settings(), error=describe_json_error("settings.json", e))
        except OSError as e:
            self._broken_sig = sig
            return LoadResult(Settings(), error=f"settings.json: cannot read: {e}")
        settings, warnings = settings_from_dict(data)
        self._sig = sig
        self._digest = hashlib.sha256(raw).hexdigest()
        self._broken_sig = None
        return LoadResult(settings, warnings=warnings)

    def _backup_broken(self) -> None:
        try:
            bad = self.path.with_name(self.path.name + ".bad")
            bad.write_bytes(self.path.read_bytes())
            log.warning("kept a copy of the unreadable settings file as %s", bad)
        except OSError as e:
            log.warning("could not back up unreadable settings file: %s", e)

    def changed_on_disk(self) -> bool:
        sig = _stat_signature(self.path)
        if sig is None:
            return False  # deleted: keep running with what we have; next save recreates it
        if sig == self._sig or sig == self._broken_sig:
            return False
        try:
            digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        except OSError:
            return False
        if digest == self._digest:
            self._sig = sig  # touched but identical
            return False
        return True

    def poll(self) -> LoadResult | None:
        """If the file was edited outside the app, re-read it.

        Returns None when nothing changed. On a parse error the current settings are
        kept and the error is returned (once per distinct broken version of the file).
        """
        if not self.changed_on_disk():
            return None
        result = self._read()
        if result.error is None:
            self.settings = result.settings.copy()
        else:
            result.settings = self.settings.copy()
        return result

    # ---- writing

    def save(self) -> bool:
        try:
            if self._broken_sig is not None and _stat_signature(self.path) == self._broken_sig:
                self._backup_broken()
            text = dumps(self.settings)
            atomic_write_text(self.path, text)
            self._sig = _stat_signature(self.path)
            self._digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
            self._broken_sig = None
            return True
        except OSError as e:
            log.error("could not save %s: %s", self.path, e)
            return False

    def update(self, mutate: Callable[[Settings], None]) -> LoadResult | None:
        """Apply ``mutate`` and save. Returns the reload result if outside edits were picked up."""
        reloaded = self.poll()
        mutate(self.settings)
        self.save()
        return reloaded
