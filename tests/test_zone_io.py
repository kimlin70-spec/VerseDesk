"""The zone worker threads, and the Windows shell helpers (those run in CI on Windows)."""

import os
import sys
import time

import pytest
from PySide6.QtCore import QCoreApplication

from versedesk.zone_io import MISSING, ZoneIO, bgra_to_qimage


def _wait(predicate, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_worker_reports_states_and_opens_off_the_gui_thread(qapp, tmp_path):
    import threading

    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    (tmp_path / "bad").write_text("x", encoding="utf-8")
    threads, opened = set(), []

    def probe(path):
        threads.add(threading.current_thread().name)
        return os.path.exists(path), os.path.isdir(path)

    def opener(path):
        threads.add(threading.current_thread().name)
        opened.append(path)
        return "boom" if path.endswith("bad") else None

    io = ZoneIO(probe=probe, info=lambda p, e, d: ("이름", (1, 1, b"\x00\x00\xff\xff")), opener=opener)
    states, finished = [], []
    io.state_ready.connect(lambda p, e, d, name, img: states.append((p, e, d, img.width())) or names.append(name))
    names = []
    io.open_finished.connect(lambda p, err: finished.append((p, err)))
    io.check([str(f), str(tmp_path / "missing")], force_icon=True)
    io.open(str(f))
    io.open(str(tmp_path / "bad"))
    io.open(str(tmp_path / "missing"))  # checked again before opening: never handed to Windows
    assert _wait(lambda: len(states) == 2 and len(finished) == 3)
    assert (str(f), True, False, 1) in states
    assert (str(tmp_path / "missing"), False, True, 1) in states  # no extension: shown as a folder
    assert finished == [(str(f), ""), (str(tmp_path / "bad"), "boom"), (str(tmp_path / "missing"), MISSING)]
    assert str(tmp_path / "missing") not in opened
    assert threads == {"zone-probe", "zone-open"}
    assert set(names) == {"이름"}
    # unchanged state: no new report unless an icon is asked for
    io.check([str(f)])
    time.sleep(0.2)
    QCoreApplication.processEvents()
    assert len(states) == 2
    io.stop()


def test_bgra_pixels_become_an_image_with_alpha(qapp):
    img = bgra_to_qimage((2, 1, bytes([255, 0, 0, 255, 0, 0, 0, 0])))  # blue opaque, transparent
    assert img.width() == 2 and img.pixelColor(0, 0).blue() == 255 and img.pixelColor(1, 0).alpha() == 0
    assert bgra_to_qimage(None).isNull()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows shell API")
def test_windows_icons_for_folders_files_and_missing_paths(qapp, tmp_path):
    from versedesk.win32 import shell as ws

    ws.init_thread_com()
    name, folder = ws.shell_info(os.environ.get("SystemRoot", "C:\\Windows"), True, True)
    assert name  # Explorer's display name
    assert folder is not None and folder[0] >= 16 and len(folder[2]) == folder[0] * folder[1] * 4
    assert any(folder[2][3::4])  # has visible pixels
    f = tmp_path / "doc.txt"
    f.write_text("x", encoding="utf-8")
    assert ws.file_icon_bgra(str(f), True, False) is not None
    assert ws.file_icon_bgra(str(tmp_path / "gone.xlsx"), False, False) is not None  # by extension only


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_windows_launch_environment_is_cleaned_and_restored(monkeypatch, tmp_path):
    from versedesk.win32 import shell as ws

    meipass = str(tmp_path / "_MEI12345")
    os.makedirs(meipass)
    monkeypatch.setattr(sys, "_MEIPASS", meipass, raising=False)
    monkeypatch.setenv("PATH", os.pathsep.join([meipass, os.path.join(meipass, "PySide6"), r"C:\Windows\System32"]))
    monkeypatch.setenv("QT_PLUGIN_PATH", os.path.join(meipass, "plugins"))
    before = dict(os.environ)
    with ws.clean_launch_environment():
        assert os.environ["PATH"] == r"C:\Windows\System32"
        assert "QT_PLUGIN_PATH" not in os.environ
    assert dict(os.environ) == before
