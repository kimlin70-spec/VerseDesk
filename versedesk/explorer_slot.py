"""Explorer window slot ("탐색기 창 자리 고정"): the data and the arithmetic, free of Qt and Win32.

The user fixes one rectangle on the screen (shown as a frame in 배치 편집); every File
Explorer window opened afterwards is moved there (see explorer_placer.py).  Nothing else
is touched: other programs' windows, Explorer windows that were already open, and windows
the user moves later all stay where they are.

settings.json keeps the slot under "explorer_window" (every key optional):

    "explorer_window": {
      "enabled": false,             # true = new Explorer windows open in the slot
      "x": null, "y": null,         # top-left in logical pixels; null = centre of the main screen
      "width": 900, "height": 600   # logical pixels (at 100 % scaling)
    }

Coordinates: settings and Qt use *logical* pixels, Windows moves windows in *native*
(physical) pixels.  ``to_native`` converts the way Qt itself does for a top-level window:
a screen's top-left corner is the same point in both spaces, distances from it are
multiplied by that screen's scale factor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

from versedesk.geometry import Rect, clamp_into

DEFAULT_WIDTH = 900
DEFAULT_HEIGHT = 600
MIN_WIDTH = 480  # File Explorer itself does not get much smaller
MIN_HEIGHT = 320
MAX_SIZE = 8000
SLOT_KEYS = ("enabled", "x", "y", "width", "height")

NativeRect = tuple[int, int, int, int]  # left, top, right, bottom in native (physical) pixels


@dataclass
class SlotSettings:
    enabled: bool = False
    x: int | None = None
    y: int | None = None
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT

    @property
    def has_position(self) -> bool:
        return self.x is not None and self.y is not None


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


def slot_from_dict(data: Any, previous: SlotSettings | None = None) -> tuple[SlotSettings, list[str]]:
    """The slot from settings.json. A missing key gets its default; an invalid value keeps
    the ``previous`` value (while the user is editing the file) or the default."""
    prev = previous or SlotSettings()
    s = SlotSettings()
    warnings: list[str] = []
    if data is None:
        return s, warnings
    if not isinstance(data, dict):
        return SlotSettings(prev.enabled, prev.x, prev.y, prev.width, prev.height), ["explorer_window must be an object"]
    if "enabled" in data:
        if isinstance(data["enabled"], bool):
            s.enabled = data["enabled"]
        else:
            s.enabled = prev.enabled
            warnings.append("explorer_window.enabled must be true or false")
    x, y = data.get("x"), data.get("y")
    if x is not None or y is not None:
        cx, cy = _int_in(x, -100_000, 100_000), _int_in(y, -100_000, 100_000)
        if cx is None or cy is None:
            s.x, s.y = prev.x, prev.y
            warnings.append("explorer_window.x / y must both be numbers (or both null)")
        else:
            s.x, s.y = cx, cy
    for key, lo in (("width", MIN_WIDTH), ("height", MIN_HEIGHT)):
        if key in data:
            val = _int_in(data[key], lo, MAX_SIZE)
            if val is None:
                val = getattr(prev, key)
                warnings.append(f"explorer_window.{key} must be a number from {lo} to {MAX_SIZE}")
            setattr(s, key, val)
    return s, warnings


def slot_to_dict(s: SlotSettings) -> dict[str, Any]:
    return {"enabled": s.enabled, "x": s.x, "y": s.y, "width": s.width, "height": s.height}


def default_rect(area: Rect, width: int, height: int) -> Rect:
    """Centred in ``area`` (the main screen's work area), shrunk to fit if the screen is small."""
    w = max(MIN_WIDTH, min(width, area.w - 80))
    h = max(MIN_HEIGHT, min(height, area.h - 80))
    return clamp_into(Rect(area.x + (area.w - w) // 2, area.y + (area.h - h) // 2, w, h), area)


@dataclass(frozen=True)
class ScreenInfo:
    rect: Rect  # the screen's geometry in logical pixels (QScreen.geometry())
    scale: float  # QScreen.devicePixelRatio(): 1.0, 1.25, 1.5 ...


def screen_for(rect: Rect, screens: Sequence[ScreenInfo]) -> ScreenInfo | None:
    """The screen a window with this geometry belongs to: the one holding its centre,
    else the one showing most of it, else the first (main) screen."""
    if not screens:
        return None
    cx, cy = rect.x + rect.w // 2, rect.y + rect.h // 2
    for s in screens:
        if s.rect.x <= cx < s.rect.right and s.rect.y <= cy < s.rect.bottom:
            return s
    best = max(screens, key=lambda s: rect.intersection_area(s.rect))
    return best if rect.intersection_area(best.rect) > 0 else screens[0]


def _qround(value: float) -> int:
    """Round half up, like Qt's qRound (Python's round() rounds halves to even)."""
    return int(math.floor(value + 0.5))


def to_native(rect: Rect, screens: Sequence[ScreenInfo]) -> NativeRect | None:
    """Logical rectangle -> native (left, top, right, bottom), or None without screens."""
    s = screen_for(rect, screens)
    if s is None or s.scale <= 0:
        return None
    left = s.rect.x + _qround((rect.x - s.rect.x) * s.scale)
    top = s.rect.y + _qround((rect.y - s.rect.y) * s.scale)
    return (left, top, left + _qround(rect.w * s.scale), top + _qround(rect.h * s.scale))


def outer_rect(target: NativeRect, window: NativeRect, visible: NativeRect) -> NativeRect:
    """Where the *window rectangle* must go so that the *visible frame* lands on ``target``.

    Windows 10/11 windows have invisible resize borders: the window rectangle
    (GetWindowRect) is a few pixels larger on the left, right and bottom than what is seen
    (DWM's extended frame bounds).  ``window`` and ``visible`` are the two as measured now.
    """
    left = max(0, visible[0] - window[0])
    top = max(0, visible[1] - window[1])
    right = max(0, window[2] - visible[2])
    bottom = max(0, window[3] - visible[3])
    if max(left, top, right, bottom) > 64:  # not a border: a bogus measurement (e.g. mid-animation)
        left = top = right = bottom = 0
    return (target[0] - left, target[1] - top, target[2] + right, target[3] + bottom)


def close_enough(a: NativeRect, b: NativeRect, tolerance: int = 1) -> bool:
    return all(abs(p - q) <= tolerance for p, q in zip(a, b))
