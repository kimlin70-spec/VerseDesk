"""Live check of VerseDesk.exe on a real Windows desktop (run by GitHub Actions).

    python tools/ci_desktop_check.py dist/VerseDesk.exe --report ci-report

It starts the exe with a clean profile and verifies, through the Win32 API, the behaviour
the user cannot easily test one by one:
  * the verse window exists, is a tool window (no taskbar/Alt+Tab), never activates,
    is not owned by Explorer and sits directly above the desktop window;
  * click-through: hit tests over every uncovered part of the verse must land on the window
    *below* it.  While Show desktop leaves the verse uncovered on a plain background, the
    test samples the drawn text itself (a layered window lets clicks through its fully
    transparent pixels anyway) and a control run without WS_EX_TRANSPARENT must hit the
    verse there, so the test can really fail;
  * a normal application window placed on top of it stays on top;
  * after Win+D (Show desktop) the verse is still visible above the desktop, and the
    normal window is not; Win+D again restores the normal window above the verse;
  * after explorer.exe is killed and restarted, the verse re-attaches to the new desktop;
  * a second launch exits immediately (single instance);
  * autostart (HKCU Run) is registered on first run; settings.json and log.txt exist;
  * `--exit-after` quits cleanly with exit code 0;
  * resource use while idle (CPU, memory) is measured and reported (WARN if high);
  * edit mode (배치 편집): the verse catches the mouse, a real drag moves it, the position
    is saved to settings.json and a restart shows it there again;
  * real mouse clicks on the verse's drawn text, in the normal state (runner consoles
    minimised) and during Show desktop, must not reach the app (it logs any that do);
  * folder zones: styles, every pixel takes the mouse, a real OLE drag offering
    Copy|Move|Link is taken as a LINK and the original stays, 구역에서 빼기 via the
    right-click menu, double-click opens a folder in Explorer, collapse/expand is saved;
  * the verse list editor (말씀 목록 편집) is a normal window; a reference typed with
    real keyboard input ("요 8:12" + Enter) is looked up in the built-in BSB and saved to
    verses.json; closing the window leaves the app running;
  * the Explorer window slot (탐색기 창 자리 고정): off = Explorer windows are left alone;
    on = a newly opened Explorer window's visible frame lands exactly on the slot, a window
    that was already open and a window moved afterwards are not touched, a changed slot is
    used at once, a window that opens maximised is put into the slot; in edit mode the
    frame can be dragged and resized with the mouse and the new place is saved.
Screenshots and the app's log are written to the report folder (uploaded as an artifact).
The exit code is 1 if a required check fails.  Checks that depend on the CI machine's
shell (Win+D, explorer restart) report WARN instead of FAIL when the shell itself does
not behave like a normal desktop, so the log explains rather than hides it.  SKIP means
a check could not be decided at that moment (it is repeated where it can be).
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from ctypes import wintypes
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from versedesk.win32 import api  # noqa: E402
from versedesk.win32.desktop import check_placement, describe_desktop, find_desktop_host  # noqa: E402

VERSE_TITLE = "VerseDesk Verse"
DARK_DESKTOP = (22, 40, 70)  # plain desktop colour used while judging legibility and click-through
TEST_TITLE = "VerseDesk CI test window"
RESULTS: list[dict] = []


def record(name: str, status: str, detail: str = "") -> None:
    RESULTS.append({"check": name, "status": status, "detail": detail})
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def expect(name: str, ok: bool, detail: str = "", warn_only: bool = False) -> bool:
    record(name, "PASS" if ok else ("WARN" if warn_only else "FAIL"), detail)
    return ok


# ----------------------------------------------------------------------------- win32 helpers

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.EnumWindows.argtypes = [api.WNDENUMPROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
user32.keybd_event.restype = None

user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = wintypes.BOOL
user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
user32.mouse_event.restype = None

VK_LWIN, VK_D = 0x5B, 0x44
KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
SW_MINIMIZE = 6
WHITE_DESKTOP = (255, 255, 255)
STRAY_CLICK_TEXT = "reached the verse window although clicks should pass through"


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.ClientToScreen.restype = wintypes.BOOL
user32.IsZoomed.argtypes = [wintypes.HWND]
user32.IsZoomed.restype = wintypes.BOOL
user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                                       wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
user32.SendInput.restype = wintypes.UINT
INPUT_KEYBOARD, KEYEVENTF_UNICODE, VK_RETURN = 1, 0x0004, 0x0D


def type_text(text: str) -> int:
    """Type ``text`` as real keyboard input (Unicode packets, so Korean needs no IME)."""
    sent = 0
    for ch in text:
        for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
            inp = INPUT(type=INPUT_KEYBOARD)
            inp.u.ki = KEYBDINPUT(0, ord(ch), flags, 0, 0)
            sent += user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        time.sleep(0.03)
    return sent


def press_key(vk: int) -> None:
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def top_level_windows() -> list[int]:
    """All top-level windows, topmost first (EnumWindows order is z-order)."""
    out: list[int] = []

    @api.WNDENUMPROC
    def cb(hwnd, _lparam):
        out.append(api.h(hwnd))
        return True

    user32.EnumWindows(cb, 0)
    return out


def find_window(title: str, timeout: float) -> int:
    end = time.time() + timeout
    while time.time() < end:
        for w in top_level_windows():
            if api.window_text(w) == title:
                return w
        time.sleep(0.25)
    return 0


def zindex(hwnd: int) -> int:
    try:
        return top_level_windows().index(hwnd)
    except ValueError:
        return -1


def press_win_d() -> None:
    user32.keybd_event(VK_LWIN, 0, 0, 0)
    user32.keybd_event(VK_D, 0, 0, 0)
    user32.keybd_event(VK_D, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_LWIN, 0, KEYEVENTF_KEYUP, 0)


def flags_text(ex: int) -> str:
    names = [("TOOLWINDOW", api.WS_EX_TOOLWINDOW), ("NOACTIVATE", api.WS_EX_NOACTIVATE),
             ("LAYERED", api.WS_EX_LAYERED), ("TRANSPARENT", api.WS_EX_TRANSPARENT),
             ("TOPMOST", api.WS_EX_TOPMOST), ("APPWINDOW", api.WS_EX_APPWINDOW)]
    return "|".join(n for n, b in names if ex & b) or "-"


def visible_on_top_at(hwnd: int, others: list[int]) -> bool:
    """True if none of ``others`` is above ``hwnd`` in z-order while overlapping it."""
    order = top_level_windows()
    if hwnd not in order:
        return False
    my = order.index(hwnd)
    l, t, r, b = api.window_rect(hwnd)
    for o in others:
        if o in order and order.index(o) < my and api.IsWindowVisible(o) and not api.IsIconic(o):
            ol, ot, or_, ob = api.window_rect(o)
            if ol < r and or_ > l and ot < b and ob > t:
                return False
    return True


def screenshot(report: Path, name: str) -> None:
    try:
        from PIL import ImageGrab

        img = ImageGrab.grab(all_screens=True)
        img.save(report / f"{name}.png")
        print(f"  screenshot {name}.png {img.size}", flush=True)
    except Exception as e:  # screenshots are best effort
        print(f"  screenshot {name} failed: {e}", flush=True)


def set_desktop_color(rgb: tuple[int, int, int]) -> None:
    """Plain-colour desktop background (no wallpaper) so text legibility can be judged."""
    SPI_SETDESKWALLPAPER, SPIF_SENDCHANGE, COLOR_DESKTOP = 0x0014, 0x0002, 1
    try:
        user32.SystemParametersInfoW(SPI_SETDESKWALLPAPER, 0, ctypes.c_wchar_p(""), SPIF_SENDCHANGE)
        colors = (ctypes.c_int * 1)(COLOR_DESKTOP)
        values = (wintypes.DWORD * 1)(rgb[0] | (rgb[1] << 8) | (rgb[2] << 16))
        user32.SetSysColors(1, colors, values)
    except Exception as e:
        print(f"  could not set desktop colour: {e}", flush=True)


def print_crop(name: str, hwnd: int, margin: int = 12) -> None:
    """Print a PNG crop of a window as base64 into the job log (artifacts are not always reachable)."""
    try:
        import base64
        import io

        from PIL import ImageGrab

        l, t, r, b = api.window_rect(hwnd)
        img = ImageGrab.grab(bbox=(l - margin, t - margin, r + margin, b + margin), all_screens=True)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=80, optimize=True)
        data = base64.b64encode(buf.getvalue()).decode()
        print(f"BEGIN_JPEG {name} {img.size[0]}x{img.size[1]}", flush=True)
        print(data, flush=True)
        print(f"END_JPEG {name}", flush=True)
    except Exception as e:
        print(f"  crop {name} failed: {e}", flush=True)


def process_stats(image: str) -> list[tuple[int, float, int, int]]:
    """(pid, cpu seconds, working set bytes, private bytes) of every process named ``image``."""
    script = (f"Get-Process -Name {image} -ErrorAction SilentlyContinue | ForEach-Object "
              "{ '{0} {1} {2} {3}' -f $_.Id, $_.TotalProcessorTime.TotalSeconds, $_.WorkingSet64, "
              "$_.PrivateMemorySize64 }")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, text=True, timeout=60)
    rows = []
    for line in r.stdout.split("\n"):
        parts = line.split()
        if len(parts) == 4:
            try:
                rows.append((int(parts[0]), float(parts[1].replace(",", ".")), int(parts[2]), int(parts[3])))
            except ValueError:
                pass
    return rows


def check_resources(seconds: float = 10.0) -> None:
    """The app lives in the background all day: it must be light while idle."""
    before = {pid: cpu for pid, cpu, _ws, _pv in process_stats("VerseDesk")}
    start = time.time()
    time.sleep(seconds)
    after = process_stats("VerseDesk")
    elapsed = time.time() - start
    if not after:
        record("resource use while idle", "WARN", "could not read process statistics")
        return
    cpu = sum(c - before.get(pid, c) for pid, c, _ws, _pv in after)
    ws = sum(w for _p, _c, w, _pv in after)
    pv = sum(p for _p, _c, _w, p in after)
    pct = 100.0 * cpu / elapsed
    detail = (f"{len(after)} processes (onefile launcher + app): idle CPU {pct:.2f}% of one core over "
              f"{elapsed:.0f}s, working set {ws / 2**20:.0f} MB, private {pv / 2**20:.0f} MB")
    expect("idle CPU stays low (under 2% of one core)", pct < 2.0, detail, warn_only=True)
    expect("memory stays modest (working set under 200 MB)", ws < 200 * 2**20, detail, warn_only=True)


def minimize_consoles() -> int:
    """Minimise the runner's own console windows, which otherwise cover the verse."""
    n = 0
    for w in top_level_windows():
        if (api.IsWindowVisible(w) and not api.IsIconic(w)
                and api.class_name(w) in ("ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS")):
            user32.ShowWindow(w, SW_MINIMIZE)
            n += 1
    return n


def click(x: int, y: int) -> None:
    """A real left click (mouse input, not a message), as a user would make it."""
    user32.SetCursorPos(x, y)
    time.sleep(0.2)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def stray_clicks_logged(appdata: Path) -> int:
    try:
        return (appdata / "log.txt").read_text(encoding="utf-8", errors="replace").count(STRAY_CLICK_TEXT)
    except OSError:
        return 0


def drag(x0: int, y0: int, dx: int, dy: int, steps: int = 25) -> None:
    """Press the left button at (x0, y0), move by (dx, dy) in small steps, release."""
    user32.SetCursorPos(x0, y0)
    time.sleep(0.3)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.3)
    for i in range(1, steps + 1):
        user32.SetCursorPos(x0 + dx * i // steps, y0 + dy * i // steps)
        time.sleep(0.03)
    time.sleep(0.3)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def saved_verse_position(appdata: Path) -> tuple[object, object]:
    try:
        verse = json.loads((appdata / "settings.json").read_text(encoding="utf-8")).get("verse", {})
        return verse.get("x"), verse.get("y")
    except (OSError, ValueError, AttributeError):
        return None, None


def check_edit_mode(exe: Path, appdata: Path, report: Path) -> None:
    """배치 편집: the verse catches the mouse, can be dragged, the position is saved, and a
    restart puts it back there.  (--edit-mode starts the app as if 배치 편집 had been
    switched on from the tray; the tray menu itself cannot be driven here.)"""
    proc = subprocess.Popen([str(exe), "--edit-mode", "--exit-after", "30"])
    moved_to = None
    try:
        verse = find_window(VERSE_TITLE, 60)
        if not expect("edit mode: verse window appears", bool(verse)):
            return
        time.sleep(3)
        ex = api.ex_style(verse)
        expect("edit mode: the verse catches clicks (no WS_EX_TRANSPARENT)", not ex & api.WS_EX_TRANSPARENT,
               flags_text(ex))
        press_win_d()  # uncover the verse: Show desktop lifts it above every window
        time.sleep(3)
        l, t, r, b = api.window_rect(verse)
        x0, y0 = l + 20, b - 12  # on the translucent edit background, away from the text
        root = root_at(x0, y0)
        expect("edit mode: the whole box can be grabbed, not only the letters", root == verse,
               f"WindowFromPoint({x0}, {y0}) -> root {api.describe(root)}")
        drag(x0, y0, -200, 120)
        time.sleep(2)
        l2, t2, _r2, _b2 = api.window_rect(verse)
        moved_to = (l2, t2)
        expect("edit mode: dragging moves the verse", abs((l2 - l) + 200) <= 3 and abs((t2 - t) - 120) <= 3,
               f"({l},{t}) -> ({l2},{t2})")
        sx, sy = saved_verse_position(appdata)
        expect("edit mode: the new position is saved in settings.json",
               isinstance(sx, int) and isinstance(sy, int) and abs(sx - l2) <= 2 and abs(sy - t2) <= 2,
               f"settings.json x={sx!r} y={sy!r}, window at ({l2},{t2})")
        screenshot(report, "06-edit-mode-dragged")
        press_win_d()
        time.sleep(2)
    finally:
        try:
            code = proc.wait(timeout=90)
        except subprocess.TimeoutExpired:
            kill_tree(proc.pid)
            code = None
    expect("edit mode run quits cleanly", code == 0, f"exit code {code}")
    if moved_to is None:
        return
    proc = subprocess.Popen([str(exe), "--exit-after", "12"])
    try:
        verse = find_window(VERSE_TITLE, 60)
        time.sleep(3)
        where = api.window_rect(verse)[:2] if verse else None
        expect("after a restart the verse is where it was dragged to",
               where is not None and abs(where[0] - moved_to[0]) <= 2 and abs(where[1] - moved_to[1]) <= 2,
               f"dragged to {moved_to}, after restart {where}")
        if verse:
            ex = api.ex_style(verse)
            expect("after a restart clicks pass through again (edit mode is not remembered)",
                   bool(ex & api.WS_EX_TRANSPARENT), flags_text(ex))
    finally:
        try:
            proc.wait(timeout=90)
        except subprocess.TimeoutExpired:
            kill_tree(proc.pid)


# ----------------------------------------------------------------------------- folder zones

ZONE_ID = "ci"
ZONE_GEO = (40, 330, 340, 260)  # x, y, width, height: lower left, away from the verse


def double_click(x: int, y: int) -> None:
    user32.SetCursorPos(x, y)
    time.sleep(0.2)
    for _ in range(2):
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(0.06)


def right_click(x: int, y: int) -> None:
    MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
    user32.SetCursorPos(x, y)
    time.sleep(0.2)
    user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)


def saved_zone(appdata: Path) -> dict:
    try:
        data = json.loads((appdata / "settings.json").read_text(encoding="utf-8"))
        return next((z for z in data.get("zones", []) if z.get("id") == ZONE_ID), {})
    except (OSError, ValueError):
        return {}


def wait_for(predicate, timeout: float = 5.0, step: float = 0.2):
    end = time.time() + timeout
    while True:
        value = predicate()
        if value or time.time() > end:
            return value
        time.sleep(step)


def item_center(zone_rect, index: int) -> tuple[int, int]:
    """Centre of an item's icon, from the zone window's own layout constants."""
    from versedesk.ui.zone_widget import CELL_H, CELL_W, ICON, PAD, TITLE_H

    l, t, r, _b = zone_rect
    cols = max(1, ((r - l) - 2 * PAD) // CELL_W)
    row, col = divmod(index, cols)
    return l + PAD + col * CELL_W + CELL_W // 2, t + TITLE_H + PAD // 2 + row * CELL_H + 6 + ICON // 2


def ole_drag_file(path: Path, target: tuple[int, int]) -> object:
    """A real OLE drag (as Explorer makes one) of ``path`` onto ``target``: the source offers
    Copy, Move and Link with Move proposed.  Returns the action the drop target chose."""
    import threading

    from PySide6.QtCore import QMimeData, Qt, QUrl
    from PySide6.QtGui import QDrag
    from PySide6.QtWidgets import QApplication, QWidget

    app = QApplication.instance() or QApplication([])
    src = QWidget()
    src.setWindowTitle("VerseDesk CI drag source")
    src.setGeometry(60, 140, 160, 70)
    src.show()
    for _ in range(20):
        app.processEvents()
        time.sleep(0.05)
    sx, sy = src.geometry().center().x(), src.geometry().center().y()
    user32.SetCursorPos(sx, sy)
    for _ in range(6):  # Qt must have handled the move to the source before the press
        app.processEvents()
        time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    for _ in range(6):  # ...and the press (it takes the mouse capture), as in a real drag start
        app.processEvents()
        time.sleep(0.05)

    def drive():
        time.sleep(0.5)
        steps = 30
        for i in range(1, steps + 1):
            user32.SetCursorPos(sx + (target[0] - sx) * i // steps, sy + (target[1] - sy) * i // steps)
            time.sleep(0.04)
        time.sleep(0.6)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    threading.Thread(target=drive, daemon=True).start()
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    drag = QDrag(src)
    drag.setMimeData(mime)
    result = drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction | Qt.DropAction.LinkAction,
                       Qt.DropAction.MoveAction)
    src.close()
    app.processEvents()
    return result


def image_name(pid: int) -> str:
    r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True)
    first = (r.stdout or "").strip().splitlines()[:1]
    return first[0].split('","')[0].strip('"').lower() if first and first[0].startswith('"') else ""


DRAG_SOURCE_AREA = (40, 120, 240, 230)  # where ole_drag_file puts its source window


def clear_area(target: int, extra=(DRAG_SOURCE_AREA,), spare=()) -> list[str]:
    """Runner desktops pop up stray windows during the run (after the explorer restart a
    'System Properties' and then a 'Performance Options' dialog appeared over the zone).
    Close or minimise every foreign window that overlaps ``target`` or ``extra`` areas,
    repeating until none is left. Windows of the processes in ``spare`` are left alone."""
    own = {api.process_id(target), os.getpid(), *spare}
    keep_titles = ("VerseDesk CI keeper", "VerseDesk CI drag source")
    shell = ("Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman", "WorkerW")
    cleared: list[str] = []
    for _attempt in range(5):
        areas = [api.window_rect(target), *extra]
        found = []
        for w in top_level_windows():
            if not api.IsWindowVisible(w) or api.IsIconic(w) or api.is_cloaked(w):
                continue
            if api.process_id(w) in own or api.class_name(w) in shell or api.window_text(w) in keep_titles:
                continue
            wl, wt, wr, wb = api.window_rect(w)
            if any(wl < r and wr > l and wt < b and wb > t for l, t, r, b in areas):
                found.append(w)
        if not found:
            break
        for w in found:
            pid = api.process_id(w)
            name = image_name(pid)
            cleared.append(f"{api.describe(w)} [{name}]")
            if name.startswith("systemproperties"):
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
            elif api.class_name(w) == "#32770":
                user32.PostMessageW(w, 0x0010, 0, 0)  # WM_CLOSE a stray dialog
            else:
                user32.ShowWindow(w, SW_MINIMIZE)
        time.sleep(1.5)
    if cleared:
        print("  cleared stray windows over the test area: " + "; ".join(cleared), flush=True)
    return cleared


def popup_windows_of(pid: int) -> list[int]:
    return [w for w in top_level_windows()
            if api.IsWindowVisible(w) and api.process_id(w) == pid and "Popup" in api.class_name(w)]


def check_zones(exe: Path, appdata: Path, report: Path) -> None:
    """Folder zones on the real desktop: styles, every pixel takes the mouse, an OLE drop is
    taken as a LINK (the original stays), 구역에서 빼기, double-click opens, collapse."""
    from PySide6.QtCore import Qt

    base = Path(os.environ.get("TEMP", str(report))) / "VerseDeskCI"
    shutil.rmtree(base, ignore_errors=True)
    folder = base / "CI Folder"
    folder.mkdir(parents=True)
    (folder / "inside.txt").write_text("keep", encoding="utf-8")
    doc = base / "CI File.txt"
    doc.write_text("original", encoding="utf-8")
    gone = base / "Gone.txt"
    dropped = base / "CI Drop.txt"
    dropped.write_text("drop me", encoding="utf-8")

    settings_path = appdata / "settings.json"
    data = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
    x, y, w, h = ZONE_GEO
    data["zones"] = [{"id": ZONE_ID, "name": "CI 구역", "x": x, "y": y, "width": w, "height": h,
                      "collapsed": False, "items": [str(folder), str(doc), str(gone)]}]
    settings_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    proc = subprocess.Popen([str(exe), "--exit-after", "80"])
    keeper = None
    try:
        zone = find_window(f"VerseDesk Zone {ZONE_ID}", 60)
        if not expect("zones: the zone window appears", bool(zone)):
            return
        time.sleep(3)
        ex = api.ex_style(zone)
        owner = api.h(api.GetWindow(zone, api.GW_OWNER))
        expect("zones: tool window that never activates (TOOLWINDOW+NOACTIVATE)",
               bool(ex & api.WS_EX_TOOLWINDOW) and bool(ex & api.WS_EX_NOACTIVATE), flags_text(ex))
        expect("zones: takes clicks and drops (not WS_EX_TRANSPARENT)", not ex & api.WS_EX_TRANSPARENT, flags_text(ex))
        expect("zones: not topmost and not owned by Explorer", not ex & api.WS_EX_TOPMOST and owner == 0,
               f"{flags_text(ex)} owner={api.describe(owner)}")
        expect("zones: sits directly above the desktop (with the verse)", check_placement(zone, find_desktop_host())[0])

        minimize_consoles()
        keeper = subprocess.Popen([sys.executable, "-c", (
            "import tkinter as tk; r = tk.Tk(); r.title('VerseDesk CI keeper'); "
            "r.geometry('200x100+620+560'); r.after(240000, r.destroy); r.mainloop()")])
        find_window("VerseDesk CI keeper", 30)
        time.sleep(2)
        clear_area(zone)
        rect = api.window_rect(zone)
        l, t, r, b = rect
        grid = [(px, py) for py in range(t + 1, b - 1, 6) for px in range(l + 1, r - 1, 6)]
        roots = [root_at(px, py) for px, py in grid]
        leaks = [(pt, root) for pt, root in zip(grid, roots) if root != zone]
        hit = {}
        for pt, root in leaks:
            hit.setdefault(root, []).append(pt)
        what = "; ".join(f"{len(pts)} -> {api.describe(root)} e.g. {pts[0]}" for root, pts in list(hit.items())[:3])
        expect("zones: every part of the box catches the mouse (nothing falls through)", not leaks,
               f"{len(grid)} points, {len(leaks)} reached another window" + (f": {what}" if leaks else ""))
        print_crop("zone-start", zone)

        # A real OLE drag offering Copy|Move|Link (Move proposed) must be taken as a Link.
        clear_area(zone)
        before = list(saved_zone(appdata).get("items", []))
        result = ole_drag_file(dropped, ((l + r) // 2, (t + b) // 2 + 30))
        expect("zones: a dropped file is taken as a LINK (never Move or Copy)", result == Qt.DropAction.LinkAction,
               f"drop target chose {result}")
        items = wait_for(lambda: [i for i in saved_zone(appdata).get("items", []) if i.lower() == str(dropped).lower()])
        expect("zones: the dropped file is registered in settings.json", bool(items),
               f"before={before} after={saved_zone(appdata).get('items')}")
        expect("zones: the dropped original is still in its place, unchanged",
               dropped.exists() and dropped.read_text(encoding="utf-8") == "drop me")
        try:
            for line in (appdata / "log.txt").read_text(encoding="utf-8", errors="replace").splitlines():
                if "drag" in line or "drop" in line:
                    print("  app log: " + line[-220:], flush=True)
        except OSError:
            pass
        time.sleep(1.5)
        print_crop("zone-after-drop", zone)

        # 구역에서 빼기 via the right-click menu: the item leaves the list, the file stays.
        index = len(saved_zone(appdata).get("items", [])) - 1
        clear_area(zone)
        right_click(*item_center(rect, index))
        popups = wait_for(lambda: popup_windows_of(api.process_id(zone)), timeout=5)
        if expect("zones: right-click on an item opens its menu", bool(popups)):
            pl, pt_, pr, pb = api.window_rect(popups[0])
            click((pl + pr) // 2, pt_ + min(18, (pb - pt_) // 2))
            gone_from_list = wait_for(lambda: not any(i.lower() == str(dropped).lower()
                                                       for i in saved_zone(appdata).get("items", [])))
            expect("zones: 구역에서 빼기 removes the item from the zone", bool(gone_from_list),
                   f"items={saved_zone(appdata).get('items')}")
            expect("zones: ...and the original file is left alone", dropped.exists())

        # Collapse and expand with the title bar button.
        clear_area(zone)
        click(r - 15, t + 15)
        collapsed = wait_for(lambda: saved_zone(appdata).get("collapsed") is True)
        cl, ct, cr, cb = api.window_rect(zone)
        expect("zones: the collapse button leaves only the title bar (saved)", bool(collapsed) and cb - ct <= 40,
               f"height {cb - ct}, collapsed={saved_zone(appdata).get('collapsed')}")
        click(r - 15, t + 15)
        expanded = wait_for(lambda: saved_zone(appdata).get("collapsed") is False)
        el, et, er, eb = api.window_rect(zone)
        expect("zones: pressing it again shows the items again (saved)", bool(expanded) and eb - et == b - t,
               f"height {eb - et} (was {b - t})")
        # Double-click the folder item: Explorer opens it.
        clear_area(zone)
        before_windows = set(top_level_windows())
        double_click(*item_center(rect, 0))
        opened = wait_for(lambda: [w2 for w2 in top_level_windows() if w2 not in before_windows
                                   and api.class_name(w2) == "CabinetWClass" and api.IsWindowVisible(w2)], timeout=15)
        expect("zones: double-clicking a folder opens it in Explorer", bool(opened),
               f"{api.describe(opened[0])}" if opened else "no new Explorer window")
        for w2 in opened or []:
            user32.PostMessageW(w2, 0x0010, 0, 0)  # WM_CLOSE
        wait_for(lambda: not any(api.IsWindow(w2) and api.IsWindowVisible(w2) for w2 in opened or []), timeout=10)

        expect("zones: originals in the zone were never touched",
               folder.is_dir() and (folder / "inside.txt").read_text(encoding="utf-8") == "keep"
               and doc.read_text(encoding="utf-8") == "original")
    finally:
        if keeper is not None:
            keeper.kill()
        try:
            code = proc.wait(timeout=120)
        except subprocess.TimeoutExpired:
            kill_tree(proc.pid)
            code = None
        expect("zones: the app quits cleanly", code == 0, f"exit code {code}")


# ----------------------------------------------------------------------------- verse list editor

EDITOR_TITLE = "VerseDesk 말씀 목록"
EDITOR_TYPED = "요 8:12"  # John 8:12: not in the built-in list, typed in Korean
EDITOR_EXPECT = "John 8:12 (BSB)"


def saved_verse_list(appdata: Path) -> list:
    try:
        return json.loads((appdata / "verses.json").read_text(encoding="utf-8")).get("verses", [])
    except (OSError, ValueError, AttributeError):
        return []


def check_verse_editor(exe: Path, appdata: Path, report: Path) -> None:
    """말씀 목록 편집: a normal window; typing a reference + Enter saves the BSB text to verses.json
    (the whole Bible is built into the exe); closing it leaves the app running.
    (--open-verse-editor opens it as if chosen in the tray, which cannot be driven here.)"""
    from versedesk.bible import Bible
    from versedesk.verses import load_builtin
    from versedesk import paths as vd_paths

    builtin = load_builtin(vd_paths.embedded_verses_path())
    expected = Bible.load().lookup(EDITOR_TYPED)
    if any(v.reference == EDITOR_EXPECT for v in builtin):
        record("verse editor: test reference is new", "FAIL", f"{EDITOR_EXPECT} is already in the built-in list")
        return
    (appdata / "verses.json").unlink(missing_ok=True)
    proc = subprocess.Popen([str(exe), "--open-verse-editor", "--exit-after", "60"])
    try:
        editor = find_window(EDITOR_TITLE, 60)
        if not expect("verse editor: the window opens", bool(editor)):
            return
        time.sleep(2)
        ex = api.ex_style(editor)
        expect("verse editor: a normal window (taskbar, Alt+Tab), unlike the desktop widgets",
               bool(api.IsWindowVisible(editor)) and not ex & (api.WS_EX_TOOLWINDOW | api.WS_EX_NOACTIVATE)
               and not ex & api.WS_EX_TOPMOST, flags_text(ex))
        fg = api.h(api.GetForegroundWindow())
        expect("verse editor: comes to the front when opened", fg == editor, f"foreground={api.describe(fg)}",
               warn_only=True)
        verse = find_window(VERSE_TITLE, 5)
        if verse:
            expect("verse editor: the verse stays on the desktop under it", check_placement(verse, find_desktop_host())[0])
        minimize_consoles()
        user32.SetForegroundWindow(editor)
        time.sleep(0.5)
        # click into the reference box (top row of the window) so the keys surely land there
        point = wintypes.POINT(0, 0)
        user32.ClientToScreen(editor, ctypes.byref(point))
        click(point.x + 300, point.y + 22)
        time.sleep(0.5)
        sent = type_text(EDITOR_TYPED)
        press_key(VK_RETURN)
        saved = wait_for(lambda: saved_verse_list(appdata) or None, timeout=10) or []
        screenshot(report, "07-verse-editor")
        last = saved[-1] if saved else {}
        expect("verse editor: a typed reference is looked up in the built-in BSB and saved",
               last.get("reference") == expected.reference and last.get("text") == expected.text,
               f"typed {EDITOR_TYPED!r} ({sent} key events): saved {len(saved)} verses, last={last}")
        expect("verse editor: the rest of the list is kept, in order",
               [v.get("reference") for v in saved[:-1]] == [v.reference for v in builtin],
               f"{len(saved)} saved, {len(builtin)} built in")
        user32.PostMessageW(editor, 0x0010, 0, 0)  # WM_CLOSE: like the window's X button
        closed = wait_for(lambda: not api.IsWindow(editor) or not api.IsWindowVisible(editor), timeout=10)
        expect("verse editor: closes with its X button", bool(closed))
        time.sleep(2)
        expect("verse editor: closing it leaves VerseDesk running", proc.poll() is None)
    finally:
        try:
            code = proc.wait(timeout=120)
        except subprocess.TimeoutExpired:
            kill_tree(proc.pid)
            code = None
        expect("verse editor: the app quits cleanly", code == 0, f"exit code {code}")


# ----------------------------------------------------------------------------- explorer window slot

SLOT_FRAME_TITLE = "VerseDesk Explorer Slot"
EXPLORER_CLASS = "CabinetWClass"
SW_MAXIMIZE = 3
SLOT_1 = dict(x=260, y=90, width=620, height=440)
SLOT_2 = dict(x=330, y=60, width=560, height=500)
SLOT_3 = dict(x=90, y=130, width=640, height=430)  # never used while the feature is on
# Explorer remembers by itself where its last window was closed (and not always the last one),
# so a check must never rely on that: every "placed" check uses a slot the previous window
# was not in, and every "left alone" check a rectangle no window was ever put in.
SLOT_WARNINGS = ("RegisterShellHookWindow failed", "could not start watching", "pausing corrections",
                 "Windows refused the move", "could not be restored", "gave up waiting")


def slot_rect(slot: dict) -> tuple[int, int, int, int]:
    return (slot["x"], slot["y"], slot["x"] + slot["width"], slot["y"] + slot["height"])


def explorer_windows() -> list[int]:
    return [w for w in top_level_windows() if api.class_name(w) == EXPLORER_CLASS and api.IsWindowVisible(w)]


def seen_rect(hwnd: int) -> tuple[int, int, int, int]:
    """What is seen of the window (without the invisible resize borders)."""
    return api.frame_bounds(hwnd) or api.window_rect(hwnd)


def near(a, b, tolerance: int = 2) -> bool:
    return all(abs(p - q) <= tolerance for p, q in zip(a, b))


def open_folder(path: Path, timeout: float = 30.0, through_shell: bool = False) -> int:
    """Open ``path`` in Explorer; the new window's handle, or 0 if no new window appeared
    (newer Windows 11 builds can open a folder as a tab of a window that is already open).
    ``through_shell``: like a double-click on a desktop folder (the window then belongs to the
    shell's own explorer.exe); otherwise ``explorer.exe <path>`` (a separate process)."""
    before = set(explorer_windows())
    if through_shell:
        os.startfile(str(path))  # noqa: S606 - a folder made by this script
    else:
        subprocess.Popen(["explorer.exe", str(path)])
    new = wait_for(lambda: [w for w in explorer_windows() if w not in before], timeout=timeout, step=0.1)
    return new[0] if new else 0


def close_windows(windows) -> None:
    for w in windows:
        if w and api.IsWindow(w):
            user32.PostMessageW(w, 0x0010, 0, 0)  # WM_CLOSE
    wait_for(lambda: not any(w and api.IsWindow(w) and api.IsWindowVisible(w) for w in windows), timeout=10)
    time.sleep(1.0)  # let Explorer write down where the window was


def set_slot(appdata: Path, **slot) -> None:
    path = appdata / "settings.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data["explorer_window"] = slot
    tmp = path.with_name("settings.json.ci-tmp")  # the app re-reads the file every 2 s: never show it half-written
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def saved_slot(appdata: Path) -> dict:
    try:
        return json.loads((appdata / "settings.json").read_text(encoding="utf-8")).get("explorer_window", {})
    except (OSError, ValueError, AttributeError):
        return {}


def slot_log(appdata: Path, since: int = 0) -> list[str]:
    """The app's log lines about Explorer windows written after the first ``since`` of them."""
    try:
        text = (appdata / "log.txt").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [ln for ln in text.splitlines() if "explorer window" in ln and "explorer window slot: o" not in ln][since:]


def print_slot_log(appdata: Path, since: int) -> list[str]:
    lines = slot_log(appdata, since)
    for line in lines:
        print("  app log: " + line[-300:], flush=True)
    return lines


def expect_placed(name: str, hwnd: int, rect, timeout: float = 10.0) -> bool:
    placed = bool(hwnd) and wait_for(lambda: near(seen_rect(hwnd), rect) and not user32.IsZoomed(hwnd),
                                     timeout=timeout, step=0.1)
    time.sleep(1.5)  # ...and it must stay there
    ok = bool(placed) and near(seen_rect(hwnd), rect) and not user32.IsZoomed(hwnd)
    return expect(name, ok, f"slot {rect}, visible frame {seen_rect(hwnd) if hwnd else None}, "
                            f"window rect {api.window_rect(hwnd) if hwnd else None}")


def start_stand_in(scenario: str, delay: float, life: float = 45.0, rect: str = "60,420,420,300"):
    """Start tools/ci_fake_explorer.py; returns (process, hwnd)."""
    proc = subprocess.Popen(
        [sys.executable, str(REPO / "tools" / "ci_fake_explorer.py"), scenario, "--delay", str(delay),
         "--life", str(life), "--rect", rect], stdout=subprocess.PIPE, text=True)
    line = proc.stdout.readline().strip()
    hwnd = int(line.split()[1]) if line.startswith("HWND ") else 0
    if not hwnd:
        print(f"  stand-in window ({scenario}) did not start: {line!r}", flush=True)
    return proc, hwnd


def wait_line(proc, word: str, timeout: float) -> bool:
    """Wait for the stand-in to print ``word`` (it prints one word per step)."""
    import threading

    got: list[str] = []
    t = threading.Thread(target=lambda: got.append(proc.stdout.readline().strip()), daemon=True)
    t.start()
    t.join(timeout)
    return bool(got) and got[0] == word


def exit_file(appdata: Path) -> Path:
    return appdata / "ci-exit-now"


def start_app(exe: Path, appdata: Path, *flags: str, cap: int = 240):
    """Start the exe so that it quits (the normal way) as soon as end_app() asks, or after ``cap`` s."""
    exit_file(appdata).unlink(missing_ok=True)
    return subprocess.Popen([str(exe), *flags, "--exit-file", str(exit_file(appdata)), "--exit-after", str(cap)])


def end_app(proc, appdata: Path, name: str) -> None:
    exit_file(appdata).write_text("quit", encoding="utf-8")
    try:
        code = proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        kill_tree(proc.pid)
        code = None
    exit_file(appdata).unlink(missing_ok=True)
    expect(name, code == 0, f"exit code {code}")


def responds(hwnd: int, timeout_ms: int = 1000) -> bool:
    """Does the window's program answer a message in time (i.e. is its main thread not stuck)?"""
    result = ctypes.c_size_t(0)
    return bool(user32.SendMessageTimeoutW(hwnd, 0, 0, 0, 0x0002, timeout_ms, ctypes.byref(result)))  # WM_NULL, ABORTIFHUNG


def check_explorer_slot(exe: Path, appdata: Path, report: Path) -> None:
    """탐색기 창 자리 고정 on the real desktop (the screen is at 100 %, so settings = native pixels)."""
    base = Path(os.environ.get("TEMP", str(report))) / "VerseDeskCI-slot"
    shutil.rmtree(base, ignore_errors=True)
    folders = []
    for name in ("Slot A", "Slot B", "Slot C", "Slot D", "Slot E", "Slot F", "Slot G", "Slot H"):
        (base / name).mkdir(parents=True)
        folders.append(base / name)
    close_windows(explorer_windows())
    rect1, rect2 = slot_rect(SLOT_1), slot_rect(SLOT_2)

    # ---- real Explorer windows -------------------------------------------------------
    set_slot(appdata, enabled=False)
    logged = len(slot_log(appdata))
    proc = start_app(exe, appdata)
    opened: list[int] = []
    try:
        if not expect("explorer slot: the app starts", bool(find_window(VERSE_TITLE, 60))):
            return
        time.sleep(3)
        minimize_consoles()

        # Feature off: Explorer decides where its window goes, and it stays there.
        w0 = open_folder(folders[0])
        opened.append(w0)
        if not expect("explorer slot: an Explorer window can be opened on this machine", bool(w0)):
            return
        time.sleep(3)
        natural = seen_rect(w0)
        time.sleep(2)
        expect("explorer slot: while the feature is off, Explorer windows are left alone",
               seen_rect(w0) == natural, f"at {natural}, later {seen_rect(w0)}")

        # Switched on while w0 is open (settings.json is re-read within 2 s).
        set_slot(appdata, enabled=True, **SLOT_1)
        time.sleep(5)
        expect("explorer slot: a window that was already open is not moved when the feature is switched on",
               seen_rect(w0) == natural, f"was {natural}, now {seen_rect(w0)}")
        expect("explorer slot: ...because the app noted it as already open (log)",
               any("1 Explorer window(s) already open" in ln for ln in slot_log(appdata, logged)),
               " | ".join(ln[-160:] for ln in slot_log(appdata, logged)))

        w1 = open_folder(folders[1], timeout=20)
        if not w1:
            record("explorer slot: a second folder opens in its own window", "SKIP",
                   "no new window (opened as a tab of the first one); closing the first and trying again")
            close_windows([w0])
            w1 = open_folder(folders[1])
        opened.append(w1)
        if not expect("explorer slot: a new Explorer window appears", bool(w1)):
            return
        expect_placed("explorer slot: a new Explorer window opens exactly in the slot", w1, rect1)
        screenshot(report, "08-explorer-slot")
        if api.IsWindow(w0):
            expect("explorer slot: the window that was already open is still where it was",
                   seen_rect(w0) == natural, f"was {natural}, now {seen_rect(w0)}")

        # While the mouse button is held nothing is moved; after the release the window is placed
        # (a double-click whose second click is still held when the window appears).
        close_windows([w0, w1])
        set_slot(appdata, enabled=True, **SLOT_2)
        time.sleep(5)
        keeper = subprocess.Popen([sys.executable, "-c", (
            "import tkinter as tk; r = tk.Tk(); r.title('VerseDesk CI keeper'); "
            "r.geometry('260x120+20+600'); r.after(60000, r.destroy); r.mainloop()")])
        kw = find_window("VerseDesk CI keeper", 30)
        time.sleep(1)
        if kw:
            kl, kt, kr, kb = api.window_rect(kw)
            user32.SetCursorPos(kl + 130, kt + 60)  # inside the keeper window: holding there drags nothing
            time.sleep(0.2)
            user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            try:
                w1 = open_folder(folders[1])
                opened.append(w1)
                time.sleep(2.5)
                held_at = seen_rect(w1) if w1 else None
                expect("explorer slot: while the mouse button is held, a new window is not moved yet",
                       bool(w1) and not near(held_at, slot_rect(SLOT_2)), f"slot {slot_rect(SLOT_2)}, window at {held_at}")
            finally:
                user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            expect_placed("explorer slot: ...and it is placed as soon as the button is released", w1, slot_rect(SLOT_2))
        keeper.kill()
        set_slot(appdata, enabled=True, **SLOT_1)
        time.sleep(5)

        # The user moves the window afterwards: it is theirs now.
        api.SetWindowPos(w1, None, 40, 300, 520, 380, api.SWP_NOZORDER | api.SWP_NOACTIVATE)
        time.sleep(0.5)
        moved = seen_rect(w1)
        user32.SetForegroundWindow(w1)  # ...and clicking it (activation) must not pull it back either
        time.sleep(3)
        expect("explorer slot: a window moved afterwards stays where it was put",
               seen_rect(w1) == moved and not near(moved, rect1) and not near(moved, rect2),
               f"moved to {moved}, later {seen_rect(w1)}")

        # A changed slot is used for the next window, opened the way a double-click on a
        # desktop folder does (the window then belongs to the shell's own process).
        close_windows([w0, w1])
        set_slot(appdata, enabled=True, **SLOT_2)
        time.sleep(5)
        w2 = open_folder(folders[2], through_shell=True)
        opened.append(w2)
        expect_placed("explorer slot: after the slot was changed, a folder opened through the shell lands in the new slot",
                      w2, rect2)
        if w2:
            shell_pid = api.process_id(api.h(api.GetShellWindow()))
            print(f"  that window belongs to pid {api.process_id(w2)} (the shell is pid {shell_pid})", flush=True)

        # A window that opens maximised: Explorer remembers "maximised" and, as the normal
        # place, slot 2 - so with slot 1 active it has to be restored AND moved.
        if w2:
            user32.ShowWindow(w2, SW_MAXIMIZE)
            time.sleep(1.5)
            close_windows([w2])
        set_slot(appdata, enabled=True, **SLOT_1)
        time.sleep(5)
        before_log = len(slot_log(appdata))
        w3 = open_folder(folders[3])
        opened.append(w3)
        expect_placed("explorer slot: a window that opens maximised is restored and put into the slot", w3, rect1)
        lines = slot_log(appdata, before_log)
        was_maximised = any("opened maximised" in ln for ln in lines)
        if was_maximised:
            expect("explorer slot: ...by restoring it first and then moving it (log)",
                   any("placed in the slot" in ln for ln in lines), " | ".join(ln[-120:] for ln in lines))
        else:
            record("explorer slot: the window really opened maximised", "SKIP",
                   "Explorer did not open it maximised on this machine: " + " | ".join(ln[-100:] for ln in lines))

        # explorer.exe restarts (crash, update) while the feature is on: new windows are still placed.
        close_windows([w3])
        old_host = find_desktop_host()
        subprocess.run(["taskkill", "/F", "/IM", "explorer.exe"], capture_output=True)
        time.sleep(3)
        subprocess.Popen(["explorer.exe"])
        wait_for(lambda: find_desktop_host() not in (0, old_host), timeout=45, step=0.5)
        time.sleep(6)
        close_windows(explorer_windows())  # a restarted Explorer may open a window of its own
        set_slot(appdata, enabled=True, **SLOT_2)
        time.sleep(5)
        w4 = open_folder(folders[4])
        opened.append(w4)
        expect_placed("explorer slot: after explorer.exe restarted, new windows are still placed", w4, rect2)

        # Switched off again: the next window is not sent to the slot (a rectangle no window was
        # ever in), and the app does not even look at it.
        close_windows([w4])
        set_slot(appdata, enabled=False, **SLOT_3)
        time.sleep(5)
        quiet_from = len(slot_log(appdata))
        w5 = open_folder(folders[5])
        opened.append(w5)
        time.sleep(4)
        expect("explorer slot: switched off again, new windows are left alone",
               bool(w5) and not near(seen_rect(w5), slot_rect(SLOT_3)) and not slot_log(appdata, quiet_from),
               f"slot {slot_rect(SLOT_3)}, window at {seen_rect(w5) if w5 else None}, log {slot_log(appdata, quiet_from)}")
    finally:
        lines = print_slot_log(appdata, logged)
        expect("explorer slot: no trouble reported in the app's log (real Explorer windows)",
               not [ln for ln in lines if any(word in ln for word in SLOT_WARNINGS)])
        expect("explorer slot: the window watcher is registered again when Explorer restarts (log)",
               any("registering the window watcher again (Explorer restarted)" in ln for ln in lines), warn_only=True)
        close_windows([w for w in opened if w] + explorer_windows())
        end_app(proc, appdata, "explorer slot: the app quits cleanly")

    # ---- awkward windows, played by a stand-in with Explorer's window class ------------
    set_slot(appdata, enabled=False, **SLOT_1)
    logged = len(slot_log(appdata))
    proc = start_app(exe, appdata)
    helpers = []
    opened = []
    try:
        verse = find_window(VERSE_TITLE, 60)
        if not expect("explorer slot (stand-in windows): the app starts", bool(verse)):
            return
        time.sleep(3)
        minimize_consoles()

        # (1) A window that exists hidden before the feature is switched on (Explorer may keep
        #     one ready): it is not "already open", and it is placed when it first shows.
        hidden, hidden_hwnd = start_stand_in("hidden", delay=9)
        helpers.append(hidden)
        time.sleep(1)
        set_slot(appdata, enabled=True, **SLOT_1)  # switched on while the hidden window exists
        if expect("explorer slot: a window kept hidden appears", bool(hidden_hwnd) and wait_line(hidden, "SHOWN", 20)):
            expect_placed("explorer slot: a window that was hidden when the feature was switched on is placed "
                          "when it first shows", hidden_hwnd, rect1)
        if hidden_hwnd:
            user32.PostMessageW(hidden_hwnd, 0x0010, 0, 0)

        # (2) A window reported while it is cloaked (invisible): not moved then; placed when it
        #     is on screen and the user turns to it.
        cloaked, cloaked_hwnd = start_stand_in("cloaked", delay=6)
        helpers.append(cloaked)
        time.sleep(4.5)  # longer than the app waits for a hidden window
        if cloaked_hwnd:
            l, t, r, b = api.window_rect(cloaked_hwnd)
            expect("explorer slot: a cloaked window is not moved while it cannot be seen",
                   (l, t) == (60, 420), f"window rect {(l, t, r, b)}")
            if expect("explorer slot: the cloaked window is uncloaked", wait_line(cloaked, "UNCLOAKED", 20)):
                time.sleep(0.5)
                clear_area(cloaked_hwnd, extra=(), spare=(api.process_id(verse),))
                user32.SetForegroundWindow(cloaked_hwnd)
                l, t, r, b = api.window_rect(cloaked_hwnd)
                click(l + 120, t + 14)  # a real click on its title bar, as a user would turn to it
                expect_placed("explorer slot: ...and is placed once it is on screen and gets activated",
                              cloaked_hwnd, rect1)
            user32.PostMessageW(cloaked_hwnd, 0x0010, 0, 0)

        # (3) A window that does not respond for a while (busy or hung Explorer), from the moment
        #     it appears: the app's request to move it has to wait, the app itself must not -
        #     another window opened meanwhile is placed at once. (That other window is a stand-in
        #     too: a real Explorer window may open in the slot by itself, from its own memory -
        #     it did in run 34 - and then nothing would show that the app moved anything.)
        before_log = len(slot_log(appdata))
        slow, slow_hwnd = start_stand_in("slow", delay=4)
        helpers.append(slow)
        if slow_hwnd and expect("explorer slot: a window stops responding", wait_line(slow, "HUNG", 20)):
            time.sleep(1.0)  # the app has asked the stuck window to move by now
            expect("explorer slot: the stand-in window really is stuck", not responds(slow_hwnd, 300))
            expect("explorer slot: ...so the request to move it is still waiting",
                   not near(seen_rect(slow_hwnd), rect1), f"window at {seen_rect(slow_hwnd)}, slot {rect1}", warn_only=True)
            expect("explorer slot: VerseDesk keeps responding while an Explorer window is stuck", responds(verse))
            other, other_hwnd = start_stand_in("plain", delay=0, rect="520,330,400,300")
            helpers.append(other)
            moved = bool(other_hwnd) and wait_for(lambda: near(seen_rect(other_hwnd), rect1), timeout=10, step=0.05)
            still_stuck = not responds(slow_hwnd, 200)
            expect("explorer slot: ...and another window opened meanwhile is still placed", bool(moved),
                   f"slot {rect1}, visible frame {seen_rect(other_hwnd) if other_hwnd else None}")
            expect("explorer slot: ...while the first one was still stuck", still_stuck, warn_only=True)
            if other_hwnd:
                user32.PostMessageW(other_hwnd, 0x0010, 0, 0)
            wait_line(slow, "AWAKE", 20)
            expect_placed("explorer slot: the slow window is placed once it responds again", slow_hwnd, rect1)
            expect("explorer slot: ...by the request that had been waiting (log)",
                   any("placed in the slot" in ln and f"0x{slow_hwnd:X}" in ln for ln in slot_log(appdata, before_log)),
                   " | ".join(ln[-120:] for ln in slot_log(appdata, before_log)))
            user32.PostMessageW(slow_hwnd, 0x0010, 0, 0)

        # (4) A window that refuses the slot's size: asked a limited number of times, then left alone.
        before_log = len(slot_log(appdata))
        stubborn, stubborn_hwnd = start_stand_in("minsize", delay=0)
        helpers.append(stubborn)
        if stubborn_hwnd:
            gave_up = wait_for(lambda: [ln for ln in slot_log(appdata, before_log)
                                        if "keeps its own size" in ln or "left as it is" in ln], timeout=12, step=0.3)
            got = seen_rect(stubborn_hwnd)
            expect("explorer slot: a window that refuses the size is left alone after a few tries (log)",
                   bool(gave_up), f"visible frame {got}; log: " + " | ".join(ln[-110:] for ln in slot_log(appdata, before_log)))
            expect("explorer slot: ...it is at the slot's corner with its own size",
                   near(got[:2], rect1[:2]) and (got[2] - got[0], got[3] - got[1]) != (SLOT_1["width"], SLOT_1["height"]),
                   f"visible frame {got}, slot {rect1}")
            user32.PostMessageW(stubborn_hwnd, 0x0010, 0, 0)

        # (5) A window that opens minimised has not been on screen yet: it is placed when the
        #     user brings it up (not dropped because nothing could be done at first).
        before_log = len(slot_log(appdata))
        mini, mini_hwnd = start_stand_in("minimised", delay=6)  # longer than the app waits for it
        helpers.append(mini)
        if mini_hwnd and expect("explorer slot: a window that opened minimised is brought up",
                                wait_line(mini, "RESTORED", 20)):
            time.sleep(0.5)
            clear_area(mini_hwnd, extra=(), spare=(api.process_id(verse),))
            user32.SetForegroundWindow(mini_hwnd)
            l, t, r, b = api.window_rect(mini_hwnd)
            click(l + 120, t + 14)  # the user turns to it
            expect_placed("explorer slot: ...and is placed then", mini_hwnd, rect1)
            expect("explorer slot: ...after the app had waited for it to come on screen (log)",
                   any("not on screen yet" in ln and f"0x{mini_hwnd:X}" in ln for ln in slot_log(appdata, before_log)),
                   " | ".join(ln[-120:] for ln in slot_log(appdata, before_log)), warn_only=True)
            user32.PostMessageW(mini_hwnd, 0x0010, 0, 0)

        # ...and after all that a real Explorer window is still placed (in another slot, so that
        # it cannot be Explorer's own memory; the app's log must name this very window).
        set_slot(appdata, enabled=True, **SLOT_2)
        time.sleep(5)
        before_log = len(slot_log(appdata))
        w7 = open_folder(folders[7])
        opened.append(w7)
        expect_placed("explorer slot: after the awkward windows, a real Explorer window is still placed", w7, rect2)
        expect("explorer slot: ...by the app (log)",
               any("placed in the slot" in ln and f"0x{w7:X}" in ln for ln in slot_log(appdata, before_log)),
               " | ".join(ln[-120:] for ln in slot_log(appdata, before_log)))
    finally:
        print_slot_log(appdata, logged)
        for h in helpers:
            h.kill()
        close_windows([w for w in opened if w] + explorer_windows())
        end_app(proc, appdata, "explorer slot (stand-in windows): the app quits cleanly")

    # ---- 배치 편집: the frame shows the slot, can be dragged and resized, the place is saved ----
    set_slot(appdata, enabled=True, x=200, y=150, width=520, height=360)
    proc = start_app(exe, appdata, "--edit-mode")
    try:
        frame = find_window(SLOT_FRAME_TITLE, 60)
        if not expect("explorer slot: in edit mode the frame appears", bool(frame) and bool(api.IsWindowVisible(frame))):
            return
        time.sleep(3)
        minimize_consoles()
        ex = api.ex_style(frame)
        expect("explorer slot: the frame is where the slot is", near(api.window_rect(frame), (200, 150, 720, 510), 1),
               f"{api.window_rect(frame)}")
        expect("explorer slot: the frame floats above other windows and stays out of the taskbar and Alt+Tab",
               bool(ex & api.WS_EX_TOPMOST) and bool(ex & api.WS_EX_TOOLWINDOW), flags_text(ex))
        verse = find_window(VERSE_TITLE, 5)
        if verse:
            expect("explorer slot: the frame does not disturb the verse on the desktop",
                   check_placement(verse, find_desktop_host())[0])
        screenshot(report, "09-explorer-slot-frame")
        drag(200 + 60, 150 + 40, 90, 50)
        time.sleep(1.5)
        expect("explorer slot: dragging the frame moves it", near(api.window_rect(frame), (290, 200, 810, 560), 3),
               f"{api.window_rect(frame)}")
        s = saved_slot(appdata)
        l, t, r, b = api.window_rect(frame)
        expect("explorer slot: the new place is saved in settings.json",
               near((s.get("x") or 0, s.get("y") or 0, s.get("width") or 0, s.get("height") or 0),
                    (l, t, r - l, b - t), 1), f"settings {s}, frame {(l, t, r, b)}")
        drag(r - 6, b - 6, 60, 40)
        time.sleep(1.5)
        l2, t2, r2, b2 = api.window_rect(frame)
        expect("explorer slot: dragging the corner resizes the frame",
               near((l2, t2), (l, t), 1) and near((r2 - r, b2 - b), (60, 40), 3), f"{(l, t, r, b)} -> {(l2, t2, r2, b2)}")
        s = saved_slot(appdata)
        expect("explorer slot: the new size is saved in settings.json",
               near((s.get("width") or 0, s.get("height") or 0), (r2 - l2, b2 - t2), 1), f"settings {s}")
        # the frame shows exactly where a window will go: open one and compare
        w8 = open_folder(folders[0])
        expect_placed("explorer slot: a window opened now covers exactly the frame", w8, (l2, t2, r2, b2))
        close_windows([w8])
        # Show desktop (Win+D) while the frame is visible: the verse is lifted as usual, the frame
        # stays above it, and the desktop layer does not start fighting over the z-order.
        if verse:
            press_win_d()
            time.sleep(3)
            host = find_desktop_host()
            expect("explorer slot: with the frame visible, Win+D still lifts the verse above the desktop",
                   zindex(verse) < zindex(host), f"z(verse)={zindex(verse)} z(host)={zindex(host)}", warn_only=True)
            expect("explorer slot: ...and the frame stays above the verse", zindex(frame) < zindex(verse),
                   f"z(frame)={zindex(frame)} z(verse)={zindex(verse)}")
            press_win_d()
            time.sleep(3)
            expect("explorer slot: after Win+D twice the verse is back on the desktop layer",
                   check_placement(verse, find_desktop_host())[0], warn_only=True)
            log_text = (appdata / "log.txt").read_text(encoding="utf-8", errors="replace")
            expect("explorer slot: the desktop layer never had to pause corrections",
                   "pausing corrections" not in log_text)
    finally:
        close_windows(explorer_windows())
        end_app(proc, appdata, "explorer slot: the edit-mode run quits cleanly")
        set_slot(appdata, enabled=False)

    # ---- fractional scaling: the same code path as a 150 % display (QT_SCALE_FACTOR) ---------
    # Settings are logical pixels; Windows moves windows in native pixels. With these odd numbers
    # every value ends in .5 after scaling, so wrong rounding would show (154,92,908,594 or
    # 155,92,909,594 instead of 155,92,910,595).
    set_slot(appdata, enabled=True, x=103, y=61, width=503, height=335)
    expected = (155, 92, 910, 595)
    exit_file(appdata).unlink(missing_ok=True)
    proc = subprocess.Popen([str(exe), "--edit-mode", "--exit-file", str(exit_file(appdata)), "--exit-after", "200"],
                            env=dict(os.environ, QT_SCALE_FACTOR="1.5"))
    try:
        frame = find_window(SLOT_FRAME_TITLE, 60)
        if expect("explorer slot (150 %): the frame appears", bool(frame)):
            time.sleep(3)
            expect("explorer slot (150 %): Qt puts the frame at the scaled place", api.window_rect(frame) == expected,
                   f"frame {api.window_rect(frame)}, expected {expected}")
            before_log = len(slot_log(appdata))
            w9 = open_folder(folders[1])
            expect_placed("explorer slot (150 %): a new Explorer window covers exactly the frame", w9, expected)
            expect("explorer slot (150 %): ...within one pixel", bool(w9) and near(seen_rect(w9), api.window_rect(frame), 1),
                   f"window {seen_rect(w9) if w9 else None}, frame {api.window_rect(frame)}")
            print_slot_log(appdata, before_log)
            close_windows([w9])
    finally:
        close_windows(explorer_windows())
        end_app(proc, appdata, "explorer slot (150 %): the app quits cleanly")
        set_slot(appdata, enabled=False)


SHOW_DESKTOP_WINDOW = "VerseDesk CI show-desktop window"


def check_show_desktop_log(exe: Path, appdata: Path, report: Path) -> None:  # noqa: ARG001
    """What log.txt says when Show desktop switches on and off. On a user's PC every click on
    the desktop once minimised all windows until the reboot; these lines are what will tell
    the cause next time, so they must work on a real desktop."""
    log_path = appdata / "log.txt"

    def lines() -> list[str]:
        try:
            return log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []

    start = len(lines())
    proc = start_app(exe, appdata)
    win = None
    try:
        if not expect("show desktop log: the app starts", bool(find_window(VERSE_TITLE, 60))):
            return
        time.sleep(3)
        minimize_consoles()
        win = subprocess.Popen([sys.executable, "-c", (
            "import tkinter as tk; r = tk.Tk(); r.title(%r); r.geometry('420x260+300+200'); "
            "r.after(150000, r.destroy); r.mainloop()") % SHOW_DESKTOP_WINDOW])
        w = find_window(SHOW_DESKTOP_WINDOW, 30)
        if not expect("show desktop log: an app window is open", bool(w)):
            return
        user32.SetForegroundWindow(w)
        time.sleep(2)
        press_win_d()
        time.sleep(3)
        took = bool(api.IsIconic(w)) or 0 <= zindex(find_desktop_host()) < zindex(w)
        if not expect("show desktop log: Win+D took effect on this machine", took,
                      f"iconic={bool(api.IsIconic(w))}", warn_only=True):
            return  # (the shell ignored the synthetic Win+D: nothing to check, not the app's fault)
        raised = [ln for ln in lines()[start:] if "desktop raised (Show desktop)" in ln]
        up = raised[-1] if raised else ""
        expect("show desktop log: Win+D is logged with the minimised windows, foreground, cursor and keys",
               bool(re.search(r"app windows: \d+ minimised", up)) and "foreground 0x" in up
               and "cursor (" in up and "held " in up and "foreground changes in the last" in up,
               up[-500:] or "no line")
        press_win_d()
        time.sleep(3)
        if not expect("show desktop log: Win+D toggled back on this machine", not api.IsIconic(w),
                      f"test window minimised={bool(api.IsIconic(w))}", warn_only=True):
            return
        normal = [ln for ln in lines()[start:] if "desktop back to normal" in ln]
        down = normal[-1] if normal else ""
        # the window Win+D minimised is counted as minimised, and above the desktop on the way back
        # (the runner's own console windows were minimised before and stay so)
        m_up = re.search(r"app windows: (\d+) minimised", up)
        m_down = re.search(r"app windows: (\d+) minimised, \d+ covered by the desktop, (\d+) above it", down)
        expect("show desktop log: ...the way back is logged too, and the window Win+D minimised is counted",
               bool(m_up and m_down) and int(m_up[1]) > int(m_down[1]) and int(m_down[2]) >= 1,
               f"raised: {up[-260:]} | normal: {down[-260:]}")
        expect("show desktop log: log lines carry milliseconds",
               bool(re.match(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} ", down)), down[:40])

        # Show desktop on and off again and again within seconds (the user's PC after resume)
        before = len(lines())
        for _ in range(5):
            press_win_d()
            time.sleep(1.2)
            press_win_d()
            time.sleep(1.2)
        time.sleep(2)
        new = lines()[before:]
        cycles = sum("desktop raised (Show desktop)" in ln for ln in new)
        expect("show desktop log: switching on again and again is noticed, with the window list",
               any("Show desktop switched on 4 times" in ln for ln in new), f"{cycles} raise(s) logged")
        expect("show desktop log: ...and the user is told what helps",
               any("told the user how to stop Show desktop" in ln for ln in new))
        expect("show desktop log: ...only once",
               sum("Show desktop switched on 4 times" in ln for ln in new) == 1, f"{cycles} raise(s) logged")
        screenshot(report, "10-show-desktop-hint")
    finally:
        if win is not None:
            win.kill()
        end_app(proc, appdata, "show desktop log: the app quits cleanly")


def kill_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)


def explorer_running() -> bool:
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq explorer.exe", "/NH"], capture_output=True, text=True)
    return "explorer.exe" in r.stdout.lower()


def reg_run_value() -> str | None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
            return winreg.QueryValueEx(k, "VerseDesk")[0]
    except FileNotFoundError:
        return None


def reg_run_delete() -> None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                            winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, "VerseDesk")
    except FileNotFoundError:
        pass


# ----------------------------------------------------------------------------- the checks


def check_widget(verse: int, label: str) -> None:
    host = find_desktop_host()
    ex = api.ex_style(verse)
    owner = api.h(api.GetWindow(verse, api.GW_OWNER))
    print(f"  verse {api.describe(verse)} ex={flags_text(ex)} owner={api.describe(owner)}", flush=True)
    expect(f"{label}: tool window (hidden from taskbar and Alt+Tab)",
           bool(ex & api.WS_EX_TOOLWINDOW) and not ex & api.WS_EX_APPWINDOW, flags_text(ex))
    expect(f"{label}: never activates (WS_EX_NOACTIVATE)", bool(ex & api.WS_EX_NOACTIVATE), flags_text(ex))
    expect(f"{label}: click-through (LAYERED+TRANSPARENT)",
           bool(ex & api.WS_EX_LAYERED) and bool(ex & api.WS_EX_TRANSPARENT), flags_text(ex))
    expect(f"{label}: not topmost", not ex & api.WS_EX_TOPMOST, flags_text(ex))
    expect(f"{label}: visible", bool(api.IsWindowVisible(verse)))
    expect(f"{label}: not owned by Explorer's windows (no input coupling)", owner == 0,
           f"owner={api.describe(owner)}")
    ok, blocker = check_placement(verse, host)
    expect(f"{label}: sits directly above the desktop", ok,
           f"blocker={api.describe(blocker)}" if blocker else ("host above verse" if not ok else ""))
    check_click_through(verse, label)


def uncovered_points(verse: int, step: int = 3) -> list[tuple[int, int]]:
    """Points of the verse (on a grid) that no visible window above it covers."""
    order = top_level_windows()
    if verse not in order:
        return []
    covers = [api.window_rect(w) for w in order[: order.index(verse)]
              if api.IsWindowVisible(w) and not api.IsIconic(w) and not api.is_cloaked(w)]
    l, t, r, b = api.window_rect(verse)
    return [(x, y) for y in range(t + 1, b - 1, step) for x in range(l + 1, r - 1, step)
            if not any(cl <= x < cr and ct <= y < cb for cl, ct, cr, cb in covers)]


def root_at(x: int, y: int) -> int:
    under = api.h(user32.WindowFromPoint(wintypes.POINT(x, y)))
    return api.h(user32.GetAncestor(under, api.GA_ROOT)) if under else 0


def painted_points(verse: int, points: list[tuple[int, int]], background: tuple[int, int, int]) -> list[tuple[int, int]]:
    """The sampled points where the verse actually draws (text, outline, shadow): a layered
    window lets clicks through its fully transparent pixels even without WS_EX_TRANSPARENT,
    so only painted pixels can show whether click-through works."""
    try:
        from PIL import ImageGrab

        l, t, r, b = api.window_rect(verse)
        img = ImageGrab.grab(bbox=(l, t, r, b), all_screens=True).convert("RGB")
    except Exception as e:
        print(f"  could not capture the verse: {e}", flush=True)
        return []
    out = []
    for x, y in points:
        px = img.getpixel((x - l, y - t))
        if max(abs(px[i] - background[i]) for i in range(3)) > 60:
            out.append((x, y))
    return out


def check_click_through(verse: int, label: str, background: tuple[int, int, int] | None = None,
                        appdata: Path | None = None) -> None:
    """A click on the verse must reach the window *below* it.

    Every uncovered grid point is hit-tested: any hit on the verse is a FAIL.  When the
    desktop colour behind the verse is known (``background``), the test is made decisive:
    it needs painted pixels among the samples, and a control run with WS_EX_TRANSPARENT
    briefly removed must hit the verse at those pixels (so the test can fail at all).
    """
    name = f"{label}: clicks on the verse reach the window behind it"
    points = uncovered_points(verse)
    if not points:
        record(name, "SKIP", "every part of the verse is covered by another window here")
        return
    order = top_level_windows()
    my_z = order.index(verse) if verse in order else -1
    roots = {pt: root_at(*pt) for pt in points}
    on_verse = [pt for pt, root in roots.items() if root == verse]
    below = [pt for pt, root in roots.items() if root and root in order and order.index(root) > my_z]
    detail = f"{len(points)} points sampled, {len(on_verse)} hit the verse, {len(below)} reached a window below"
    if on_verse:
        record(name, "FAIL", f"{detail}; e.g. {on_verse[0]}")
        return
    if background is None:
        record(name, "PASS" if below else "WARN", detail if below else "inconclusive: " + detail)
        return
    painted = painted_points(verse, points, background)
    painted_below = [pt for pt in painted if pt in below]
    detail += f"; {len(painted)} of them on drawn text/shadow, {len(painted_below)} of those reached a window below"
    if not painted_below:
        record(name, "WARN", "inconclusive (no drawn pixel sampled): " + detail)
        return
    if appdata is not None:
        # Real mouse clicks on drawn text: the app logs any click that reaches the verse.
        before = stray_clicks_logged(appdata)
        targets = painted_below[len(painted_below) // 3 :: max(1, len(painted_below) // 4)][:3]
        for pt in targets:
            click(*pt)
            time.sleep(0.4)
        time.sleep(0.8)
        caught = stray_clicks_logged(appdata) - before
        expect(f"{label}: real mouse clicks on the verse's text go through to the desktop", caught == 0,
               f"{len(targets)} clicks at {targets}; the app saw {caught}")
    # Control: without WS_EX_TRANSPARENT the drawn pixels must be hit, or the test proves nothing.
    # The app re-applies its styles on every keeper tick (150 ms while the desktop is shown),
    # so sample right after removing the flag and retry if the app put it back mid-sample.
    ex = api.ex_style(verse)
    sample = painted_below[:: max(1, len(painted_below) // 60)]
    hits, valid, healed = 0, False, None
    try:
        for _attempt in range(8):
            api.SetWindowLongPtrW(verse, api.GWL_EXSTYLE, ex & ~api.WS_EX_TRANSPARENT)
            if api.ex_style(verse) & api.WS_EX_TRANSPARENT:
                continue  # could not change it (or it was restored at once)
            hits = sum(1 for pt in sample if root_at(*pt) == verse)
            if not api.ex_style(verse) & api.WS_EX_TRANSPARENT:
                valid = True  # the flag stayed off during the whole sample
                break
        # Leave it off: the app must restore click-through by itself within a tick or two.
        api.SetWindowLongPtrW(verse, api.GWL_EXSTYLE, ex & ~api.WS_EX_TRANSPARENT)
        time.sleep(1.0)
        healed = bool(api.ex_style(verse) & api.WS_EX_TRANSPARENT)
    finally:
        if not api.ex_style(verse) & api.WS_EX_TRANSPARENT:
            api.SetWindowLongPtrW(verse, api.GWL_EXSTYLE, ex)
    expect("the app restores click-through if another program removes it", bool(healed),
           "WS_EX_TRANSPARENT back within 1 s" if healed else "still missing after 1 s", warn_only=True)
    detail += (f"; control with WS_EX_TRANSPARENT removed: {hits} of {len(sample)} drawn points hit the verse"
               if valid else "; control could not be run (the style did not stay off)")
    if valid and hits:
        record(name, "PASS", detail)
    else:
        record(name, "WARN", "inconclusive: " + detail)


def run(exe: Path, report: Path) -> None:
    appdata = Path(os.environ["APPDATA"]) / "VerseDesk"
    shutil.rmtree(appdata, ignore_errors=True)
    reg_run_delete()
    print("environment:\n" + describe_desktop(), flush=True)
    expect("explorer.exe is running on the CI desktop", explorer_running(), warn_only=True)
    set_desktop_color((255, 255, 255))  # worst case for white text
    time.sleep(1)
    screenshot(report, "00-before")

    procs: list[subprocess.Popen] = []
    test_win = None
    try:
        app = subprocess.Popen([str(exe)])
        procs.append(app)
        verse = find_window(VERSE_TITLE, 60)
        if not expect("verse window appears", bool(verse), f"after starting {exe.name}"):
            return
        time.sleep(4)
        screenshot(report, "01-started")
        check_widget(verse, "start")
        check_resources()

        # Normal state with nothing over the verse (the way a user sees it): the runner's own
        # console windows cover it, so minimise them, and keep one small app window open away
        # from the verse (with no app window at all the desktop counts as "shown").
        n = minimize_consoles()
        keeper = subprocess.Popen([sys.executable, "-c", (
            "import tkinter as tk; r = tk.Tk(); r.title('VerseDesk CI keeper'); "
            "r.geometry('320x150+20+560'); r.after(240000, r.destroy); r.mainloop()")])
        procs.append(keeper)
        find_window("VerseDesk CI keeper", 30)
        time.sleep(2.5)
        print(f"  minimised {n} console window(s)", flush=True)
        screenshot(report, "01b-normal-state-uncovered")
        ex = api.ex_style(verse)
        expect("normal state: the verse is in its normal place (not lifted)", not ex & api.WS_EX_TOPMOST
               and check_placement(verse, find_desktop_host())[0], flags_text(ex))
        check_click_through(verse, "normal state", background=WHITE_DESKTOP, appdata=appdata)
        keeper.kill()
        time.sleep(1)

        # A normal application window on top of the verse must stay on top of it.
        l, t, r, b = api.window_rect(verse)
        geo = f"{max(200, r - l + 80)}x{max(150, b - t + 80)}+{l - 40}+{t - 40}"
        test_win = subprocess.Popen([sys.executable, "-c", (
            "import tkinter as tk; r = tk.Tk(); r.title(%r); r.geometry(%r); "
            "tk.Label(r, text='normal app window', font=('Segoe UI', 20)).pack(expand=True); "
            "r.after(240000, r.destroy); r.mainloop()") % (TEST_TITLE, geo)])
        tw = find_window(TEST_TITLE, 30)
        if expect("test application window appears", bool(tw)):
            user32.SetForegroundWindow(tw)
            time.sleep(2.5)
            expect("normal window stays above the verse", zindex(tw) < zindex(verse),
                   f"z(test)={zindex(tw)} z(verse)={zindex(verse)}")
            expect("verse still directly above the desktop under other windows", check_placement(verse, find_desktop_host())[0])
            screenshot(report, "02-app-window-on-top")

            # Another program asks Windows to bring the verse to the top: the veto must hold.
            user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                            ctypes.c_int, ctypes.c_int, wintypes.UINT]
            user32.SetWindowPos.restype = wintypes.BOOL
            user32.SetWindowPos(verse, None, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)  # HWND_TOP, no activate
            time.sleep(0.2)
            expect("raise attempt by another program is vetoed", zindex(tw) < zindex(verse),
                   f"z(test)={zindex(tw)} z(verse)={zindex(verse)}")
            time.sleep(1.5)
            expect("after the raise attempt the verse is back under the app window", zindex(tw) < zindex(verse)
                   and check_placement(verse, find_desktop_host())[0], f"z(test)={zindex(tw)} z(verse)={zindex(verse)}")

            # Win+D: the desktop comes forward; the verse must stay visible.
            press_win_d()
            time.sleep(3)
            host = find_desktop_host()
            fg = api.h(api.GetForegroundWindow())
            print(f"  after Win+D: foreground={api.describe(fg)}\n" + describe_desktop(), flush=True)
            screenshot(report, "03-after-win-d")
            # the verse is now in front of the (plain-coloured) desktop: show how it renders
            print_crop("verse-on-white", verse)
            set_desktop_color(DARK_DESKTOP)
            time.sleep(1.5)
            print_crop("verse-on-dark", verse)
            desktop_came_forward = (zindex(host) >= 0 and zindex(host) < zindex(tw)) or bool(api.IsIconic(tw))
            if expect("Win+D took effect on this machine", desktop_came_forward,
                      f"z(host)={zindex(host)} z(test)={zindex(tw)} iconic={bool(api.IsIconic(tw))}", warn_only=True):
                expect("after Win+D the verse is above the desktop", zindex(verse) < zindex(host),
                       f"z(verse)={zindex(verse)} z(host)={zindex(host)}")
                expect("after Win+D the verse is not covered", visible_on_top_at(verse, [host, tw]))
                # nothing covers the verse now and the desktop behind it is plain dark blue, so
                # this hit test (with its control) really decides click-through
                check_click_through(verse, "after Win+D", background=DARK_DESKTOP, appdata=appdata)
                press_win_d()
                time.sleep(3)
                screenshot(report, "04-after-second-win-d")
                if expect("second Win+D brings the normal window back above the verse",
                          zindex(tw) < zindex(verse) and not api.IsIconic(tw),
                          f"z(test)={zindex(tw)} z(verse)={zindex(verse)}", warn_only=True):
                    check_widget(verse, "after Win+D twice")
                else:  # the desktop may still be shown: then the verse is rightly lifted
                    expect("verse still above the shown desktop", zindex(verse) < zindex(find_desktop_host()),
                           f"z(verse)={zindex(verse)} z(host)={zindex(find_desktop_host())}", warn_only=True)

        # explorer.exe restart: the verse must re-attach to the new desktop window.
        if explorer_running():
            old_host = find_desktop_host()
            subprocess.run(["taskkill", "/F", "/IM", "explorer.exe"], capture_output=True)
            time.sleep(3)
            subprocess.Popen(["explorer.exe"])
            new_host = 0
            end = time.time() + 45
            while time.time() < end:
                new_host = find_desktop_host()
                if new_host and new_host != old_host:
                    break
                time.sleep(0.5)
            time.sleep(5)
            screenshot(report, "05-after-explorer-restart")
            if expect("explorer restarted with a new desktop window", bool(new_host) and new_host != old_host,
                      f"old=0x{old_host:X} new=0x{new_host:X}", warn_only=True):
                expect("app still running after explorer restart", app.poll() is None)
                verse2 = find_window(VERSE_TITLE, 10)
                expect("verse window survived explorer restart", bool(verse2) and verse2 == verse,
                       f"0x{verse:X} -> 0x{verse2:X}")
                if verse2:
                    check_widget(verse2, "after explorer restart")
                    verse = verse2

        # Single instance.
        second = subprocess.run([str(exe), "--no-duplicate-dialog"], timeout=90)
        expect("second launch exits at once (single instance)", second.returncode == 3, f"exit code {second.returncode}")
        expect("first instance still running", app.poll() is None)

        # Autostart and files.
        run_value = reg_run_value()
        expect("autostart registered in HKCU Run on first run", run_value == f'"{exe.resolve()}"', repr(run_value))
        expect("settings.json created", (appdata / "settings.json").exists())
        expect("log.txt created", (appdata / "log.txt").exists())
    finally:
        if test_win is not None:
            test_win.kill()
        for p in procs:
            kill_tree(p.pid)
        if not explorer_running():
            subprocess.Popen(["explorer.exe"])
        time.sleep(2)

    # Clean exit path (the same code the tray's 종료 uses).
    clean = subprocess.run([str(exe), "--exit-after", "6"], timeout=120)
    expect("--exit-after quits cleanly with exit code 0", clean.returncode == 0, f"exit code {clean.returncode}")

    # 배치 편집 (edit mode): drag, save, restore after a restart.
    check_edit_mode(exe, appdata, report)

    # 폴더 구역 (folder zones).
    check_zones(exe, appdata, report)

    # 말씀 목록 편집 (verse list editor).
    check_verse_editor(exe, appdata, report)

    # 탐색기 창 자리 고정 (Explorer window slot).
    check_explorer_slot(exe, appdata, report)

    # What log.txt says about Show desktop (the user's "every click on the desktop minimises
    # all windows" report): the lines that will tell the cause next time.
    check_show_desktop_log(exe, appdata, report)

    log = appdata / "log.txt"
    if log.exists():
        text = log.read_text(encoding="utf-8", errors="replace")
        shutil.copy(log, report / "log.txt")
        bad = [ln for ln in text.splitlines() if " ERROR " in ln or "Traceback" in ln or " CRITICAL " in ln]
        expect("no errors in log.txt", not bad, "; ".join(bad[:5]))
    for extra in ("settings.json", "crash.txt"):
        if (appdata / extra).exists():
            shutil.copy(appdata / extra, report / extra)
    reg_run_delete()


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("exe", type=Path)
    ap.add_argument("--report", type=Path, default=Path("ci-report"))
    args = ap.parse_args()
    args.report.mkdir(parents=True, exist_ok=True)
    try:
        run(args.exe.resolve(), args.report)
    except Exception:
        record("checker crashed", "FAIL", traceback.format_exc())
    (args.report / "results.json").write_text(json.dumps(RESULTS, indent=2), encoding="utf-8")
    lines = ["# VerseDesk desktop check", ""] + [
        f"- **{r['status']}** {r['check']}" + (f" — `{r['detail']}`" if r["detail"] else "") for r in RESULTS
    ]
    (args.report / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    failed = [r for r in RESULTS if r["status"] == "FAIL"]
    count = {k: sum(r["status"] == k for r in RESULTS) for k in ("WARN", "SKIP")}
    print(f"\n{len(RESULTS)} checks, {len(failed)} failed, {count['WARN']} warnings, {count['SKIP']} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
