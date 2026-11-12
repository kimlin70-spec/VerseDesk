"""settings.json — load, validate, save atomically, and notice edits made outside the app.

Pure Python (no Qt) so it can be unit-tested on any OS.

File layout (all keys optional; anything missing or invalid falls back to the default):

    {
      "version": 1,
      "autostart": true,
      "desktop_mode": "bottom",
      "debug_log": false,             # true = very detailed log.txt (for troubleshooting)
      "verse": {
        "x": null, "y": null,          # top-left position; null = default (top-right of main screen)
        "width": 520,                  # text box width in pixels (at 100% scaling)
        "font_family": "Georgia",
        "font_size": 20,               # points
        "reference_font_size": null,   # points; null = 65% of font_size
        "color": "#FFFFFF",
        "shadow": true,
        "align": "right"               # left | center | right
      },
      "zones": [ ... ]                 # folder zones, see versedesk/zones.py
    }

Unknown top-level keys (for example ones written by a newer version) are kept as-is.
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

from versedesk.zones import Zone, zones_from_list, zones_to_list

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
    debug_log: bool = False
    verse: VerseSettings = field(default_factory=VerseSettings)
    zones: list[Zone] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)  # unknown keys, preserved verbatim

    def copy(self) -> "Settings":
        return copy.deepcopy(self)


# --------------------------------------------------------------------------- validation


def _num(v: Any) -> float | None:
    """A number, also accepting numeric text such as "32" (easy to type in Notepad)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        try:
            f = float(v)
        except OverflowError:  # an integer with hundreds of digits
            return None
        return f if f == f else None  # f == f rejects NaN
    if isinstance(v, str):
        try:
            f = float(v.strip())
        except ValueError:
            return None
        return f if f == f else None
    return None


def _int_in(v: Any, lo: int, hi: int) -> int | None:
    n = _num(v)
    if n is not None and lo <= n <= hi:
        return int(round(n))
    return None


def _float_in(v: Any, lo: float, hi: float) -> float | None:
    n = _num(v)
    if n is not None and lo <= n <= hi:
        return n
    return None


def _coord(v: Any) -> int | None:
    # Positions may be negative on multi-monitor setups; reject absurd values.
    return _int_in(v, -100_000, 100_000)


def settings_from_dict(data: Any, previous: Settings | None = None) -> tuple[Settings, list[str]]:
    """Build Settings from parsed JSON. Returns (settings, warnings).

    A missing key gets its default. An invalid value keeps the ``previous`` value (when
    re-reading a file the user is editing) or, at first load, the default.
    """
    warnings: list[str] = []
    s = Settings()
    prev = previous.copy() if previous is not None else Settings()
    if not isinstance(data, dict):
        warnings.append("settings.json top level is not an object; keeping the previous settings")
        return prev, warnings

    known = {"version", "autostart", "desktop_mode", "debug_log", "verse", "zones"}
    s.extra = {k: copy.deepcopy(v) for k, v in data.items() if k not in known}

    if "autostart" in data:
        if isinstance(data["autostart"], bool):
            s.autostart = data["autostart"]
        else:
            s.autostart = prev.autostart
            warnings.append("autostart must be true or false")

    if "debug_log" in data:
        if isinstance(data["debug_log"], bool):
            s.debug_log = data["debug_log"]
        else:
            s.debug_log = prev.debug_log
            warnings.append("debug_log must be true or false")

    if "desktop_mode" in data:
        if data["desktop_mode"] in DESKTOP_MODES:
            s.desktop_mode = data["desktop_mode"]
        else:
            s.desktop_mode = prev.desktop_mode
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
        vs.x, vs.y = prev.verse.x, prev.verse.y
        warnings.append("verse.x / verse.y must both be numbers (or both null)")

    def take(key: str, conv: Callable[[Any], Any], what: str) -> None:
        if key not in v:
            return
        val = conv(v[key])
        if val is None:
            setattr(vs, key, getattr(prev.verse, key))
            warnings.append(f"verse.{key} {what}; keeping {getattr(vs, key)!r}")
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

    if "zones" in data:
        if isinstance(data["zones"], list):
            s.zones, zone_warnings = zones_from_list(data["zones"])
            warnings.extend(zone_warnings)
        else:
            s.zones = [z.copy() for z in prev.zones]
            warnings.append("zones must be a list; keeping the previous zones")
    return s, warnings


def settings_to_dict(s: Settings) -> dict[str, Any]:
    vs = s.verse
    out: dict[str, Any] = {
        "version": SETTINGS_VERSION,
        "autostart": s.autostart,
        "desktop_mode": s.desktop_mode,
        "debug_log": s.debug_log,
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
        "zones": zones_to_list(s.zones),
    }
    for k, val in s.extra.items():
        out.setdefault(k, copy.deepcopy(val))
    return out


def dumps(s: Settings) -> str:
    return json.dumps(settings_to_dict(s), ensure_ascii=False, indent=2) + "\n"


# --------------------------------------------------------------------------- file helpers


def decode_text(raw: bytes) -> str:
    """Decode a file the user may have saved with Notepad or PowerShell:
    UTF-8 (with or without BOM), UTF-16 (with BOM, or BOM-less ASCII-range text) or ANSI."""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace")  # a stray odd byte must not stop the app
    if len(raw) >= 4 and raw[1] == 0 and raw[3] == 0 and raw[0] != 0:
        try:
            return raw.decode("utf-16-le")
        except UnicodeDecodeError:
            pass
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return raw.decode("mbcs")  # Windows ANSI code page (e.g. CP949 on Korean Windows)
        except (LookupError, UnicodeDecodeError):
            return raw.decode("cp1252", errors="replace")


def read_text_lenient(path: Path) -> str:
    return decode_text(path.read_bytes())


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
    unreadable: bool = False  # could not even be opened (locked by another program?): retried later


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
        self._unreadable = False  # the existing file could not be opened yet

    # ---- reading

    def load(self) -> LoadResult:
        if not self.path.exists():
            self.settings = Settings()
            self._sig, self._digest = None, None
            return LoadResult(self.settings.copy(), first_run=True)
        result = self._read(previous=None)
        if result.error is None:
            self.settings = result.settings.copy()
        else:
            if not result.unreadable:
                self._backup_broken()
            self.settings = Settings()
            result.settings = self.settings.copy()
        return result

    def _read(self, previous: Settings | None) -> LoadResult:
        sig = _stat_signature(self.path)
        raw = None
        last_err: OSError | None = None
        for attempt in range(3):  # antivirus, backup or sync tools may hold the file briefly
            try:
                raw = self.path.read_bytes()
                break
            except OSError as e:
                last_err = e
                if attempt < 2:
                    time.sleep(0.15 * (attempt + 1))
        if raw is None:
            self._unreadable = True
            self._sig, self._digest = None, None  # keep trying on every poll
            return LoadResult(Settings(), error=f"settings.json: cannot open the file: {last_err}", unreadable=True)
        self._unreadable = False
        try:
            data = json.loads(decode_text(raw))
        except json.JSONDecodeError as e:
            self._broken_sig = sig
            return LoadResult(Settings(), error=describe_json_error("settings.json", e))
        except (ValueError, RecursionError) as e:  # e.g. a number thousands of digits long
            self._broken_sig = sig
            return LoadResult(Settings(), error=f"settings.json: cannot be read ({type(e).__name__}: {e})"[:300])
        try:
            settings, warnings = settings_from_dict(data, previous)
        except Exception as e:  # an odd value must never keep the app from starting
            log.exception("settings.json: unexpected content")
            self._broken_sig = sig
            return LoadResult(Settings(), error=f"settings.json: unexpected content ({type(e).__name__})")
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
        result = self._read(previous=self.settings)
        if result.error is None:
            self.settings = result.settings.copy()
        else:
            result.settings = self.settings.copy()
        return result

    # ---- writing

    def save(self) -> bool:
        if self._unreadable and self.path.exists():
            # Never replace a file we have not been able to read: it holds the user's settings
            # (update() re-reads it first; poll() picks it up once it can be opened).
            log.error("settings.json still cannot be opened; not saving over it")
            return False
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
        if self._unreadable and self.path.exists():
            # Could not be opened so far: read it now, before the change, so the change is
            # applied on top of the user's real settings rather than replacing them later.
            result = self._read(previous=self.settings)
            if result.error is None:
                self.settings = result.settings.copy()
                reloaded = result
        mutate(self.settings)
        self.save()
        return reloaded
