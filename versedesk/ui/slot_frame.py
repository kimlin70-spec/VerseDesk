"""The frame that shows (in 배치 편집) where new Explorer windows will open.

A translucent rectangle the user drags to move and resizes by its bottom-right corner.
It is only an editing aid: visible while 배치 편집 is on and the feature is enabled, and
it floats above other windows so it can be seen wherever it is.  It is not part of the
desktop layer and never takes the keyboard focus.

Monitors with different scaling: Qt's logical coordinates have gaps between such monitors,
and a window that straddles two of them changes its logical size.  So while it is dragged
the frame always lies wholly on the monitor under the mouse and keeps the size it had when
it was grabbed; while it is resized it never grows past its own monitor.

The widget only reports what the user did (``geometry_edited``); ``ExplorerPlacer``
saves it.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen, QPolygon
from PySide6.QtWidgets import QWidget

from versedesk.explorer_slot import MIN_HEIGHT, MIN_WIDTH

WINDOW_TITLE = "VerseDesk Explorer Slot"
GRIP = 22
FILL = QColor(40, 110, 220, 70)
EDGE = QColor(255, 255, 255, 235)
EDGE_SHADOW = QColor(10, 40, 110, 200)
TEXT_BACK = QColor(10, 40, 110, 170)
TITLE_TEXT = "탐색기 창 자리"
HINT_TEXT = "끌어서 옮기기 · 오른쪽 아래 모서리를 끌어 크기 바꾸기\n다 되면 트레이 메뉴 → 배치 편집 끄기"


class SlotFrame(QWidget):
    geometry_edited = Signal(int, int, int, int)  # x, y, width, height (logical px)

    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setWindowTitle(WINDOW_TITLE)
        self.setObjectName("explorer-slot")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(MIN_WIDTH, MIN_HEIGHT)
        self._press: tuple[str, object, QRect] | None = None

    def grip_rect(self) -> QRect:
        return QRect(self.width() - GRIP, self.height() - GRIP, GRIP, GRIP)

    # ------------------------------------------------------------------ painting

    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        rect = self.rect()
        # first, without antialiasing and one pixel past the edge (fractional scaling): every
        # pixel has alpha > 0, so the whole frame can be grabbed
        p.fillRect(rect.adjusted(0, 0, 1, 1), FILL)
        for color, inset in ((EDGE_SHADOW, 0), (EDGE, 2)):
            pen = QPen(color, 2, Qt.PenStyle.SolidLine if inset == 0 else Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawRect(rect.adjusted(inset + 1, inset + 1, -inset - 1, -inset - 1))
        # the resize corner: a dark triangle with light lines, visible on any background
        g = self.grip_rect()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(EDGE_SHADOW)
        p.drawPolygon(QPolygon([QPoint(g.right() + 1, g.top()), QPoint(g.right() + 1, g.bottom() + 1),
                                QPoint(g.left(), g.bottom() + 1)]))
        p.setPen(QPen(EDGE, 2))
        r = g.adjusted(0, 0, -4, -4)
        for k in (4, 9, 14):
            p.drawLine(r.right() - k, r.bottom(), r.right(), r.bottom() - k)

        title_font = QFont(self.font())
        title_font.setPointSizeF(15)
        title_font.setBold(True)
        hint_font = QFont(self.font())
        hint_font.setPointSizeF(9.5)
        p.setFont(title_font)
        title_h = p.fontMetrics().height()
        p.setFont(hint_font)
        hint_h = p.fontMetrics().lineSpacing() * 2
        block = QRect(0, 0, min(rect.width() - 24, 460), title_h + hint_h + 26)
        block.moveCenter(rect.center())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(TEXT_BACK)
        p.drawRoundedRect(block, 8, 8)
        p.setPen(EDGE)
        p.setFont(title_font)
        p.drawText(QRect(block.x(), block.y() + 8, block.width(), title_h), Qt.AlignmentFlag.AlignHCenter, TITLE_TEXT)
        p.setFont(hint_font)
        p.drawText(QRect(block.x() + 6, block.y() + 14 + title_h, block.width() - 12, hint_h),
                   Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap, HINT_TEXT)
        p.end()

    # ------------------------------------------------------------------ mouse

    @staticmethod
    def _area(screen) -> QRect:
        return screen.availableGeometry().intersected(screen.geometry())

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            kind = "resize" if self.grip_rect().contains(event.position().toPoint()) else "move"
            self._press = (kind, event.globalPosition().toPoint(), self.geometry())
        event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._press and event.buttons() & Qt.MouseButton.LeftButton:
            kind, start, geo = self._press
            cursor = event.globalPosition().toPoint()
            delta = cursor - start
            if kind == "move":  # the size it had when grabbed, wholly on the monitor under the mouse
                area = self._area(QGuiApplication.screenAt(cursor) or self.screen())
                target = QRect(geo.topLeft() + delta, geo.size())
                target.moveLeft(max(area.left(), min(target.left(), area.right() + 1 - target.width())))
                target.moveTop(max(area.top(), min(target.top(), area.bottom() + 1 - target.height())))
                self.setGeometry(target)
            else:  # never larger than what fits on its own monitor
                area = self._area(self.screen())
                self.resize(max(MIN_WIDTH, min(geo.width() + delta.x(), area.right() + 1 - geo.x())),
                            max(MIN_HEIGHT, min(geo.height() + delta.y(), area.bottom() + 1 - geo.y())))
        elif self.grip_rect().contains(event.position().toPoint()):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        else:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._press is not None:
            kind, _start, geo = self._press
            self._press = None
            if self.geometry() != geo:
                # a move never changes the size, whatever the monitors did to the numbers on the way
                w, h = (geo.width(), geo.height()) if kind == "move" else (self.width(), self.height())
                self.geometry_edited.emit(self.x(), self.y(), w, h)
        event.accept()
