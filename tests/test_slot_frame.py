"""The frame that shows the Explorer window slot in 배치 편집."""

import json
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest

from versedesk.explorer_slot import MIN_HEIGHT, MIN_WIDTH
from versedesk.ui.slot_frame import WINDOW_TITLE, SlotFrame

HELPER = Path(__file__).resolve().parent / "helpers" / "slot_frame_two_screens.py"
TWO_SCREENS = {
    "synchronousWindowSystemEvents": True,
    "windowFrameMargins": False,
    "screens": [  # left: 1920x1080 at 150 %, right: 1920x1080 at 100 %
        {"name": "A150", "x": 0, "y": 0, "width": 1920, "height": 1080, "logicalDpi": 144, "logicalBaseDpi": 96, "dpr": 1.0},
        {"name": "B100", "x": 1920, "y": 0, "width": 1920, "height": 1080, "logicalDpi": 96, "logicalBaseDpi": 96, "dpr": 1.0},
    ],
}


def _frame(qapp, x=100, y=80, w=520, h=360):
    f = SlotFrame()
    f.setGeometry(x, y, w, h)
    f.show()
    qapp.processEvents()
    return f


def test_it_floats_on_top_stays_out_of_the_taskbar_and_never_takes_the_focus(qapp):
    f = SlotFrame()
    flags = f.windowFlags()
    assert flags & Qt.WindowType.Tool == Qt.WindowType.Tool  # no taskbar button, no Alt+Tab entry
    assert flags & Qt.WindowType.WindowStaysOnTopHint and flags & Qt.WindowType.FramelessWindowHint
    assert flags & Qt.WindowType.WindowDoesNotAcceptFocus  # a click on it does not steal the keyboard
    assert f.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert f.windowTitle() == WINDOW_TITLE
    assert (f.minimumWidth(), f.minimumHeight()) == (MIN_WIDTH, MIN_HEIGHT)
    f.deleteLater()


def test_dragging_moves_it_and_reports_the_new_place_once(qapp):
    f = _frame(qapp)
    got = []
    f.geometry_edited.connect(lambda *a: got.append(a))
    QTest.mousePress(f, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(60, 40))
    QTest.mouseMove(f, QPoint(100, 70))
    QTest.mouseMove(f, QPoint(150, 90))
    assert got == []  # nothing is saved while the mouse is still held
    QTest.mouseRelease(f, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(150, 90))
    assert len(got) == 1 and got[0][2:] == (520, 360)
    assert (f.x(), f.y()) == got[0][:2] and (f.x(), f.y()) != (100, 80)
    f.hide()
    f.deleteLater()


def test_a_click_without_moving_reports_nothing(qapp):
    f = _frame(qapp)
    got = []
    f.geometry_edited.connect(lambda *a: got.append(a))
    QTest.mouseClick(f, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(60, 40))
    QTest.mouseClick(f, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, QPoint(60, 40))
    assert got == []
    f.hide()
    f.deleteLater()


def test_it_cannot_be_dragged_off_its_screen(qapp):
    f = _frame(qapp, 100, 80, 520, 360)
    area = f.screen().availableGeometry().intersected(f.screen().geometry())
    QTest.mousePress(f, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(60, 40))
    for step in range(1, 30):
        QTest.mouseMove(f, QPoint(60 - 40 * step, 40 - 40 * step))  # far past the top-left corner
    QTest.mouseRelease(f, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(60, 40))
    assert area.contains(f.geometry()) and (f.width(), f.height()) == (520, 360)
    f.hide()
    f.deleteLater()


def test_the_corner_resizes_within_the_minimum_and_the_screen(qapp):
    f = _frame(qapp, 40, 40, 520, 360)
    got = []
    f.geometry_edited.connect(lambda *a: got.append(a))
    grip = f.grip_rect().center()
    QTest.mousePress(f, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, grip)
    QTest.mouseMove(f, grip + QPoint(60, 40))
    QTest.mouseRelease(f, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, grip + QPoint(60, 40))
    assert got[-1] == (40, 40, 580, 400)
    grip = f.grip_rect().center()
    QTest.mousePress(f, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, grip)
    QTest.mouseMove(f, grip - QPoint(900, 900))  # smaller than allowed
    QTest.mouseRelease(f, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, grip - QPoint(900, 900))
    assert got[-1] == (40, 40, MIN_WIDTH, MIN_HEIGHT)
    grip = f.grip_rect().center()
    area = f.screen().availableGeometry().intersected(f.screen().geometry())
    QTest.mousePress(f, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, grip)
    QTest.mouseMove(f, grip + QPoint(5000, 5000))  # larger than the screen
    QTest.mouseRelease(f, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, grip + QPoint(5000, 5000))
    assert area.contains(f.geometry())
    f.hide()
    f.deleteLater()


def test_the_whole_frame_can_be_grabbed_also_at_fractional_scaling(qapp):
    """A fully transparent pixel would let the click fall through to whatever is behind."""
    for dpr in (1.0, 1.25, 1.5, 1.75):
        f = SlotFrame()
        f.setGeometry(0, 0, 481, 321)
        img = QImage(int(481 * dpr + 0.5), int(321 * dpr + 0.5), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        img.setDevicePixelRatio(dpr)
        f.render(img)
        low = min(img.pixelColor(x, y).alpha() for x in range(0, img.width(), 3) for y in range(img.height()))
        edge = min(img.pixelColor(img.width() - 1, y).alpha() for y in range(img.height()))
        assert low > 0 and edge > 0, (dpr, low, edge)
        f.deleteLater()


def test_across_two_monitors_with_different_scaling_the_size_never_changes(tmp_path):
    """The user's set-up. Qt's logical coordinates have a gap between a 150 % monitor and its
    neighbour, and a window straddling both changes its logical size: without care the frame
    flickers between the monitors and a size nobody chose gets saved."""
    (tmp_path / "screens.json").write_text(json.dumps(TWO_SCREENS), encoding="utf-8")
    # a relative file name: Qt splits the platform arguments at ':' (a Windows drive letter would break it)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen:configfile=screens.json", PYTHONDONTWRITEBYTECODE="1")
    run = subprocess.run([sys.executable, str(HELPER)], capture_output=True, text=True, env=env, timeout=120,
                         cwd=str(tmp_path))
    assert run.returncode == 0, run.stderr[-2000:]
    out = json.loads(run.stdout.strip().splitlines()[-1])
    assert [s[5] for s in out["screens"]] == [1.5, 1.0], out["screens"]  # the fake monitors are as intended
    for case in ("move_by_left_edge", "move_by_right_edge", "move_back"):
        r = out[case]
        assert r["sizes"] == [[600, 400]], (case, r)  # the same size at every step...
        assert r["saved"] and r["saved"][-1][2:] == [600, 400], (case, r)  # ...and saved
        assert r["steps_not_on_one_screen"] == 0 and r["screen_changes"] == 1, (case, r)
    assert out["move_by_left_edge"]["final_screen"] == "B100" and out["move_back"]["final_screen"] == "A150"
    r = out["resize_across"]  # the corner pulled onto the other monitor: it stops at its own monitor's edge
    assert r["steps_not_on_one_screen"] == 0 and r["screen_changes"] == 0, r
    x, y, w, h = r["saved"][-1]
    assert (x, y) == (700, 100) and x + w <= 1280 and y + h <= 720, r
