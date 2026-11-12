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
