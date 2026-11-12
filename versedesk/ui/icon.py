"""The VerseDesk icon (an open book on a navy tile), drawn in code.

Used at runtime for the tray icon (no image files needed) and by tools/make_icon.py to
produce assets/versedesk.ico for the exe.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap

ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def draw_icon(size: int) -> QImage:
    s = float(size)
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # tile
        tile = QRectF(0.5, 0.5, s - 1.0, s - 1.0) if size <= 24 else QRectF(s * 0.03, s * 0.03, s * 0.94, s * 0.94)
        grad = QLinearGradient(tile.topLeft(), tile.bottomLeft())
        grad.setColorAt(0.0, QColor("#2F5D8C"))
        grad.setColorAt(1.0, QColor("#16304F"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(tile, s * 0.22, s * 0.22)

        # open book
        cx = s * 0.5
        top, bottom = s * 0.27, s * 0.73
        left, right = s * 0.15, s * 0.85
        dip = s * 0.05  # pages dip toward the spine

        def page(x_outer: float) -> QPainterPath:
            path = QPainterPath(QPointF(cx, top + dip))
            path.quadTo(QPointF((cx + x_outer) / 2, top - dip * 0.6), QPointF(x_outer, top))
            path.lineTo(QPointF(x_outer, bottom - dip))
            path.quadTo(QPointF((cx + x_outer) / 2, bottom - dip * 1.6), QPointF(cx, bottom))
            path.closeSubpath()
            return path

        p.setBrush(QColor("#FBF7EE"))
        p.drawPath(page(left))
        p.drawPath(page(right))

        # spine
        pen = QPen(QColor("#16304F"))
        pen.setWidthF(max(1.0, s * 0.03))
        p.setPen(pen)
        p.drawLine(QPointF(cx, top + dip), QPointF(cx, bottom))

        # text lines on the pages (only where they are visible)
        if size >= 32:
            line_pen = QPen(QColor(22, 48, 79, 110))
            line_pen.setWidthF(max(1.0, s * 0.018))
            p.setPen(line_pen)
            for i in range(4):
                y = top + dip + (bottom - top - 2 * dip) * (0.22 + 0.18 * i)
                p.drawLine(QPointF(left + s * 0.07, y), QPointF(cx - s * 0.06, y + dip * 0.4))
                p.drawLine(QPointF(cx + s * 0.06, y + dip * 0.4), QPointF(right - s * 0.07, y))

        # gold ribbon
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#E8B64C"))
        rw = max(1.5, s * 0.07)
        ribbon = QPainterPath(QPointF(cx + s * 0.04, bottom - s * 0.02))
        ribbon.lineTo(QPointF(cx + s * 0.04 + rw, bottom - s * 0.02))
        ribbon.lineTo(QPointF(cx + s * 0.04 + rw, bottom + s * 0.13))
        ribbon.lineTo(QPointF(cx + s * 0.04 + rw / 2, bottom + s * 0.10))
        ribbon.lineTo(QPointF(cx + s * 0.04, bottom + s * 0.13))
        ribbon.closeSubpath()
        p.drawPath(ribbon)
    finally:
        p.end()
    return img


def app_icon() -> QIcon:
    icon = QIcon()
    for size in ICON_SIZES:
        icon.addPixmap(QPixmap.fromImage(draw_icon(size)))
    return icon
