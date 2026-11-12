"""Folder zones: keeps the zone windows, settings.json and the background checks in step.

Every change the user makes in a zone (drop, remove, rename, collapse, move, resize,
delete) goes through ``SettingsStore.update`` and is saved at once.  The zone windows are
then brought in line with the settings (``sync_from_settings``), which is also what
happens when the user edits settings.json by hand.

Nothing here ever moves, copies or deletes a file or folder: zones only store paths.
"""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QImage, QPixmap

from versedesk.geometry import Rect, best_screen, clamp_into, place_on_screens
from versedesk.settings import LoadResult, Settings, SettingsStore
from versedesk.ui import dialogs
from versedesk.ui.zone_widget import TITLE_H, ItemView, ZoneWidget
from versedesk.zone_io import ZoneIO
from versedesk.zones import MAX_ITEMS, MAX_ZONES, AddResult, Zone, display_name, find_zone, new_zone_id, path_key

log = logging.getLogger("versedesk.zones")

RECHECK_MS = 30_000  # how often to notice originals that were moved, deleted or came back
CASCADE = 32

NOTE_CREATED = (
    "구역은 바탕화면에 붙어 있어 열린 창 뒤에 생깁니다(창을 내리거나 Win+D). "
    "폴더나 파일을 이 상자로 끌어다 놓으면 등록됩니다(원본은 그대로). "
    "옮기기·크기 바꾸기는 트레이 메뉴 → '배치 편집 켜기'."
)


class ZoneManager(QObject):
    def __init__(
        self,
        store: SettingsStore,
        layer,
        *,
        notify: Callable[..., None],
        screen_rects: Callable[[], tuple[list[Rect], Rect]],
        apply_reload: Callable[[LoadResult | None], None],
        io: ZoneIO | None = None,
        ask_name: Callable[..., str | None] = dialogs.ask_zone_name,
        confirm_delete: Callable[[str, int], bool] = dialogs.confirm_delete_zone,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.store = store
        self.layer = layer
        self._notify = notify
        self._screen_rects = screen_rects
        self._apply_reload = apply_reload
        self._ask_name = ask_name
        self._confirm_delete = confirm_delete
        self.io = io or ZoneIO(self)
        self.io.state_ready.connect(self._on_state)
        self.io.open_finished.connect(self._on_open_finished)
        self.widgets: dict[str, ZoneWidget] = {}
        self._states: dict[str, tuple[bool, bool, QPixmap | None, str]] = {}  # key -> exists, is_dir, icon, name
        self._edit = False
        self._started = False
        self._recheck = QTimer(self)
        self._recheck.setInterval(RECHECK_MS)
        self._recheck.timeout.connect(self._recheck_all)

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        self._started = True
        self.io.start()
        self.sync_from_settings()
        self._recheck.start()

    def stop(self) -> None:
        self._recheck.stop()
        self.io.stop()
        for w in self.widgets.values():
            w.hide()

    @property
    def zones(self) -> list[Zone]:
        return self.store.settings.zones

    # ------------------------------------------------------------------ settings -> windows

    def sync_from_settings(self) -> None:
        if not self._started:
            return
        wanted = {z.id: z for z in self.zones}
        for zid in list(self.widgets):
            if zid not in wanted:
                self._destroy(zid)
        for index, z in enumerate(self.zones):
            w = self.widgets.get(z.id)
            if w is None:
                w = self._create(z)
            self._apply(w, z, index)

    def _create(self, z: Zone) -> ZoneWidget:
        w = ZoneWidget(z.id, extra_flags=self.layer.extra_window_flags)
        zid = z.id
        w.open_requested.connect(lambda path, zid=zid: self.open_item(zid, path))
        w.remove_requested.connect(lambda path, zid=zid: self.remove_item(zid, path))
        w.rename_requested.connect(lambda zid=zid: self.rename_zone(zid))
        w.delete_requested.connect(lambda zid=zid: self.delete_zone(zid))
        w.collapse_toggled.connect(lambda collapsed, zid=zid: self.set_collapsed(zid, collapsed))
        w.paths_dropped.connect(lambda paths, zid=zid: self.add_items(zid, paths))
        w.geometry_edited.connect(lambda x, y, wd, ht, zid=zid: self.set_geometry(zid, x, y, wd, ht))
        w.pressed.connect(lambda w=w: self.layer.bring_to_front(w))
        w.set_edit_mode(self._edit)
        self.layer.attach(w, click_through=False)  # zones always take clicks and drops
        self.widgets[zid] = w
        log.info("zone %s (%r) created with %d items", zid, z.name, len(z.items))
        return w

    def _destroy(self, zid: str) -> None:
        w = self.widgets.pop(zid, None)
        if w is None:
            return
        self.layer.detach(w)
        w.hide()
        w.deleteLater()
        log.info("zone %s window removed", zid)

    def _apply(self, w: ZoneWidget, z: Zone, index: int) -> None:
        views = []
        for p in z.items:
            v = ItemView(path=p, name=display_name(p))
            state = self._states.get(path_key(p))
            if state is not None:
                v.exists, v.is_dir, v.pixmap = state[0], state[1], state[2]
                v.name = state[3] or v.name
            views.append(v)
        w.set_zone(z.name, views, z.collapsed, z.width, z.height)
        self._position(w, z, index)
        if not w.isVisible():
            w.show()
            self.layer.bring_to_front(w)  # a newer zone never hides under an older one
        unknown = [p for p in z.items if path_key(p) not in self._states]
        if unknown:
            self.io.check(unknown, force_icon=True)

    def _position(self, w: ZoneWidget, z: Zone, index: int) -> None:
        rects, prim = self._screen_rects()
        r = self.shown_rect(z, rects, prim) if z.has_position else self._default_rect(z.width, z.height, index, prim)
        if (w.x(), w.y()) != (r.x, r.y):
            w.move(r.x, r.y)

    @staticmethod
    def shown_rect(z: Zone, rects: list[Rect], prim: Rect) -> Rect:
        """Where a zone with a saved position appears. The screen is chosen by its title bar
        (what the user placed), and the box is kept inside that screen: a zone parked
        collapsed at the bottom of the second monitor opens upwards there instead of
        jumping to the main monitor."""
        bar = place_on_screens(Rect(z.x, z.y, z.width, TITLE_H), rects, prim)
        if z.collapsed:
            return bar
        i, _area = best_screen(bar, rects)
        screen = rects[i] if i >= 0 else prim
        return clamp_into(Rect(bar.x, bar.y, z.width, z.height), screen)

    @staticmethod
    def _default_rect(width: int, height: int, index: int, prim: Rect) -> Rect:
        """New zones go near the middle of the main screen (desktop icons usually sit at the
        left, the verse at the top right), each one a little lower and to the right."""
        x = prim.x + max(0, (prim.w - width) // 2) + (index % 8) * CASCADE
        y = prim.y + max(0, (prim.h - height) // 2) + (index % 8) * CASCADE
        return place_on_screens(Rect(x, y, width, height), [prim], prim)

    def _free_spot(self, width: int, height: int, rects: list[Rect], prim: Rect) -> Rect:
        """A spot on the main screen, near the middle, that no other zone covers."""
        taken = [self.shown_rect(z, rects, prim) for z in self.zones if z.has_position]
        cx, cy = prim.x + (prim.w - width) // 2, prim.y + (prim.h - height) // 2
        step_x, step_y = width + 16, height + 16
        candidates = [(cx, cy)]
        for ring in range(1, 4):
            for dx in range(-ring, ring + 1):
                for dy in range(-ring, ring + 1):
                    if max(abs(dx), abs(dy)) == ring:
                        candidates.append((cx + dx * step_x, cy + dy * step_y))
        for x, y in candidates:
            r = Rect(x, y, width, height)
            if prim.contains_rect(r) and not any(r.intersection_area(t) for t in taken):
                return r
        return self._default_rect(width, height, len(self.zones), prim)

    def reposition(self) -> None:
        """Screens changed: keep every zone on a screen (the saved positions stay as they are)."""
        for index, z in enumerate(self.zones):
            w = self.widgets.get(z.id)
            if w is not None:
                self._position(w, z, index)
                if not w.isVisible():
                    w.show()

    def set_edit_mode(self, on: bool) -> None:
        self._edit = on
        for w in self.widgets.values():
            w.set_edit_mode(on)

    # ------------------------------------------------------------------ changes from the user

    def _update(self, mutate: Callable[[Settings], None]) -> None:
        self._apply_reload(self.store.update(mutate))
        self.sync_from_settings()

    def add_zone(self) -> None:
        if len(self.zones) >= MAX_ZONES:
            self._notify("구역", f"구역은 {MAX_ZONES}개까지 만들 수 있습니다.", warning=True)
            return
        name = self._ask_name(dialogs.TITLE_NEW, "새 구역")
        if name is None:
            return
        rects, prim = self._screen_rects()
        z = Zone(id=new_zone_id(zz.id for zz in self.zones), name=name)
        r = self._free_spot(z.width, z.height, rects, prim)
        z.x, z.y = r.x, r.y

        def mutate(s: Settings) -> None:
            s.zones.append(z.copy())

        self._update(mutate)
        log.info("zone %s (%r) added", z.id, name)
        self._notify(f"'{name}' 구역을 만들었습니다", NOTE_CREATED)

    def add_items(self, zid: str, paths: list[str]) -> None:
        results: list[AddResult] = []

        def mutate(s: Settings) -> None:
            z = find_zone(s.zones, zid)
            if z is not None:
                results.append(z.add_paths(paths))

        self._update(mutate)
        if not results:
            return
        r = results[-1]
        log.info("zone %s: %d dropped, %d added, %d already there, %d over the limit, %d unusable",
                 zid, len(paths), len(r.added), len(r.duplicates), len(r.over_limit), len(r.invalid))
        if r.added:
            self.io.check(r.added, force_icon=True)
        if r.over_limit:
            self._notify("구역", f"구역 하나에는 항목을 {MAX_ITEMS}개까지 넣을 수 있습니다. "
                               f"{len(r.over_limit)}개는 넣지 않았습니다.", warning=True)
        elif r.duplicates and not r.added:
            self._notify("구역", "이미 이 구역에 들어 있는 항목입니다.")

    def remove_item(self, zid: str, path: str) -> None:
        def mutate(s: Settings) -> None:
            z = find_zone(s.zones, zid)
            if z is not None:
                z.remove_path(path)

        self._update(mutate)
        log.info("zone %s: removed %s (the original is untouched)", zid, path)

    def rename_zone(self, zid: str) -> None:
        z = find_zone(self.zones, zid)
        if z is None:
            return
        name = self._ask_name(dialogs.TITLE_RENAME, z.name)
        if name is None or name == z.name:
            return

        def mutate(s: Settings) -> None:
            zz = find_zone(s.zones, zid)
            if zz is not None:
                zz.name = name

        self._update(mutate)

    def delete_zone(self, zid: str) -> None:
        z = find_zone(self.zones, zid)
        if z is None:
            return
        if not self._confirm_delete(z.name, len(z.items)):
            return

        def mutate(s: Settings) -> None:
            s.zones[:] = [zz for zz in s.zones if zz.id != zid]

        self._update(mutate)
        log.info("zone %s (%r) deleted; its %d items were only removed from the list", zid, z.name, len(z.items))

    def set_collapsed(self, zid: str, collapsed: bool) -> None:
        def mutate(s: Settings) -> None:
            z = find_zone(s.zones, zid)
            if z is not None:
                z.collapsed = collapsed

        self._update(mutate)

    def set_geometry(self, zid: str, x: int, y: int, width: int, height: int) -> None:
        rects, prim = self._screen_rects()
        z = find_zone(self.zones, zid)
        if z is None:
            return
        shown_h = TITLE_H if z.collapsed else height
        placed = place_on_screens(Rect(x, y, width, shown_h), rects, prim)  # what the user sees stays on a screen

        def mutate(s: Settings) -> None:
            zz = find_zone(s.zones, zid)
            if zz is not None:
                zz.x, zz.y, zz.width, zz.height = placed.x, placed.y, width, height

        self._update(mutate)
        log.info("zone %s moved/resized to (%d, %d) %dx%d", zid, placed.x, placed.y, width, height)

    def open_item(self, zid: str, path: str) -> None:
        state = self._states.get(path_key(path))
        if state is not None and state[0] is False:
            self._notify("찾을 수 없습니다", f"{path}\n원래 자리에서 옮겨졌거나 삭제된 것 같습니다.", warning=True)
            self.io.check([path])
            return
        log.info("opening %s", path)
        self.io.open(path)

    # ------------------------------------------------------------------ background results

    def _on_state(self, path: str, exists: bool, is_dir: bool, name: str, image: QImage) -> None:
        k = path_key(path)
        old = self._states.get(k)
        pixmap = QPixmap.fromImage(image) if not image.isNull() else (old[2] if old else None)
        name = name or (old[3] if old else "")
        self._states[k] = (exists, is_dir, pixmap, name)
        for w in self.widgets.values():
            for item in w.items:
                if path_key(item.path) == k:
                    w.set_item_state(item.path, exists, is_dir, pixmap, name)

    def _on_open_finished(self, path: str, error: str) -> None:
        if error:
            log.warning("could not open %s: %s", path, error)
            self._notify("열 수 없습니다", f"{path}\n{error}", warning=True)
            self.io.check([path])

    def _recheck_all(self) -> None:
        paths = [p for z in self.zones for p in z.items]
        if paths:
            self.io.check(paths)

    def diagnostics(self) -> str:
        lines = [f"zones: {len(self.zones)}"]
        for z in self.zones:
            missing = sum(1 for p in z.items if (self._states.get(path_key(p)) or (True,))[0] is False)  # noqa: E501
            lines.append(f"  {z.id} {z.name!r}: {len(z.items)} items ({missing} missing), "
                         f"collapsed={z.collapsed} at ({z.x}, {z.y}) {z.width}x{z.height}")
        return "\n".join(lines)
