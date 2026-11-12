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
    verses.json; closing the window leaves the app running.
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


def clear_area(target: int, extra=(DRAG_SOURCE_AREA,)) -> list[str]:
    """Runner desktops pop up stray windows during the run (after the explorer restart a
    'System Properties' and then a 'Performance Options' dialog appeared over the zone).
    Close or minimise every foreign window that overlaps ``target`` or ``extra`` areas,
    repeating until none is left."""
    own = {api.process_id(target), os.getpid()}
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
