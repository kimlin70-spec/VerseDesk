"""Screen-placement rules, as plain integer rectangles (no Qt) so they can be unit-tested.

All coordinates are Qt logical (device-independent) pixels, the same space that
QWidget.pos() and QScreen.availableGeometry() use.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:  # exclusive
        return self.x + self.w

    @property
    def bottom(self) -> int:  # exclusive
        return self.y + self.h

    @property
    def area(self) -> int:
        return max(0, self.w) * max(0, self.h)

    def moved_to(self, x: int, y: int) -> "Rect":
        return Rect(x, y, self.w, self.h)

    def intersection_area(self, other: "Rect") -> int:
        w = min(self.right, other.right) - max(self.x, other.x)
        h = min(self.bottom, other.bottom) - max(self.y, other.y)
        return w * h if w > 0 and h > 0 else 0

    def contains_rect(self, other: "Rect") -> bool:
        return (
            other.x >= self.x
            and other.y >= self.y
            and other.right <= self.right
            and other.bottom <= self.bottom
        )


def clamp_into(rect: Rect, area: Rect) -> Rect:
    """Shift ``rect`` (size unchanged) so it lies inside ``area``; if it is larger, align top-left."""
    x = rect.x
    y = rect.y
    if rect.w >= area.w:
        x = area.x
    else:
        x = min(max(x, area.x), area.right - rect.w)
    if rect.h >= area.h:
        y = area.y
    else:
        y = min(max(y, area.y), area.bottom - rect.h)
    return rect.moved_to(x, y)


def best_screen(rect: Rect, screens: Sequence[Rect]) -> tuple[int, int]:
    """(index, overlap area) of the screen that shows the largest part of ``rect``; (-1, 0) if none."""
    best_i, best_a = -1, 0
    for i, s in enumerate(screens):
        a = rect.intersection_area(s)
        if a > best_a:
            best_i, best_a = i, a
    return best_i, best_a


def place_on_screens(
    rect: Rect,
    screens: Sequence[Rect],
    primary: Rect,
    min_visible_fraction: float = 0.5,
) -> Rect:
    """Keep a saved window position usable.

    * entirely inside one screen        -> unchanged
    * mostly (>= min_visible_fraction) on one screen -> nudged fully onto that screen
    * otherwise (off-screen, monitor unplugged, resolution shrank) -> moved onto the primary screen
    """
    for s in screens:
        if s.contains_rect(rect):
            return rect
    i, overlap = best_screen(rect, screens)
    if i >= 0 and rect.area > 0 and overlap >= rect.area * min_visible_fraction:
        return clamp_into(rect, screens[i])
    return clamp_into(rect, primary)


def top_right(area: Rect, w: int, h: int, margin_x: int, margin_y: int) -> Rect:
    """A w x h rectangle in the top-right corner of ``area`` (falls back to the left edge if too wide)."""
    x = max(area.x, area.right - w - margin_x)
    y = area.y + margin_y
    return clamp_into(Rect(x, y, w, h), area)
