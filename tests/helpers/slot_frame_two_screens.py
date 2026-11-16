"""Run in its own process on Qt's offscreen platform with two fake monitors (150 % left,
100 % right): drag and resize the Explorer slot frame across the monitor boundary and print
what happened as JSON.  Used by tests/test_slot_frame.py.

The mouse moves in *native* pixels (as a real mouse does); Qt reports it in logical
coordinates, which have a gap between two such monitors (logical x 1280..1919 does not exist).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from versedesk.ui.slot_frame import SlotFrame  # noqa: E402

app = QApplication(sys.argv[:1])
screens = QGuiApplication.screens()
NATIVE = []  # (native x, y, w, h, scale, logical x, y)
for s in screens:
    g, f = s.geometry(), s.devicePixelRatio()
    NATIVE.append((g.x(), g.y(), round(g.width() * f), round(g.height() * f), f))


def to_logical(nx, ny):
    for x, y, w, h, f in NATIVE:
        if x <= nx < x + w and y <= ny < y + h:
            return x + (nx - x) / f, y + (ny - y) / f
    raise ValueError((nx, ny))


def to_native(lx, ly):
    for s in screens:
        g, f = s.geometry(), s.devicePixelRatio()
        if g.contains(int(lx), int(ly)):
            return g.x() + (lx - g.x()) * f, g.y() + (ly - g.y()) * f
    raise ValueError((lx, ly))


def drag(start_rect, grab, native_delta, steps=80):
    frame = SlotFrame()
    saved = []
    frame.geometry_edited.connect(lambda *a: saved.append(list(a)))
    frame.setGeometry(*start_rect)
    frame.show()
    app.processEvents()
    nx0, ny0 = to_native(start_rect[0] + grab[0], start_rect[1] + grab[1])

    def event(kind, nx, ny, button, buttons):
        pos = QPointF(*to_logical(nx, ny))
        return QMouseEvent(kind, pos - QPointF(frame.pos()), pos, button, buttons, Qt.KeyboardModifier.NoModifier)

    left = Qt.MouseButton.LeftButton
    frame.mousePressEvent(event(QEvent.Type.MouseButtonPress, nx0, ny0, left, left))
    sizes, outside, hops, last = set(), 0, 0, frame.screen().name()
    nx, ny = nx0, ny0
    for i in range(1, steps + 1):
        nx, ny = nx0 + native_delta[0] * i / steps, ny0 + native_delta[1] * i / steps
        frame.mouseMoveEvent(event(QEvent.Type.MouseMove, nx, ny, Qt.MouseButton.NoButton, left))
        app.processEvents()
        g = frame.geometry()
        sizes.add((g.width(), g.height()))
        if not any(s.geometry().contains(g) for s in screens):
            outside += 1
        if frame.screen().name() != last:
            hops, last = hops + 1, frame.screen().name()
    frame.mouseReleaseEvent(event(QEvent.Type.MouseButtonRelease, nx, ny, left, Qt.MouseButton.NoButton))
    app.processEvents()
    g = frame.geometry()
    result = {"saved": saved, "sizes": sorted(sizes), "steps_not_on_one_screen": outside, "screen_changes": hops,
              "final": [g.x(), g.y(), g.width(), g.height()], "final_screen": frame.screen().name()}
    frame.hide()
    frame.deleteLater()
    return result


out = {
    "screens": [[s.name(), s.geometry().x(), s.geometry().y(), s.geometry().width(), s.geometry().height(),
                 s.devicePixelRatio()] for s in screens],
    # grabbed near its left edge and carried from the 150 % monitor far onto the 100 % one
    "move_by_left_edge": drag((300, 100, 600, 400), (10, 50), (2400, 60)),
    # grabbed near its right edge
    "move_by_right_edge": drag((300, 100, 600, 400), (590, 50), (2400, 60)),
    # and back: from the 100 % monitor to the 150 % one
    "move_back": drag((2400, 200, 600, 400), (300, 20), (-2000, 0)),
    # the resize corner pulled across the boundary
    "resize_across": drag((700, 100, 500, 400), (495, 395), (1500, 300)),
}
print(json.dumps(out))
