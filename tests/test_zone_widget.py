"""The zone window: drops are links only, every pixel takes the mouse, layout and collapse."""

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtTest import QTest

from versedesk.ui.zone_widget import (
    CELL_W,
    TITLE_H,
    ZoneWidget,
    item_views,
    link_is_possible,
    local_paths_from_mime,
)

ALL = Qt.DropAction.CopyAction | Qt.DropAction.MoveAction | Qt.DropAction.LinkAction
NO_LINK = Qt.DropAction.CopyAction | Qt.DropAction.MoveAction


def _mime(*paths):
    m = QMimeData()
    m.setUrls([QUrl.fromLocalFile(p) for p in paths])
    return m


def _zone(qapp, n_items=5, width=340, height=260, collapsed=False):
    w = ZoneWidget("z1")
    w.set_zone("업무", item_views([f"C:\\Work\\file{i}.txt" for i in range(n_items)]), collapsed, width, height)
    return w


def test_drag_from_explorer_is_accepted_as_a_link(qapp):
    w = _zone(qapp)
    mime = _mime("C:/Users/Kim/보고서", "C:/Users/Kim/plan.xlsx")
    # Explorer offers Copy|Move|Link and proposes Move for the same drive
    enter = QDragEnterEvent(QPoint(50, 80), ALL, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    enter.setDropAction(Qt.DropAction.MoveAction)
    w.dragEnterEvent(enter)
    assert enter.isAccepted() and enter.dropAction() == Qt.DropAction.LinkAction

    move = QDragMoveEvent(QPoint(60, 90), ALL, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier)
    move.setDropAction(Qt.DropAction.MoveAction)
    w.dragMoveEvent(move)
    assert move.isAccepted() and move.dropAction() == Qt.DropAction.LinkAction

    got = []
    w.paths_dropped.connect(got.append)
    drop = QDropEvent(QPointF(60, 90), ALL, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier)
    drop.setDropAction(Qt.DropAction.CopyAction)
    w.dropEvent(drop)
    assert drop.isAccepted() and drop.dropAction() == Qt.DropAction.LinkAction
    assert got == [["C:\\Users\\Kim\\보고서", "C:\\Users\\Kim\\plan.xlsx"]]
    w.deleteLater()


def test_a_source_that_cannot_link_is_refused(qapp):
    w = _zone(qapp)
    mime = _mime("C:/a.txt")
    enter = QDragEnterEvent(QPoint(5, 5), NO_LINK, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    w.dragEnterEvent(enter)
    assert not enter.isAccepted()
    got = []
    w.paths_dropped.connect(got.append)
    drop = QDropEvent(QPointF(5, 5), NO_LINK, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    w.dropEvent(drop)
    assert not drop.isAccepted() and got == []
    w.deleteLater()


def test_non_file_drags_are_refused(qapp):
    w = _zone(qapp)
    m = QMimeData()
    m.setText("just text")
    enter = QDragEnterEvent(QPoint(5, 5), ALL, m, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    w.dragEnterEvent(enter)
    assert not enter.isAccepted()
    web = QMimeData()
    web.setUrls([QUrl("https://example.com/a.txt")])
    assert local_paths_from_mime(web) == []
    assert link_is_possible(ALL) and not link_is_possible(NO_LINK)
    w.deleteLater()


def test_every_pixel_catches_the_mouse_and_drops(qapp):
    """Fully transparent pixels would let clicks and drops fall through to the desktop."""
    for collapsed in (False, True):
        w = _zone(qapp, collapsed=collapsed)
        img = w.grab().toImage()
        alphas = {img.pixelColor(x, y).alpha() for x in range(img.width()) for y in range(img.height())}
        assert min(alphas) >= 2, (collapsed, min(alphas))
        w.deleteLater()
    empty = _zone(qapp, n_items=0)
    img = empty.grab().toImage()
    assert min(img.pixelColor(x, y).alpha() for x in range(img.width()) for y in range(img.height())) >= 2
    empty.deleteLater()


def test_collapse_shows_only_the_title_bar_and_expands_back(qapp):
    w = _zone(qapp, height=300)
    assert w.height() == 300
    w.set_collapsed(True)
    assert w.height() == TITLE_H and w.collapsed
    w.set_collapsed(False)
    assert w.height() == 300
    w.deleteLater()


def test_collapse_button_click_reports_the_new_state(qapp):
    w = _zone(qapp)
    w.show()
    got = []
    w.collapse_toggled.connect(got.append)
    QTest.mouseClick(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, w.collapse_button_rect().center())
    assert got == [True]
    w.deleteLater()


def test_grid_layout_and_hit_testing(qapp):
    w = _zone(qapp, n_items=7, width=2 * CELL_W + 16 + 10)
    assert w.item_at(w.cell_rect(0).center()) == 0
    assert w.item_at(w.cell_rect(6).center()) == 6
    assert w.cell_rect(1).top() == w.cell_rect(0).top()  # two columns
    assert w.cell_rect(2).top() > w.cell_rect(0).top()
    assert w.item_at(QPoint(5, 5)) == -1  # title bar
    w.set_collapsed(True)
    assert w.item_at(QPoint(20, 20)) == -1
    w.deleteLater()


def test_double_click_opens_and_moving_needs_edit_mode(qapp):
    w = _zone(qapp)
    w.show()
    opened, edited = [], []
    w.open_requested.connect(opened.append)
    w.geometry_edited.connect(lambda *a: edited.append(a))
    QTest.mouseDClick(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, w.cell_rect(1).center())
    assert opened == ["C:\\Work\\file1.txt"]
    start = w.pos()
    QTest.mousePress(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(100, 10))
    QTest.mouseMove(w, QPoint(140, 40))
    QTest.mouseRelease(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(140, 40))
    assert w.pos() == start and edited == []  # not in edit mode: the zone stays put
    w.deleteLater()


def test_missing_items_are_drawn_faded_without_crashing(qapp):
    w = _zone(qapp, n_items=2)
    w.set_item_state("C:\\Work\\file0.txt", False, False, None)
    w.set_item_state("C:\\Work\\file1.txt", True, False, None)
    assert [i.exists for i in w.items] == [False, True]
    w.grab()  # paints both states
    w.deleteLater()
