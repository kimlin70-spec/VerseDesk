"""트레이 → 말씀 목록 편집: the verse list in one small window.

Type a reference ("요 3:16", "시 23:1-3", "John 3:16") and press Enter or 추가: the text is
filled in from the BSB text built into the program (no typing, no typos, works offline).
▲/▼ (or dragging) changes the order, 삭제 removes, and the dropdown sets how often the next
verse comes up.  Every change is saved at once, so there is no save button.

It is a normal window (taskbar, Alt+Tab) created without a parent, like the dialogs (see
ui/dialogs.py).  The Bible text is loaded on the first lookup and freed with the window.
"""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QItemSelectionModel, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QFont, QGuiApplication, QIcon, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from versedesk.bible import Bible, BibleUnavailable, ReferenceProblem, parse_reference, split_references
from versedesk.rotation import INTERVAL_CHOICES, interval_label
from versedesk.verses import MAX_VERSES, Verse

log = logging.getLogger("versedesk.ui.verse_editor")

TITLE = "VerseDesk 말씀 목록"
PLACEHOLDER = "예) 요 3:16, 시 23:1-3, John 3:16"
HELP = "구절 주소를 적고 Enter를 누르면 영어 본문이 자동으로 들어갑니다. 여러 개는 쉼표(,)로 나눠 적으세요."
PREVIEW_HINT = "목록에서 구절을 고르면 여기에 전체 본문이 보입니다."
DEFAULT_SIZE = (640, 560)
# text colours for a light window, and for Windows' dark app mode (readable on both)
LIGHT_COLORS = {"ok": "#1E7B34", "error": "#B3261E", "hint": "#5F6368"}
DARK_COLORS = {"ok": "#81C995", "error": "#F28B82", "hint": "#BDC1C6"}


class _VerseTree(QTreeWidget):
    """Two columns (구절 | 본문); rows can be dragged into a new order, never nested."""

    reordered = Signal()

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt name)
        moving = sorted(self.selectedItems(), key=self.indexOfTopLevelItem)
        super().dropEvent(event)
        if not event.isAccepted() or not moving:
            return
        self.keep_order(moving)
        QTimer.singleShot(0, lambda: self._reselect(moving))  # Qt clears the selection after a drop
        self.reordered.emit()

    def keep_order(self, moving: list[QTreeWidgetItem]) -> None:
        """Qt drops a block of rows in the order they were clicked (and sometimes reversed);
        put them back in their list order, where they landed."""
        rows = [self.indexOfTopLevelItem(i) for i in moving]
        if not rows or min(rows) < 0:
            return
        start = min(rows)
        for item in moving:
            self.takeTopLevelItem(self.indexOfTopLevelItem(item))
        for k, item in enumerate(moving):
            self.insertTopLevelItem(start + k, item)

    def _reselect(self, items: list[QTreeWidgetItem]) -> None:
        try:
            self.clearSelection()
            for item in items:
                if self.indexOfTopLevelItem(item) >= 0:
                    item.setSelected(True)
        except RuntimeError:  # the window was closed in the meantime
            pass


class VerseEditor(QWidget):
    list_changed = Signal(list)  # list[Verse], in order: save and show it
    interval_changed = Signal(int)  # minutes
    closed = Signal()  # the window is gone (it deletes itself right after)

    def __init__(
        self,
        verses: list[Verse],
        interval_minutes: int,
        *,
        using_builtin: bool = False,
        note: str | None = None,
        load_bible: Callable[[], Bible] | None = None,
        icon: QIcon | None = None,
    ):
        super().__init__(None, Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(TITLE)
        if icon is not None:
            self.setWindowIcon(icon)
        self._load_bible = load_bible
        self._bible: Bible | None = None

        self.input = QLineEdit()
        self.input.setPlaceholderText(PLACEHOLDER)
        self.input.setClearButtonEnabled(True)
        self.add_button = QPushButton("추가")
        self.message = QLabel()
        self.message.setWordWrap(True)

        self.tree = _VerseTree()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["구절", "본문"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.tree.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        header = self.tree.header()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionsMovable(False)

        self.up_button = QPushButton("▲ 위로")
        self.down_button = QPushButton("▼ 아래로")
        self.delete_button = QPushButton("삭제")
        for b in (self.up_button, self.down_button, self.delete_button):
            # a click must leave the keyboard in the list: a focused button that gets disabled
            # (top/bottom reached) would hand the focus to the interval dropdown, where the
            # arrow keys would silently change the interval
            b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.preview.setMinimumHeight(72)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.preview.setFont(QFont("Georgia", 11))

        self.interval = QComboBox()
        choices = list(INTERVAL_CHOICES)
        if interval_minutes not in choices:
            choices.append(interval_minutes)
        for minutes in sorted(choices):
            self.interval.addItem(interval_label(minutes), minutes)
        self.interval.setCurrentIndex(self.interval.findData(interval_minutes))
        self.count_label = QLabel()
        self.close_button = QPushButton("닫기")

        top = QHBoxLayout()
        top.addWidget(QLabel("구절 주소"))
        top.addWidget(self.input, 1)
        top.addWidget(self.add_button)
        side = QVBoxLayout()
        for b in (self.up_button, self.down_button, self.delete_button):
            side.addWidget(b)
        side.addStretch(1)
        middle = QHBoxLayout()
        middle.addWidget(self.tree, 1)
        middle.addLayout(side)
        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("바뀌는 간격"))
        bottom.addWidget(self.interval)
        bottom.addStretch(1)
        bottom.addWidget(self.count_label)
        bottom.addSpacing(12)
        bottom.addWidget(self.close_button)
        root = QVBoxLayout(self)
        root.addLayout(top)
        root.addWidget(self.message)
        root.addLayout(middle, 1)
        root.addWidget(self.preview)
        root.addLayout(bottom)
        self._fit_to_screen()

        self.input.returnPressed.connect(self.add_from_input)
        self.add_button.clicked.connect(self.add_from_input)
        self.up_button.clicked.connect(lambda: self.move_selected(-1))
        self.down_button.clicked.connect(lambda: self.move_selected(1))
        self.delete_button.clicked.connect(self.delete_selected)
        self.close_button.clicked.connect(self.close)
        self.tree.itemSelectionChanged.connect(self._update_selection)
        self.tree.reordered.connect(self._changed)
        self.interval.currentIndexChanged.connect(self._on_interval)
        for keys, slot, widget in (
            (QKeySequence(QKeySequence.StandardKey.Delete), self.delete_selected, self.tree),
            (QKeySequence("Ctrl+Up"), lambda: self.move_selected(-1), self.tree),
            (QKeySequence("Ctrl+Down"), lambda: self.move_selected(1), self.tree),
            (QKeySequence("Escape"), self.close, self),
        ):
            sc = QShortcut(keys, widget)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)

        self.set_list(verses, using_builtin, note)

    def _fit_to_screen(self) -> None:
        """Open on the screen with the mouse (where the tray menu was), small enough to fit
        above the taskbar at 125-175% scaling on a small screen."""
        width, height = DEFAULT_SIZE
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen is not None:
            self.setScreen(screen)
            area = screen.availableGeometry()
            width, height = min(width, area.width() - 40), min(height, area.height() - 100)
        self.resize(max(width, 360), max(height, 300))

    # ------------------------------------------------------------------ list

    def verses(self) -> list[Verse]:
        return [self.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) for i in range(self.tree.topLevelItemCount())]

    def set_list(self, verses: list[Verse], using_builtin: bool = False, note: str | None = None) -> None:
        """Show ``verses`` (e.g. after the file was edited outside); keeps the selection."""
        selected = {v.key() for v in self._selected_verses()}
        self.tree.clear()
        for v in verses:
            self.tree.addTopLevelItem(self._item(v))
        self.tree.resizeColumnToContents(0)
        if self.tree.columnWidth(0) > 220:
            self.tree.setColumnWidth(0, 220)
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            item.setSelected(item.data(0, Qt.ItemDataRole.UserRole).key() in selected)
        self._update_count()
        self._update_selection()
        if note:
            self._say(note, "error")
        elif using_builtin:
            self._say(f"기본 말씀 {len(verses)}개입니다. 고치면 내 목록으로 저장됩니다. " + HELP, "hint")
        else:
            self._say(HELP, "hint")

    @staticmethod
    def _item(v: Verse) -> QTreeWidgetItem:
        item = QTreeWidgetItem([v.reference or "(출처 없음)", v.text])
        item.setData(0, Qt.ItemDataRole.UserRole, v)
        item.setToolTip(0, v.reference)
        # rows can be dragged between other rows but never dropped *onto* one (no nesting)
        item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsDragEnabled)
        return item

    def _selected_rows(self) -> list[int]:
        return sorted(self.tree.indexOfTopLevelItem(i) for i in self.tree.selectedItems())

    def _selected_verses(self) -> list[Verse]:
        return [self.tree.topLevelItem(r).data(0, Qt.ItemDataRole.UserRole) for r in self._selected_rows()]

    def _select_rows(self, rows: list[int]) -> None:
        self.tree.clearSelection()
        for r in rows:
            item = self.tree.topLevelItem(r)
            if item is not None:
                item.setSelected(True)
        if rows:
            first = self.tree.topLevelItem(rows[0])
            if first is not None:
                self.tree.setCurrentItem(first, 0, QItemSelectionModel.SelectionFlag.NoUpdate)
                self.tree.scrollToItem(first)

    def _changed(self) -> None:
        self._update_count()
        self._update_selection()
        self.list_changed.emit(self.verses())

    def _color(self, kind: str) -> str:
        dark = self.palette().color(QPalette.ColorRole.Window).lightness() < 128
        return (DARK_COLORS if dark else LIGHT_COLORS)[kind]

    def _update_count(self) -> None:
        n = self.tree.topLevelItemCount()
        self.count_label.setText(f"{n}개 · 자동 저장" if n else "비어 있음 · 바탕화면에는 기본 말씀이 나옵니다")
        self.count_label.setStyleSheet(f"color: {self._color('hint')}")

    def _update_selection(self) -> None:
        verses = self._selected_verses()
        self.delete_button.setEnabled(bool(verses))
        self.up_button.setEnabled(bool(verses) and self._selected_rows() != list(range(len(verses))))
        n = self.tree.topLevelItemCount()
        self.down_button.setEnabled(bool(verses) and self._selected_rows() != list(range(n - len(verses), n)))
        if len(verses) == 1:
            v = verses[0]
            self.preview.setText(f"{v.text}\n— {v.reference}" if v.reference else v.text)
            self.preview.setStyleSheet("")
        elif verses:
            self.preview.setText(f"{len(verses)}개를 골랐습니다.")
            self.preview.setStyleSheet(f"color: {self._color('hint')}")
        else:
            self.preview.setText(PREVIEW_HINT)
            self.preview.setStyleSheet(f"color: {self._color('hint')}")

    def _say(self, text: str, kind: str) -> None:
        self.message.setText(text)
        self.message.setStyleSheet(f"color: {self._color(kind)}")

    # ------------------------------------------------------------------ actions

    def _bible_or_none(self) -> Bible | None:
        if self._bible is None:
            try:
                self._bible = (self._load_bible or Bible.load)()
            except (BibleUnavailable, OSError, ValueError) as e:
                log.error("cannot load the built-in Bible: %s", e)
                self._say("내장 성경 본문을 읽지 못했습니다. log.txt를 확인해 주세요.", "error")
                return None
        return self._bible

    def add_from_input(self) -> None:
        refs = split_references(self.input.text())
        if not refs:
            self._say("구절 주소를 적어 주세요. " + PLACEHOLDER, "error")
            self.input.setFocus()
            return
        bible = self._bible_or_none()
        if bible is None:
            return
        keys = {v.key(): i for i, v in enumerate(self.verses())}
        added: list[Verse] = []
        notes: list[str] = []
        failed: list[str] = []
        problems: list[str] = []
        duplicate_rows: list[int] = []
        for typed in refs:
            try:
                ref = parse_reference(typed)
                verse = bible.passage(ref)
            except ReferenceProblem as e:
                failed.append(typed)
                problems.append(f"'{typed}': {e}")
                continue
            if verse.key() in keys:
                duplicate_rows.append(keys[verse.key()])
                problems.append(f"이미 목록에 있습니다: {verse.reference}")
                continue
            if len(keys) >= MAX_VERSES:
                failed.append(typed)
                problems.append(f"목록에는 {MAX_VERSES}개까지 넣을 수 있습니다.")
                continue
            keys[verse.key()] = len(keys)
            added.append(verse)
            if ref.note:  # Korean numbering differs from the BSB here (e.g. 고후 13:13 = 13:14)
                notes.append(f"{verse.reference} = {ref.note}")
            self.tree.addTopLevelItem(self._item(verse))
        self.input.setText(", ".join(failed))
        self.input.setFocus()
        if added:
            n = self.tree.topLevelItemCount()
            self._select_rows(list(range(n - len(added), n)))
            self._changed()
        elif duplicate_rows:
            self._select_rows(sorted(set(duplicate_rows)))
        extra = f" ({'; '.join(notes)})" if notes else ""
        if added and not problems:
            what = added[0].reference if len(added) == 1 else f"{len(added)}개"
            self._say(f"추가했습니다: {what}{extra}", "ok")
        elif added:
            self._say(f"{len(added)}개를 추가했습니다{extra}. " + " / ".join(problems), "error")
        else:
            self._say(" / ".join(problems), "error")

    def _rebuild(self, items: list[QTreeWidgetItem]) -> None:
        """Replace the rows without a flurry of selection changes in between, and without
        the list jumping back to the top (emptying it resets the scroll bar)."""
        bar = self.tree.verticalScrollBar()
        scrolled = bar.value()
        was = self.tree.blockSignals(True)
        try:
            while self.tree.topLevelItemCount():
                self.tree.takeTopLevelItem(0)
            for item in items:
                self.tree.addTopLevelItem(item)
        finally:
            self.tree.blockSignals(was)
        self.tree.doItemsLayout()  # the scroll range is back before the old position is set
        bar.setValue(scrolled)

    def delete_selected(self) -> None:
        rows = self._selected_rows()
        if not rows:
            return
        gone = set(rows)
        keep = [self.tree.topLevelItem(r) for r in range(self.tree.topLevelItemCount()) if r not in gone]
        self._rebuild(keep)
        if keep:
            self._select_rows([min(rows[0], len(keep) - 1)])
        self._say(f"{len(rows)}개를 목록에서 뺐습니다.", "hint")
        self._changed()
        self.tree.setFocus()

    def move_selected(self, step: int) -> None:
        """Move the selected rows one place up (-1) or down (+1); a block moves together."""
        rows = self._selected_rows()
        n = self.tree.topLevelItemCount()
        if not rows or (step < 0 and rows[0] == 0) or (step > 0 and rows[-1] == n - 1):
            return
        order = list(range(n))
        for r in (rows if step < 0 else reversed(rows)):
            order[r], order[r + step] = order[r + step], order[r]
        items = [self.tree.topLevelItem(i) for i in range(n)]
        self._rebuild([items[i] for i in order])
        self._select_rows([r + step for r in rows])
        self._changed()
        self.tree.setFocus()

    def _on_interval(self, _index: int) -> None:
        minutes = self.interval.currentData()
        if isinstance(minutes, int):
            self.interval_changed.emit(minutes)

    def show_interval(self, minutes: int) -> None:
        """Show ``minutes`` (settings.json was changed outside) without reporting it back."""
        was = self.interval.blockSignals(True)
        try:
            index = self.interval.findData(minutes)
            if index < 0:
                self.interval.addItem(interval_label(minutes), minutes)
                index = self.interval.count() - 1
            self.interval.setCurrentIndex(index)
        finally:
            self.interval.blockSignals(was)

    # ------------------------------------------------------------------ window

    def set_save_result(self, ok: bool) -> None:
        if ok:
            self._update_count()
        else:
            self.count_label.setText("저장하지 못했습니다 (log.txt 참고)")
            self.count_label.setStyleSheet(f"color: {self._color('error')}")

    def present(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt name)
        self._bible = None  # ~15 MB of text; the window is deleted right after
        super().closeEvent(event)
        if event.isAccepted():
            self.closed.emit()
