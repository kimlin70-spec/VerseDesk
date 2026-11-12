"""The verse list editor window (트레이 → 말씀 목록 편집)."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView

from versedesk.bible import Bible
from versedesk.ui.verse_editor import VerseEditor
from versedesk.verses import Verse


def _bible():
    return Bible(
        {"John 3:16": "For God so loved the world.", "John 3:17": "For God did not send His Son.",
         "Psalm 23:1": "A Psalm of David. The LORD is my shepherd.", "Romans 8:28": "All things work together.",
         "Matthew 17:21": ""},
        {23: "A Psalm of David."},
    )


def _list(n=3):
    return [Verse(f"Book {i}:1 (BSB)", f"Text {i}.", "user") for i in range(1, n + 1)]


@pytest.fixture
def editor(qapp):
    ed = VerseEditor(_list(), 120, load_bible=_bible)
    saved, intervals = [], []
    ed.list_changed.connect(saved.append)
    ed.interval_changed.connect(intervals.append)
    ed.saved, ed.intervals = saved, intervals
    ed.show()
    yield ed
    ed.close()


def refs(ed):
    return [v.reference for v in ed.verses()]


def test_typing_a_reference_and_enter_adds_it_and_saves(editor):
    editor.input.setText("요 3:16")  # QTest can only type ASCII; Korean comes from the IME on a real PC
    QTest.keyClicks(editor.input, "-17")
    QTest.keyClick(editor.input, Qt.Key.Key_Return)
    assert refs(editor)[-1] == "John 3:16–17 (BSB)"
    assert editor.saved[-1][-1].text == "For God so loved the world. For God did not send His Son."
    assert editor.input.text() == "" and "추가했습니다" in editor.message.text()
    assert editor.tree.selectedItems()[0].text(0) == "John 3:16–17 (BSB)"  # the new row is selected
    assert "For God so loved" in editor.preview.text()


def test_several_at_once_and_problems_stay_in_the_box(editor):
    editor.input.setText("시 23:1, 요 99:1, 롬 8:28")
    editor.add_button.click()
    assert refs(editor)[-2:] == ["Psalm 23:1 (BSB)", "Romans 8:28 (BSB)"]
    assert editor.verses()[-2].text == "The LORD is my shepherd."
    assert editor.input.text() == "요 99:1"  # to fix and try again
    assert "21장까지" in editor.message.text() or "까지 있습니다" in editor.message.text()
    assert len(editor.saved) == 1


def test_duplicates_are_not_added_twice(editor):
    editor.input.setText("요 3:16")
    editor.add_from_input()
    editor.input.setText("John 3:16")
    editor.add_from_input()
    assert refs(editor).count("John 3:16 (BSB)") == 1
    assert "이미 목록에 있습니다" in editor.message.text()
    assert len(editor.saved) == 1


def test_unknown_or_missing_verses_change_nothing(editor):
    for typed in ("", "요 3", "Hezekiah 1:1", "마 17:21"):
        editor.input.setText(typed)
        editor.add_from_input()
    assert refs(editor) == [v.reference for v in _list()] and editor.saved == []


def test_move_up_down_and_delete(editor):
    editor._select_rows([2])
    editor.up_button.click()
    assert refs(editor) == ["Book 1:1 (BSB)", "Book 3:1 (BSB)", "Book 2:1 (BSB)"]
    editor.up_button.click()
    assert refs(editor)[0] == "Book 3:1 (BSB)"
    assert not editor.up_button.isEnabled()  # already at the top
    editor.down_button.click()
    assert refs(editor) == ["Book 1:1 (BSB)", "Book 3:1 (BSB)", "Book 2:1 (BSB)"]
    editor.delete_button.click()
    assert refs(editor) == ["Book 1:1 (BSB)", "Book 2:1 (BSB)"]
    assert len(editor.saved) == 4 and [v.reference for v in editor.saved[-1]] == refs(editor)
    assert editor.tree.selectedItems()  # the next row is selected, so 삭제 can be pressed again


def test_a_block_of_rows_moves_together_and_keyboard_shortcuts(editor):
    editor.activateWindow()
    assert QTest.qWaitForWindowActive(editor)
    editor.tree.setFocus()
    editor._select_rows([1, 2])
    QTest.keyClick(editor.tree, Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier)
    assert refs(editor) == ["Book 2:1 (BSB)", "Book 3:1 (BSB)", "Book 1:1 (BSB)"]
    QTest.keyClick(editor.tree, Qt.Key.Key_Delete)
    assert refs(editor) == ["Book 1:1 (BSB)"]


def test_an_empty_list_says_what_the_desktop_shows(editor):
    editor.tree.selectAll()
    editor.delete_selected()
    assert editor.verses() == [] and editor.saved[-1] == []
    assert "기본 말씀" in editor.count_label.text()


def test_interval_choice(qapp):
    ed = VerseEditor(_list(), 90, load_bible=_bible)  # a value set by hand in settings.json is kept
    got = []
    ed.interval_changed.connect(got.append)
    assert ed.interval.currentData() == 90 and ed.interval.currentText() == "1시간 30분마다"
    labels = [ed.interval.itemText(i) for i in range(ed.interval.count())]
    assert labels[0] == "30분마다" and labels[-1] == "하루에 한 번"
    ed.interval.setCurrentIndex(ed.interval.findData(1440))
    assert got == [1440]
    ed.close()


def test_drag_reordering_is_reported(editor):
    order = list(reversed(editor.verses()))
    items = [editor.tree.takeTopLevelItem(0) for _ in range(3)]
    for it in reversed(items):  # what a drag & drop leaves behind
        editor.tree.addTopLevelItem(it)
    editor.tree.reordered.emit()
    assert editor.saved[-1] == order


def test_rows_cannot_be_dropped_onto_each_other(editor):
    item = editor.tree.topLevelItem(0)
    assert not item.flags() & Qt.ItemFlag.ItemIsDropEnabled
    assert item.flags() & Qt.ItemFlag.ItemIsDragEnabled


def test_a_broken_bible_file_is_explained(qapp):
    from versedesk.bible import BibleUnavailable

    def broken():
        raise BibleUnavailable("damaged")

    ed = VerseEditor(_list(), 120, load_bible=broken)
    ed.input.setText("요 3:16")
    ed.add_from_input()
    assert "읽지 못했습니다" in ed.message.text() and len(ed.verses()) == 3
    ed.close()


def test_closing_frees_the_bible_and_reports_it(qapp):
    ed = VerseEditor(_list(), 120, load_bible=_bible, using_builtin=True)
    assert "기본 말씀 3개" in ed.message.text()
    closed = []
    ed.closed.connect(lambda: closed.append(True))
    ed.input.setText("요 3:16")
    ed.add_from_input()
    assert ed._bible is not None
    ed.show()
    ed.close()
    assert closed == [True] and ed._bible is None


def test_set_list_keeps_the_selection(editor):
    editor._select_rows([1])
    editor.set_list(list(reversed(_list())))
    assert [i.text(0) for i in editor.tree.selectedItems()] == ["Book 2:1 (BSB)"]


def test_clicking_the_buttons_leaves_the_keyboard_in_the_list(editor, qapp):
    """A focused button that gets disabled would pass the focus to the interval dropdown,
    where ↑/↓ would silently change (and save) the interval."""
    from PySide6.QtWidgets import QApplication

    editor.activateWindow()
    assert QTest.qWaitForWindowActive(editor)
    editor.tree.setFocus()
    editor._select_rows([1])
    for button in (editor.down_button, editor.up_button, editor.up_button, editor.delete_button):
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        assert QApplication.focusWidget() is editor.tree, button.text()
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Down)
    assert editor.intervals == []  # the arrow key moved in the list, not the interval


def test_a_dropped_block_keeps_its_list_order(editor):
    """Qt puts dragged rows down in click order (or reversed): they are put back in list order."""
    items = [editor.tree.topLevelItem(i) for i in range(3)]
    moving = [items[1], items[2]]
    # what Qt can leave behind when the block is dropped back onto its own place: reversed
    for it in moving:
        editor.tree.takeTopLevelItem(editor.tree.indexOfTopLevelItem(it))
    editor.tree.insertTopLevelItem(1, items[2])
    editor.tree.insertTopLevelItem(2, items[1])
    editor.tree.keep_order(moving)
    assert refs(editor) == ["Book 1:1 (BSB)", "Book 2:1 (BSB)", "Book 3:1 (BSB)"]


def test_showing_an_interval_from_settings_does_not_send_it_back(editor):
    editor.show_interval(30)
    editor.show_interval(45)  # a value set by hand that is not in the list
    assert editor.interval.currentData() == 45 and editor.intervals == []
    editor.interval.setCurrentIndex(editor.interval.findData(120))
    assert editor.intervals == [120]  # a real choice is still reported


def test_korean_numbering_is_explained_when_it_differs(qapp):
    bible = Bible({"2 Corinthians 13:12": "Greet one another.", "2 Corinthians 13:13": "All the saints.",
                   "2 Corinthians 13:14": "The grace of the Lord Jesus Christ."})
    ed = VerseEditor([], 120, load_bible=lambda: bible)
    ed.input.setText("고후 13:13")
    ed.add_from_input()
    assert refs(ed) == ["2 Corinthians 13:14 (BSB)"]
    assert "한글 성경 고후 13:13" in ed.message.text()
    ed.close()


def test_a_note_about_an_unusable_file_is_shown(qapp):
    ed = VerseEditor(_list(), 120, using_builtin=True, note="지금 verses.json을 쓸 수 없어 기본 말씀을 보여 줍니다.",
                     load_bible=_bible)
    assert "쓸 수 없어" in ed.message.text()
    ed.close()


def test_the_comma_rule_is_shown_from_the_first_use(qapp):
    ed = VerseEditor(_list(), 120, using_builtin=True, load_bible=_bible)
    assert "쉼표" in ed.message.text() and "," in ed.input.placeholderText()
    ed.close()


def test_the_window_fits_a_small_screen(qapp):
    ed = VerseEditor(_list(), 120, load_bible=_bible)
    area = ed.screen().availableGeometry()
    assert ed.width() <= max(360, area.width() - 40) and ed.height() <= max(300, area.height() - 100)
    ed.close()


def test_deleting_or_moving_does_not_make_a_scrolled_list_jump(qapp):
    ed = VerseEditor(_list(60), 120, load_bible=_bible)
    ed.resize(640, 420)
    ed.show()
    qapp.processEvents()
    bar = ed.tree.verticalScrollBar()
    ed.tree.scrollToItem(ed.tree.topLevelItem(19), QAbstractItemView.ScrollHint.PositionAtTop)
    qapp.processEvents()
    top = bar.value()
    assert top > 0
    ed._select_rows([20])
    ed.delete_selected()
    qapp.processEvents()
    assert bar.value() == top
    ed.move_selected(-1)
    qapp.processEvents()
    assert bar.value() == top
    ed.close()
