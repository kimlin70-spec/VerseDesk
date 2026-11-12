"""One folder zone on the desktop: a translucent box with a title bar and item icons.

  ┌──────────────────────────────────┐
  │ 업무 (3)                       ▾ │  title bar: name, item count, collapse button
  ├──────────────────────────────────┤
  │  [icon]   [icon]   [icon]        │  items: system icon + name (2 lines)
  │  보고서   계획.xlsx 사진          │  missing originals are drawn faded
  └──────────────────────────────────┘

Rules that matter (see CLAUDE.md):
  * Drops are accepted only as a LINK: the zone stores the path and Explorer leaves the
    original where it is.  ``acceptProposedAction()`` is never used, because the proposed
    action is usually Move.  A source that does not offer Link is refused.
  * Every pixel of the box is painted with alpha >= 2/255, so clicks and drops anywhere in
    the box reach the zone instead of falling through to the desktop behind it.
  * The window never activates; menus and dialogs are created without a parent (a parent
    would become the Windows owner and drag the zone above other windows).
  * Moving and resizing only in edit mode (배치 편집); opening, collapsing, dropping and the
    right-click menus always work.

The widget only reports what the user did (signals); ``ZoneManager`` changes the settings.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QToolTip

from versedesk.ui.desktop_widget import DesktopWidget
from versedesk.zones import MIN_HEIGHT, MIN_WIDTH, clean_path, display_name

log = logging.getLogger("versedesk.ui.zone")

TITLE_H = 30
PAD = 8
CELL_W = 84
CELL_H = 78
ICON = 32
GRIP = 16
RADIUS = 9

BOX_COLOR = QColor(16, 20, 28, 150)
TITLE_COLOR = QColor(16, 20, 28, 200)
FLOOR_COLOR = QColor(0, 0, 0, 2)  # the minimum everywhere: catches clicks and drops
HOVER_COLOR = QColor(255, 255, 255, 38)
DROP_COLOR = QColor(120, 180, 255, 70)
TEXT_COLOR = QColor(255, 255, 255)
MISSING_OPACITY = 0.38

TEXT_REMOVE_ITEM = "구역에서 빼기"
TEXT_RENAME = "이름 변경"
TEXT_DELETE_ZONE = "구역 삭제"
TIP_MISSING = "찾을 수 없음 (원래 자리에서 옮겨졌거나 삭제됨)"
TIP_COLLAPSE = "접기"
TIP_EXPAND = "펼치기"
EMPTY_HINT = "폴더나 파일을 여기로 끌어다 놓으세요\n(원본은 그대로, 바로가기처럼 등록됩니다)"


@dataclass
class ItemView:
    path: str
    name: str
    exists: bool | None = None  # None = not checked yet
    is_dir: bool = False
    pixmap: QPixmap | None = None


def local_paths_from_mime(mime) -> list[str]:
    """Windows paths of the files/folders being dragged (only real local paths)."""
    out: list[str] = []
    if mime is None or not mime.hasUrls():
        return out
    for url in mime.urls():
        if not url.isLocalFile():
            continue
        if url.host():
            # A share (\\server\\share\\...). Qt keeps a non-ASCII server name (e.g. a PC called
            # 김철수-PC) in its ACE form "xn--..." which Windows would not find: decode it.
            host = QUrl.fromAce(url.host(QUrl.ComponentFormattingOption.FullyEncoded).encode("ascii"),
                                QUrl.AceProcessingOption.IgnoreIDNWhitelist)
            local = "//" + host + url.path(QUrl.ComponentFormattingOption.FullyDecoded)
        else:
            local = url.toLocalFile()
        if len(local) >= 3 and local[0] == "/" and local[1].isalpha() and local[2] == ":":
            local = local[1:]  # "/C:/..." (how Qt spells a drive path off Windows) -> "C:/..."
        p = clean_path(local)
        if p:
            out.append(p)
    return out


def link_is_possible(actions) -> bool:
    return bool(actions & Qt.DropAction.LinkAction)


def _actions_text(actions) -> str:
    names = [n for n, a in (("copy", Qt.DropAction.CopyAction), ("move", Qt.DropAction.MoveAction),
                            ("link", Qt.DropAction.LinkAction)) if actions & a]
    return "+".join(names) or "none"


class ZoneWidget(DesktopWidget):
    open_requested = Signal(str)
    remove_requested = Signal(str)
    rename_requested = Signal()
    delete_requested = Signal()
    collapse_toggled = Signal(bool)  # the new collapsed state
    paths_dropped = Signal(list)  # list[str]
    geometry_edited = Signal(int, int, int, int)  # x, y, width, expanded height (logical px)
    pressed = Signal()  # any mouse press: the zone comes to the front of VerseDesk's widgets

    def __init__(self, zone_id: str, extra_flags=Qt.WindowType.Widget):
        super().__init__(extra_flags)
        self.zone_id = zone_id
        self.setObjectName(f"zone:{zone_id}")
        self.setWindowTitle(f"VerseDesk Zone {zone_id}")
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)
        self._name = ""
        self._items: list[ItemView] = []
        self._collapsed = False
        self._expanded_height = MIN_HEIGHT
        self._edit = False
        self._scroll = 0
        self._hover = -1
        self._drop_hover = False
        self._press: tuple[str, QPoint, QRect] | None = None  # (kind, global pos, start geometry)
        self._title_font = QFont()
        self._title_font.setPointSizeF(10)
        self._title_font.setBold(True)
        self._item_font = QFont()
        self._item_font.setPointSizeF(8.5)
        self._generic: dict[bool, QPixmap] = {}

    # ------------------------------------------------------------------ state from the manager

    def set_zone(self, name: str, items: list[ItemView], collapsed: bool, width: int, height: int) -> None:
        self._name = name
        self._items = list(items)
        self._collapsed = collapsed
        self._expanded_height = max(MIN_HEIGHT, height)
        self.setFixedSize(max(MIN_WIDTH, width), self._current_height())
        self._clamp_scroll()
        self._hover = -1
        self.update()

    def set_item_state(self, path: str, exists: bool, is_dir: bool, pixmap: QPixmap | None) -> None:
        for item in self._items:
            if item.path == path:
                item.exists, item.is_dir = exists, is_dir
                if pixmap is not None and not pixmap.isNull():
                    item.pixmap = pixmap
        self.update()

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self.setFixedSize(self.width(), self._current_height())
        self.update()

    def set_edit_mode(self, on: bool) -> None:
        self._edit = on
        self._press = None
        self.update()

    @property
    def collapsed(self) -> bool:
        return self._collapsed

    @property
    def items(self) -> list[ItemView]:
        return list(self._items)

    def _current_height(self) -> int:
        return TITLE_H if self._collapsed else self._expanded_height

    # ------------------------------------------------------------------ geometry helpers

    def collapse_button_rect(self) -> QRect:
        return QRect(self.width() - TITLE_H, 0, TITLE_H, TITLE_H)

    def grip_rect(self) -> QRect:
        return QRect(self.width() - GRIP, self.height() - GRIP, GRIP, GRIP)

    def _columns(self) -> int:
        return max(1, (self.width() - 2 * PAD) // CELL_W)

    def _content_height(self) -> int:
        rows = (len(self._items) + self._columns() - 1) // self._columns()
        return rows * CELL_H

    def _visible_height(self) -> int:
        return max(0, self.height() - TITLE_H - PAD)

    def _clamp_scroll(self) -> None:
        self._scroll = max(0, min(self._scroll, self._content_height() - self._visible_height()))

    def cell_rect(self, index: int) -> QRect:
        cols = self._columns()
        row, col = divmod(index, cols)
        return QRect(PAD + col * CELL_W, TITLE_H + PAD // 2 + row * CELL_H - self._scroll, CELL_W, CELL_H)

    def item_at(self, pos: QPoint) -> int:
        if self._collapsed or pos.y() < TITLE_H:
            return -1
        for i in range(len(self._items)):
            if self.cell_rect(i).contains(pos):
                return i
        return -1

    # ------------------------------------------------------------------ painting

    def _generic_pixmap(self, is_dir: bool) -> QPixmap:
        if is_dir not in self._generic:
            style = QApplication.style()
            kind = QStyle.StandardPixmap.SP_DirIcon if is_dir else QStyle.StandardPixmap.SP_FileIcon
            self._generic[is_dir] = style.standardIcon(kind).pixmap(QSize(ICON, ICON))
        return self._generic[is_dir]

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        try:
            # Every device pixel catches the mouse and drops (alpha >= 2): no antialiasing and one
            # logical pixel extra, so fractional scaling (125%, 150%...) leaves no thin edge.
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.fillRect(self.rect().adjusted(0, 0, 1, 1), FLOOR_COLOR)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)  # icons at 125/150%

            box = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            path = QPainterPath()
            path.addRoundedRect(box, RADIUS, RADIUS)
            p.fillPath(path, BOX_COLOR)
            if self._drop_hover:
                p.fillPath(path, DROP_COLOR)

            # title bar
            title = QPainterPath()
            title.addRoundedRect(QRectF(0, 0, self.width(), TITLE_H if self._collapsed else TITLE_H + RADIUS),
                                 RADIUS, RADIUS)
            p.save()
            p.setClipRect(QRect(0, 0, self.width(), TITLE_H))
            p.fillPath(title, TITLE_COLOR)
            p.restore()
            p.setFont(self._title_font)
            fm = QFontMetrics(self._title_font)
            label = f"{self._name} ({len(self._items)})"
            text_w = self.width() - TITLE_H - 12
            p.setPen(TEXT_COLOR)
            p.drawText(QRect(12, 0, text_w, TITLE_H), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                       fm.elidedText(label, Qt.TextElideMode.ElideRight, text_w))
            self._paint_chevron(p, self.collapse_button_rect())

            if not self._collapsed:
                p.save()
                p.setClipRect(QRect(0, TITLE_H, self.width(), self.height() - TITLE_H))
                if self._items:
                    for i, item in enumerate(self._items):
                        r = self.cell_rect(i)
                        if r.bottom() < TITLE_H or r.top() > self.height():
                            continue
                        self._paint_item(p, item, r, hovered=(i == self._hover))
                else:
                    p.setFont(self._item_font)
                    p.setPen(QColor(255, 255, 255, 170))
                    p.drawText(QRect(PAD, TITLE_H, self.width() - 2 * PAD, self.height() - TITLE_H),
                               int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap), EMPTY_HINT)
                p.restore()

            if self._edit:
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor(255, 255, 255, 200), 1.5, Qt.PenStyle.DashLine))
                p.drawRoundedRect(box.adjusted(1.5, 1.5, -1.5, -1.5), RADIUS, RADIUS)
                if not self._collapsed:
                    g = self.grip_rect()
                    p.setPen(QPen(QColor(255, 255, 255, 220), 1.5))
                    for k in (4, 8, 12):
                        p.drawLine(g.right() - k, g.bottom() - 2, g.right() - 2, g.bottom() - k)
        finally:
            p.end()

    def _paint_chevron(self, p: QPainter, r: QRect) -> None:
        c = r.center()
        p.setPen(QPen(QColor(255, 255, 255, 220), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        if self._collapsed:  # ▸ (expand)
            p.drawLine(c.x() - 2, c.y() - 5, c.x() + 3, c.y())
            p.drawLine(c.x() + 3, c.y(), c.x() - 2, c.y() + 5)
        else:  # ▾ (collapse)
            p.drawLine(c.x() - 5, c.y() - 2, c.x(), c.y() + 3)
            p.drawLine(c.x(), c.y() + 3, c.x() + 5, c.y() - 2)

    def _paint_item(self, p: QPainter, item: ItemView, r: QRect, hovered: bool) -> None:
        if hovered:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(HOVER_COLOR)
            p.drawRoundedRect(QRectF(r).adjusted(3, 2, -3, -2), 6, 6)
        missing = item.exists is False
        p.save()
        if missing:
            p.setOpacity(MISSING_OPACITY)
        pix = item.pixmap if item.pixmap is not None and not item.pixmap.isNull() else self._generic_pixmap(item.is_dir)
        icon_rect = QRect(r.center().x() - ICON // 2, r.top() + 6, ICON, ICON)
        p.drawPixmap(icon_rect, pix)
        p.setFont(self._item_font)
        fm = QFontMetrics(self._item_font)
        text_rect = QRect(r.left() + 3, icon_rect.bottom() + 4, r.width() - 6, fm.height() * 2 + 2)
        text = fm.elidedText(item.name, Qt.TextElideMode.ElideRight, (text_rect.width() - 4) * 2 - fm.averageCharWidth())
        flags = int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWrapAnywhere)
        p.setPen(QColor(0, 0, 0, 160))
        p.drawText(text_rect.translated(1, 1), flags, text)
        p.setPen(TEXT_COLOR)
        p.drawText(text_rect, flags, text)
        p.restore()

    # ------------------------------------------------------------------ mouse

    def event(self, e):  # tooltips with the full path
        if e.type() == QEvent.Type.ToolTip:
            pos = e.pos()
            i = self.item_at(pos)
            if i >= 0:
                item = self._items[i]
                QToolTip.showText(e.globalPos(), item.path + (f"\n{TIP_MISSING}" if item.exists is False else ""), self)
            elif self.collapse_button_rect().contains(pos):
                QToolTip.showText(e.globalPos(), TIP_EXPAND if self._collapsed else TIP_COLLAPSE, self)
            else:
                QToolTip.hideText()
            return True
        return super().event(e)

    def mousePressEvent(self, event):  # noqa: N802
        pos = event.position().toPoint()
        self.pressed.emit()
        if event.button() == Qt.MouseButton.LeftButton:
            if self.collapse_button_rect().contains(pos):
                self._press = ("collapse", event.globalPosition().toPoint(), self.geometry())
            elif self._edit and not self._collapsed and self.grip_rect().contains(pos):
                self._press = ("resize", event.globalPosition().toPoint(), self.geometry())
            elif self._edit:
                self._press = ("move", event.globalPosition().toPoint(), self.geometry())
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        pos = event.position().toPoint()
        if self._press and event.buttons() & Qt.MouseButton.LeftButton:
            kind, start, geo = self._press
            delta = event.globalPosition().toPoint() - start
            if kind == "move":
                self.move(geo.topLeft() + delta)
            elif kind == "resize":
                w = max(MIN_WIDTH, geo.width() + delta.x())
                h = max(MIN_HEIGHT, geo.height() + delta.y())
                self._expanded_height = h
                self.setFixedSize(w, h)
                self._clamp_scroll()
            event.accept()
            return
        hover = self.item_at(pos)
        if hover != self._hover:
            self._hover = hover
            self.update()
        if self._edit:
            if not self._collapsed and self.grip_rect().contains(pos):
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif self.collapse_button_rect().contains(pos):
                self.setCursor(Qt.CursorShape.ArrowCursor)
            else:
                self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._press is None:
            super().mouseReleaseEvent(event)
            return
        kind, start, geo = self._press
        self._press = None
        pos = event.position().toPoint()
        if kind == "collapse":
            if self.collapse_button_rect().contains(pos):
                self.collapse_toggled.emit(not self._collapsed)
        elif self.geometry() != geo:
            self.geometry_edited.emit(self.x(), self.y(), self.width(), self._expanded_height)
        event.accept()

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            i = self.item_at(event.position().toPoint())
            if i >= 0:
                self.open_requested.emit(self._items[i].path)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        if self._hover != -1:
            self._hover = -1
            self.update()
        super().leaveEvent(event)

    def wheelEvent(self, event):  # noqa: N802
        if self._collapsed:
            return
        steps = event.angleDelta().y() / 120.0
        self._scroll -= int(steps * CELL_H * 0.6)
        self._clamp_scroll()
        self._hover = self.item_at(event.position().toPoint())
        self.update()
        event.accept()

    def contextMenuEvent(self, event):  # noqa: N802
        pos = event.pos()
        menu = QMenu()  # no parent: see the module docstring
        if pos.y() < TITLE_H:
            act_rename = QAction(TEXT_RENAME, menu)
            act_delete = QAction(TEXT_DELETE_ZONE, menu)
            menu.addAction(act_rename)
            menu.addSeparator()
            menu.addAction(act_delete)
            chosen = menu.exec(event.globalPos())
            if chosen is act_rename:
                self.rename_requested.emit()
            elif chosen is act_delete:
                self.delete_requested.emit()
            return
        i = self.item_at(pos)
        if i >= 0:
            path = self._items[i].path
            act_remove = QAction(TEXT_REMOVE_ITEM, menu)
            menu.addAction(act_remove)
            if menu.exec(event.globalPos()) is act_remove:
                self.remove_requested.emit(path)

    # ------------------------------------------------------------------ drag and drop (link only)

    def _accept_link(self, event) -> bool:
        if local_paths_from_mime(event.mimeData()) and link_is_possible(event.possibleActions()):
            event.setDropAction(Qt.DropAction.LinkAction)
            event.accept()
            return True
        event.ignore()
        return False

    def dragEnterEvent(self, event):  # noqa: N802
        accepted = self._accept_link(event)
        mime = event.mimeData()
        log.info(
            "drag entered zone %s: %s, offered actions %s, formats %s",
            self.zone_id, "accepted as link" if accepted else "refused",
            _actions_text(event.possibleActions()), ", ".join(mime.formats()[:6]) if mime else "-",
        )
        if accepted != self._drop_hover:
            self._drop_hover = accepted
            self.update()

    def dragMoveEvent(self, event):  # noqa: N802
        self._accept_link(event)

    def dragLeaveEvent(self, event):  # noqa: N802
        self._drop_hover = False
        self.update()

    def dropEvent(self, event):  # noqa: N802
        self._drop_hover = False
        self.update()
        paths = local_paths_from_mime(event.mimeData())
        if not paths or not link_is_possible(event.possibleActions()):
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.LinkAction)  # never Move or Copy: originals stay put
        event.accept()
        log.info("drop on zone %s: %d path(s) taken as a link", self.zone_id, len(paths))
        self.paths_dropped.emit(paths)


def item_views(paths: list[str]) -> list[ItemView]:
    return [ItemView(path=p, name=display_name(p)) for p in paths]


__all__ = ["ZoneWidget", "ItemView", "item_views", "local_paths_from_mime", "link_is_possible", "TITLE_H"]
