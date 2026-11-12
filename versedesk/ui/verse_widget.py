"""The 'verse of the day' window: white serif text with a dark halo + soft shadow, on a
fully transparent background, so it reads on any wallpaper.

Normal mode: purely decorative; the desktop layer makes it click-through.
Edit mode ("배치 편집"): a dashed frame appears and the window can be dragged; the new
position is reported through the ``moved`` signal when the mouse button is released.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

log = logging.getLogger("versedesk.ui.verse")

PADDING = 20  # logical px around the text; leaves room for the shadow
OUTLINE_ALPHA = 140
EDIT_HINT = "배치 편집 중 · 끌어서 옮기세요"


@dataclass(frozen=True)
class VerseAppearance:
    width: int = 520
    font_family: str = "Georgia"
    font_size: float = 20.0
    reference_font_size: float = 13.0
    color: str = "#FFFFFF"
    shadow: bool = True
    align: str = "right"

    @classmethod
    def from_settings(cls, vs) -> "VerseAppearance":
        return cls(
            width=vs.width,
            font_family=vs.font_family,
            font_size=vs.font_size,
            reference_font_size=vs.effective_reference_font_size(),
            color=vs.color,
            shadow=vs.shadow,
            align=vs.align,
        )


_ALIGN = {"left": Qt.AlignmentFlag.AlignLeft, "center": Qt.AlignmentFlag.AlignHCenter, "right": Qt.AlignmentFlag.AlignRight}


def _shadow(owner: QWidget, blur: float, dx: float, dy: float, alpha: int) -> QGraphicsDropShadowEffect:
    # Parent the effect: an unparented effect created in Python is garbage-collected (and
    # silently removed from the widget) as soon as the last Python reference goes away.
    e = QGraphicsDropShadowEffect(owner)
    e.setBlurRadius(blur)
    e.setOffset(dx, dy)
    e.setColor(QColor(0, 0, 0, alpha))
    return e


class _Canvas(QWidget):
    """Paints the text. Lives inside two wrapper widgets that carry the shadow effects."""

    def __init__(self, owner: "VerseWidget", parent: QWidget):
        super().__init__(parent)
        self._owner = owner
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event):  # noqa: N802
        try:
            self._owner._paint(self)
        except Exception:
            log.exception("painting the verse failed")


class VerseWidget(QWidget):
    moved = Signal(int, int)  # top-left after a drag in edit mode (logical px)

    def __init__(self, appearance: VerseAppearance | None = None, extra_flags=Qt.WindowType.Widget):
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.NoDropShadowWindowHint
            | extra_flags
        )
        super().__init__(None, flags)
        self.setObjectName("verse")
        self.setWindowTitle("VerseDesk Verse")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._appearance = appearance or VerseAppearance()
        self._text = ""
        self._reference = ""
        self._edit = False
        self._drag_offset: QPoint | None = None
        self._text_rect = QRectF()
        self._ref_rect = QRectF()
        self._outer_fx: QGraphicsDropShadowEffect | None = None

        # The canvas paints white text over a thin dark outline; its holder adds a soft shadow.
        # Together they stay legible on white, black, busy photos and stripes.
        self._outer = QWidget(self)
        self._outer.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._canvas = _Canvas(self, self._outer)
        self._apply_effects()
        self.relayout()

    # ---- public API

    @property
    def edit_mode(self) -> bool:
        return self._edit

    @property
    def text(self) -> str:
        return self._text

    @property
    def reference(self) -> str:
        return self._reference

    def set_verse(self, text: str, reference: str) -> None:
        self._text = text
        self._reference = reference
        self.relayout()

    def set_appearance(self, appearance: VerseAppearance) -> None:
        if appearance == self._appearance:
            return
        self._appearance = appearance
        self._apply_effects()
        self.relayout()

    def set_edit_mode(self, on: bool) -> None:
        self._edit = on
        self._drag_offset = None
        self.setCursor(Qt.CursorShape.SizeAllCursor if on else Qt.CursorShape.ArrowCursor)
        self._canvas.update()

    # ---- layout & painting

    def _fonts(self) -> tuple[QFont, QFont]:
        a = self._appearance
        text_font = QFont(a.font_family)
        text_font.setPointSizeF(a.font_size)
        text_font.setStyleHint(QFont.StyleHint.Serif)
        ref_font = QFont(a.font_family)
        ref_font.setPointSizeF(a.reference_font_size)
        ref_font.setItalic(True)
        ref_font.setStyleHint(QFont.StyleHint.Serif)
        return text_font, ref_font

    def _flags(self) -> int:
        return int(_ALIGN.get(self._appearance.align, Qt.AlignmentFlag.AlignRight) | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap)

    def relayout(self) -> None:
        a = self._appearance
        text_font, ref_font = self._fonts()
        inner_w = max(50, a.width - 2 * PADDING)
        fm = QFontMetricsF(text_font, self)
        text_h = 0.0
        if self._text:
            br = fm.boundingRect(QRectF(0, 0, inner_w, 100_000), self._flags(), self._text)
            text_h = br.height()
        ref_h = QFontMetricsF(ref_font, self).height() if self._reference else 0.0
        gap = fm.height() * 0.35 if (self._text and self._reference) else 0.0
        self._text_rect = QRectF(PADDING, PADDING, inner_w, text_h)
        self._ref_rect = QRectF(PADDING, PADDING + text_h + gap, inner_w, ref_h)
        total_h = int(math.ceil(PADDING + text_h + gap + ref_h + PADDING))
        self.setFixedSize(a.width, max(total_h, 2 * PADDING))
        for w in (self._outer, self._canvas):
            w.setGeometry(0, 0, self.width(), self.height())
        self._canvas.update()

    def _apply_effects(self) -> None:
        if self._appearance.shadow:
            self._outer_fx = _shadow(self._outer, 14, 0, 1.5, 200)  # keep a Python reference too
            self._outer.setGraphicsEffect(self._outer_fx)
        else:
            self._outer.setGraphicsEffect(None)
            self._outer_fx = None

    def _paint(self, canvas: QWidget) -> None:
        a = self._appearance
        p = QPainter(canvas)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            if self._edit:
                frame = QRectF(canvas.rect()).adjusted(3, 3, -3, -3)
                p.setBrush(QColor(0, 0, 0, 80))
                p.setPen(QPen(QColor(255, 255, 255, 200), 1.5, Qt.PenStyle.DashLine))
                p.drawRoundedRect(frame, 10, 10)
                hint_font = QFont()
                hint_font.setPointSizeF(8.5)
                p.setFont(hint_font)
                p.setPen(QColor(255, 255, 255, 220))
                p.drawText(QRectF(12, 4, canvas.width() - 24, PADDING - 4), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), EDIT_HINT)
            text_font, ref_font = self._fonts()
            color = QColor(a.color)
            if not color.isValid():
                color = QColor("#FFFFFF")
            ref_color = QColor(color)
            ref_color.setAlphaF(min(1.0, color.alphaF() * 0.92))
            self._draw_outlined(p, text_font, self._text_rect, self._text, color)
            if self._reference:
                self._draw_outlined(p, ref_font, self._ref_rect, self._reference, ref_color)
        finally:
            p.end()

    def _draw_outlined(self, p: QPainter, font: QFont, rect: QRectF, text: str, color: QColor) -> None:
        """White text with a thin dark outline: the text is first drawn in translucent black
        at 8 small offsets around its position, then in the real colour on top."""
        if not text:
            return
        p.setFont(font)
        flags = self._flags()
        if self._appearance.shadow:
            px = QFontMetricsF(font, self).height()
            radius = min(3.0, max(1.0, px * 0.045))
            p.setPen(QColor(0, 0, 0, OUTLINE_ALPHA))
            for k in range(8):
                angle = k * math.pi / 4
                p.drawText(rect.translated(radius * math.cos(angle), radius * math.sin(angle)), flags, text)
        p.setPen(color)
        p.drawText(rect, flags, text)

    # ---- dragging (edit mode only)

    def mousePressEvent(self, event):  # noqa: N802
        if self._edit and event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._edit and self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._drag_offset is not None and event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = None
            pos = self.pos()
            self.moved.emit(pos.x(), pos.y())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def changeEvent(self, event):  # noqa: N802
        # Different monitor / scale factor: font metrics may change slightly.
        if event.type() in (QEvent.Type.FontChange,):
            self.relayout()
        super().changeEvent(event)
