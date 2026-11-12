"""ZoneManager: every user action is saved, windows follow the settings, originals are untouched."""

import json
import os

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from versedesk.desktop_layer import NullDesktopLayer
from versedesk.geometry import Rect
from versedesk.settings import SettingsStore
from versedesk.ui.zone_widget import TITLE_H
from versedesk.zone_manager import ZoneManager


class FakeIO(QObject):
    """Synchronous stand-in for ZoneIO (no threads in unit tests)."""

    state_ready = Signal(str, bool, bool, QImage)
    open_finished = Signal(str, str)

    def __init__(self, open_error=""):
        super().__init__()
        self.checked, self.opened = [], []
        self.open_error = open_error

    def start(self):
        pass

    def stop(self):
        pass

    def check(self, paths, force_icon=False):
        for p in paths:
            self.checked.append(p)
            self.state_ready.emit(p, os.path.exists(p), os.path.isdir(p), QImage())

    def open(self, path):
        self.opened.append(path)
        self.open_finished.emit(path, self.open_error)


SCREEN = Rect(0, 0, 1920, 1040)


@pytest.fixture
def originals(tmp_path):
    folder = tmp_path / "보고서"
    folder.mkdir()
    (folder / "inside.txt").write_text("keep me", encoding="utf-8")
    f = tmp_path / "plan.txt"
    f.write_text("original content", encoding="utf-8")
    return folder, f


def _manager(qapp, tmp_path, names=("업무",), confirm=True, io=None):
    store = SettingsStore(tmp_path / "settings.json")
    store.load()
    notes = []
    queue = list(names)
    m = ZoneManager(
        store, NullDesktopLayer(),
        notify=lambda title, text, warning=False: notes.append((title, text, warning)),
        screen_rects=lambda: ([SCREEN], SCREEN),
        apply_reload=lambda result: None,
        io=io or FakeIO(),
        ask_name=lambda title, default: queue.pop(0) if queue else None,
        confirm_delete=lambda name, count: confirm,
    )
    m.start()
    return m, store, notes


def _saved(tmp_path):
    return json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))["zones"]


def test_new_zone_is_created_saved_and_shown(qapp, tmp_path):
    m, store, notes = _manager(qapp, tmp_path)
    m.add_zone()
    zones = _saved(tmp_path)
    assert [z["name"] for z in zones] == ["업무"]
    z = zones[0]
    assert z["items"] == [] and z["collapsed"] is False and z["x"] is not None
    w = m.widgets[z["id"]]
    assert w.isVisible() and (w.x(), w.y()) == (z["x"], z["y"])
    assert m.layer.is_click_through(w) is False  # zones take clicks
    assert notes and "업무" in notes[0][0]


def test_cancelled_name_creates_nothing(qapp, tmp_path):
    m, store, notes = _manager(qapp, tmp_path, names=())
    m.add_zone()
    assert store.settings.zones == [] and m.widgets == {}


def test_dropped_items_are_registered_once_and_originals_stay(qapp, tmp_path, originals):
    folder, f = originals
    m, store, notes = _manager(qapp, tmp_path)
    m.add_zone()
    zid = store.settings.zones[0].id
    m.add_items(zid, [str(folder), str(f)])
    m.add_items(zid, [str(f)])  # the same path again
    assert _saved(tmp_path)[0]["items"] == [str(folder), str(f)]
    assert notes[-1][1] == "이미 이 구역에 들어 있는 항목입니다."
    m.remove_item(zid, str(f))
    assert _saved(tmp_path)[0]["items"] == [str(folder)]
    # nothing on disk was moved, copied or deleted
    assert f.read_text(encoding="utf-8") == "original content"
    assert (folder / "inside.txt").read_text(encoding="utf-8") == "keep me"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["plan.txt", "settings.json", "보고서"]


def test_deleting_a_zone_asks_first_and_leaves_files_alone(qapp, tmp_path, originals):
    folder, f = originals
    m, store, notes = _manager(qapp, tmp_path, confirm=False)
    m.add_zone()
    zid = store.settings.zones[0].id
    m.add_items(zid, [str(folder), str(f)])
    m.delete_zone(zid)  # the user pressed 취소
    assert len(_saved(tmp_path)) == 1 and zid in m.widgets
    m._confirm_delete = lambda name, count: True
    m.delete_zone(zid)
    assert _saved(tmp_path) == [] and m.widgets == {}
    assert f.exists() and folder.exists() and (folder / "inside.txt").exists()


def test_rename_collapse_and_geometry_are_saved(qapp, tmp_path):
    m, store, notes = _manager(qapp, tmp_path, names=("업무", "사진"))
    m.add_zone()
    zid = store.settings.zones[0].id
    m.rename_zone(zid)
    m.set_collapsed(zid, True)
    assert m.widgets[zid].height() == TITLE_H
    m.set_geometry(zid, 300, 200, 420, 330)
    z = _saved(tmp_path)[0]
    assert (z["name"], z["collapsed"], z["x"], z["y"], z["width"], z["height"]) == ("사진", True, 300, 200, 420, 330)
    m.set_collapsed(zid, False)
    assert m.widgets[zid].height() == 330


def test_zone_moved_off_screen_is_kept_on_a_screen(qapp, tmp_path):
    m, store, notes = _manager(qapp, tmp_path)
    m.add_zone()
    zid = store.settings.zones[0].id
    m.set_geometry(zid, 5000, -800, 340, 260)
    z = _saved(tmp_path)[0]
    assert 0 <= z["x"] <= SCREEN.w - 340 and 0 <= z["y"] <= SCREEN.h - 260


def test_open_uses_the_worker_and_reports_failures(qapp, tmp_path, originals):
    folder, f = originals
    io = FakeIO(open_error="이 파일을 열 프로그램이 없습니다")
    m, store, notes = _manager(qapp, tmp_path, io=io)
    m.add_zone()
    zid = store.settings.zones[0].id
    m.add_items(zid, [str(f)])
    m.open_item(zid, str(f))
    assert io.opened == [str(f)]
    assert notes[-1][0] == "열 수 없습니다" and notes[-1][2] is True


def test_missing_original_is_dimmed_and_not_opened(qapp, tmp_path, originals):
    folder, f = originals
    io = FakeIO()
    m, store, notes = _manager(qapp, tmp_path, io=io)
    m.add_zone()
    zid = store.settings.zones[0].id
    m.add_items(zid, [str(f)])
    os.remove(f)  # the user deleted it in Explorer
    m._recheck_all()
    w = m.widgets[zid]
    assert [i.exists for i in w.items] == [False]
    m.open_item(zid, str(f))
    assert io.opened == [] and notes[-1][0] == "찾을 수 없습니다"


def test_outside_edits_of_settings_json_are_followed(qapp, tmp_path):
    m, store, notes = _manager(qapp, tmp_path)
    data = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8")) if (tmp_path / "settings.json").exists() else {}
    data["zones"] = [{"id": "hand", "name": "손으로 추가", "items": ["C:\\\\Temp"]}]
    (tmp_path / "settings.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    store.poll()
    m.sync_from_settings()
    assert list(m.widgets) == ["hand"]
    data["zones"] = []
    (tmp_path / "settings.json").write_text(json.dumps(data), encoding="utf-8")
    os.utime(tmp_path / "settings.json", ns=(1, 2))
    store.poll()
    m.sync_from_settings()
    assert m.widgets == {}


def test_edit_mode_reaches_every_zone(qapp, tmp_path):
    m, store, notes = _manager(qapp, tmp_path, names=("a", "b"))
    m.add_zone()
    m.add_zone()
    m.set_edit_mode(True)
    assert all(w._edit for w in m.widgets.values()) and len(m.widgets) == 2
    m.set_edit_mode(False)
    assert not any(w._edit for w in m.widgets.values())
