from PySide6.QtGui import QFont, QFontMetricsF

from versedesk.ui.verse_widget import VerseAppearance, VerseWidget


def test_long_reference_wraps_and_window_grows(qapp):
    w = VerseWidget(VerseAppearance(width=200, font_size=12, reference_font_size=14))
    w.set_verse("Short text.", "1 Thessalonians 5:16–18 (BSB) and some more words")
    f = QFont("Georgia")
    f.setPointSizeF(14)
    one_line = QFontMetricsF(f, w).height()
    assert w._ref_rect.height() > one_line * 1.5
    assert w.height() >= w._ref_rect.bottom()
    w.deleteLater()


def test_edit_mode_and_appearance_changes_relayout(qapp):
    w = VerseWidget(VerseAppearance())
    w.set_verse("For God so loved the world.", "John 3:16 (BSB)")
    h = w.height()
    w.set_appearance(VerseAppearance(font_size=40))
    assert w.height() > h
    w.set_edit_mode(True)
    assert w.edit_mode
    w.set_appearance(VerseAppearance(font_size=40, shadow=False))
    w.deleteLater()


def test_a_click_outside_edit_mode_is_reported_as_stray(qapp):
    """Outside edit mode clicks should never reach the verse (they pass through to the
    desktop); if one does, the widget reports it so the app can log diagnostics."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    w = VerseWidget(VerseAppearance())
    w.set_verse("For God so loved the world.", "John 3:16 (BSB)")
    w.show()
    seen, moved = [], []
    w.stray_click.connect(lambda x, y: seen.append((x, y)))
    w.moved.connect(lambda x, y: moved.append((x, y)))
    QTest.mouseClick(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(10, 10))
    assert len(seen) == 1
    w.set_edit_mode(True)
    QTest.mouseClick(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(10, 10))
    assert len(seen) == 1 and len(moved) == 1  # in edit mode a click is a (zero-length) drag
    w.deleteLater()
