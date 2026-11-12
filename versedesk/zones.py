"""Folder zones ("구역"): the data model, kept free of Qt so it can be tested anywhere.

A zone is a named box on the desktop that lists paths to folders and files.  It only
stores the paths (like shortcuts): nothing here ever touches the files themselves.

settings.json layout (a list under "zones"; every key optional):

    "zones": [
      {
        "id": "a1b2c3d4",            # stable identifier (generated)
        "name": "업무",
        "x": 120, "y": 160,          # top-left in logical pixels; null = placed automatically
        "width": 340, "height": 260, # size when expanded (logical pixels at 100% scaling)
        "collapsed": false,          # true = only the title bar is shown
        "items": ["C:\\\\Users\\\\Kim\\\\Documents\\\\보고서", "D:\\\\계획.xlsx"]
      }
    ]

Paths are Windows paths.  Two paths are the same item when they differ only in letter
case, slash direction or a trailing backslash (that is how Windows compares them).
"""

from __future__ import annotations

import copy
import ntpath
import os
import posixpath
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable

DEFAULT_ZONE_NAME = "새 구역"
NAME_MAX = 40
MAX_ITEMS = 500  # far more than fits on a desktop; protects against absurd files
MAX_ZONES = 50

DEFAULT_WIDTH = 340
DEFAULT_HEIGHT = 260
MIN_WIDTH = 160
MIN_HEIGHT = 110
MAX_SIZE = 4000

ZONE_KEYS = ("id", "name", "x", "y", "width", "height", "collapsed", "items")


def _strip(path: str) -> str:
    """Remove surrounding ASCII spaces/line breaks and quotes only: other Unicode spaces
    (no-break, ideographic) can be part of a real Windows file name."""
    return path.strip(" \t\r\n").strip('"')


def _drop_long_prefix(p: str) -> str:
    """'\\\\?\\C:\\x' and '\\\\?\\UNC\\server\\share' name the same items as 'C:\\x' and '\\\\server\\share'."""
    if p[:8].upper() == "\\\\?\\UNC\\":
        return "\\\\" + p[8:]
    if p.startswith("\\\\?\\") or p.startswith("//?/"):
        return p[4:]
    return p


def _posix_path(p: str) -> bool:
    """Off Windows (development, tests) real paths look like '/home/...'; on Windows a
    leading slash is never an absolute path by itself."""
    return (os.name != "nt" and p.startswith("/") and not p.startswith("//")  # "//server/share" is a share
            and not (len(p) > 2 and p[2] == ":"))


def path_key(path: str) -> str:
    """Comparison key for a Windows path: case-insensitive, either slash, no trailing
    separator (except for a drive root like 'C:\\')."""
    raw = _strip(path)
    if _posix_path(raw):
        return posixpath.normpath(raw)
    p = ntpath.normpath(_drop_long_prefix(raw))
    if len(p) > 3 and p.endswith("\\"):
        p = p.rstrip("\\")
    return ntpath.normcase(p)


def clean_path(path: str) -> str | None:
    """The path as it will be stored (normalised separators), or None if unusable."""
    if not isinstance(path, str):
        return None
    p = _strip(path)
    if not p or "\0" in p or len(p) > 32_000:
        return None
    if _posix_path(p):
        return posixpath.normpath(p)
    p = ntpath.normpath(_drop_long_prefix(p))
    if len(p) > 3 and p.endswith("\\"):
        p = p.rstrip("\\")
    # only absolute paths make sense on a desktop ("C:\\..." or "\\\\server\\share\\...")
    drive, _rest = ntpath.splitdrive(p)
    if not drive:
        return None
    return p


def display_name(path: str) -> str:
    """What is written under the icon: the last part of the path, like Explorer shows it."""
    if _posix_path(path):
        return posixpath.basename(path.rstrip("/")) or path
    p = path.rstrip("\\/")
    name = ntpath.basename(p)
    if name:
        return name
    drive, _ = ntpath.splitdrive(path)
    return drive or path  # a drive root such as "C:\\" or a share


def clean_name(name: Any) -> str:
    if not isinstance(name, str):
        return DEFAULT_ZONE_NAME
    name = " ".join(name.split())  # no line breaks or runs of spaces in a title
    return name[:NAME_MAX] if name else DEFAULT_ZONE_NAME


def new_zone_id(existing: Iterable[str] = ()) -> str:
    taken = set(existing)
    while True:
        zid = uuid.uuid4().hex[:8]
        if zid not in taken:
            return zid


@dataclass
class AddResult:
    added: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)  # already in the zone
    invalid: list[str] = field(default_factory=list)  # not a full path
    over_limit: list[str] = field(default_factory=list)  # the zone already holds MAX_ITEMS

    def __bool__(self) -> bool:
        return bool(self.added)


@dataclass
class Zone:
    id: str
    name: str = DEFAULT_ZONE_NAME
    x: int | None = None
    y: int | None = None
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    collapsed: bool = False
    items: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)  # unknown keys, kept for newer versions

    @property
    def has_position(self) -> bool:
        return self.x is not None and self.y is not None

    def keys(self) -> set[str]:
        return {path_key(p) for p in self.items}

    def contains(self, path: str) -> bool:
        return path_key(path) in self.keys()

    def add_paths(self, paths: Iterable[str]) -> AddResult:
        """Append new paths, skipping duplicates and unusable ones, up to MAX_ITEMS."""
        seen = self.keys()
        result = AddResult()
        for raw in paths:
            p = clean_path(raw)
            if p is None:
                result.invalid.append(str(raw))
                continue
            k = path_key(p)
            if k in seen:
                result.duplicates.append(p)
                continue
            if len(self.items) >= MAX_ITEMS:
                result.over_limit.append(p)
                continue
            seen.add(k)
            self.items.append(p)
            result.added.append(p)
        return result

    def remove_path(self, path: str) -> bool:
        k = path_key(path)
        for i, p in enumerate(self.items):
            if path_key(p) == k:
                del self.items[i]
                return True
        return False

    def copy(self) -> "Zone":
        return copy.deepcopy(self)


# --------------------------------------------------------------------------- settings


def _int_in(v: Any, lo: int, hi: int) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, str):
        try:
            v = float(v.strip())
        except ValueError:
            return None
    if isinstance(v, (int, float)):
        try:
            f = float(v)
        except OverflowError:
            return None
        if f == f and lo <= f <= hi:
            return int(round(f))
    return None


def zone_from_dict(data: Any, taken_ids: set[str], index: int) -> tuple[Zone | None, list[str]]:
    """One zone from settings.json. Bad values fall back to defaults (with a warning);
    a zone that is not even an object is dropped."""
    warnings: list[str] = []
    where = f"zones[{index}]"
    if not isinstance(data, dict):
        return None, [f"{where} is not an object; ignored"]
    zid = data.get("id")
    if not isinstance(zid, str) or not zid.strip() or zid in taken_ids or len(zid) > 64:
        zid = new_zone_id(taken_ids)
    z = Zone(id=zid.strip())
    taken_ids.add(z.id)
    z.name = clean_name(data.get("name"))
    if "name" in data and not isinstance(data.get("name"), str):
        warnings.append(f"{where}.name must be text")

    x, y = data.get("x"), data.get("y")
    if x is None and y is None:
        pass
    else:
        cx, cy = _int_in(x, -100_000, 100_000), _int_in(y, -100_000, 100_000)
        if cx is None or cy is None:
            warnings.append(f"{where}.x / y must both be numbers (or both null)")
        else:
            z.x, z.y = cx, cy
    for key, lo, default in (("width", MIN_WIDTH, DEFAULT_WIDTH), ("height", MIN_HEIGHT, DEFAULT_HEIGHT)):
        if key in data:
            val = _int_in(data[key], lo, MAX_SIZE)
            if val is None:
                warnings.append(f"{where}.{key} must be a number from {lo} to {MAX_SIZE}")
                val = default
            setattr(z, key, val)
    if "collapsed" in data:
        if isinstance(data["collapsed"], bool):
            z.collapsed = data["collapsed"]
        else:
            warnings.append(f"{where}.collapsed must be true or false")

    items = data.get("items", [])
    if not isinstance(items, list):
        warnings.append(f"{where}.items must be a list of paths")
        items = []
    bad = 0
    for raw in items:
        if clean_path(raw) is None:
            bad += 1
    if bad:
        warnings.append(f"{where}.items: {bad} entr{'y is' if bad == 1 else 'ies are'} not a full path; ignored")
    z.add_paths([p for p in items if isinstance(p, str)])
    z.extra = {k: copy.deepcopy(v) for k, v in data.items() if k not in ZONE_KEYS}
    return z, warnings


def zones_from_list(data: Any) -> tuple[list[Zone], list[str]]:
    if data is None:
        return [], []
    if not isinstance(data, list):
        return [], ["zones must be a list"]
    zones: list[Zone] = []
    warnings: list[str] = []
    taken: set[str] = set()
    for i, entry in enumerate(data[:MAX_ZONES]):
        z, w = zone_from_dict(entry, taken, i)
        warnings.extend(w)
        if z is not None:
            zones.append(z)
    if len(data) > MAX_ZONES:
        warnings.append(f"only the first {MAX_ZONES} zones are used")
    return zones, warnings


def zone_to_dict(z: Zone) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": z.id,
        "name": z.name,
        "x": z.x,
        "y": z.y,
        "width": z.width,
        "height": z.height,
        "collapsed": z.collapsed,
        "items": list(z.items),
    }
    for k, v in z.extra.items():
        out.setdefault(k, copy.deepcopy(v))
    return out


def zones_to_list(zones: Iterable[Zone]) -> list[dict[str, Any]]:
    return [zone_to_dict(z) for z in zones]


def find_zone(zones: Iterable[Zone], zone_id: str) -> Zone | None:
    for z in zones:
        if z.id == zone_id:
            return z
    return None
