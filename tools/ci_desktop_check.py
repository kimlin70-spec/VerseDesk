"""Live check of VerseDesk.exe on a real Windows desktop (run by GitHub Actions).

    python tools/ci_desktop_check.py dist/VerseDesk.exe --report ci-report

It starts the exe with a clean profile and verifies, through the Win32 API, the behaviour
the user cannot easily test one by one:
  * the verse window exists, is a tool window (no taskbar/Alt+Tab), never activates,
    is not owned by Explorer and sits directly above the desktop window;
  * click-through: a hit test on a part of the verse no other window covers must land on
    the window *below* it (where every part is covered the test cannot decide: SKIP);
  * a normal application window placed on top of it stays on top;
  * after Win+D (Show desktop) the verse is still visible above the desktop, and the
    normal window is not; Win+D again restores the normal window above the verse;
  * after explorer.exe is killed and restarted, the verse re-attaches to the new desktop;
  * a second launch exits immediately (single instance);
  * autostart (HKCU Run) is registered on first run; settings.json and log.txt exist;
  * `--exit-after` quits cleanly with exit code 0.
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

VK_LWIN, VK_D = 0x5B, 0x44
KEYEVENTF_KEYUP = 0x0002


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


def uncovered_point(verse: int) -> tuple[int, int] | None:
    """A point of the verse that no visible window above it covers, or None if fully covered."""
    order = top_level_windows()
    if verse not in order:
        return None
    covers = []
    for w in order[: order.index(verse)]:
        if api.IsWindowVisible(w) and not api.IsIconic(w) and not api.is_cloaked(w):
            covers.append(api.window_rect(w))
    l, t, r, b = api.window_rect(verse)
    for fy in (0.5, 0.3, 0.7, 0.15, 0.85):
        for fx in (0.5, 0.3, 0.7, 0.15, 0.85, 0.05, 0.95):
            x, y = int(l + (r - l) * fx), int(t + (b - t) * fy)
            if not any(cl <= x < cr and ct <= y < cb for cl, ct, cr, cb in covers):
                return x, y
    return None


def check_click_through(verse: int, label: str) -> None:
    """A click on the verse must reach the window *below* it.  Only meaningful at a point
    no other window covers; otherwise the result says nothing and is reported as SKIP."""
    name = f"{label}: a click on the verse reaches the window behind it"
    p = uncovered_point(verse)
    if p is None:
        record(name, "SKIP", "every part of the verse is covered by another window here")
        return
    under = api.h(user32.WindowFromPoint(wintypes.POINT(*p)))
    root = api.h(user32.GetAncestor(under, api.GA_ROOT)) if under else 0
    detail = f"WindowFromPoint{p} -> {api.describe(under)} (root {api.describe(root)})"
    if root == verse:
        record(name, "FAIL", detail)
    elif root and zindex(root) > zindex(verse):
        record(name, "PASS", detail)
    else:  # something we did not see as covering answered: cannot judge
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
            set_desktop_color((22, 40, 70))
            time.sleep(1.5)
            print_crop("verse-on-dark", verse)
            desktop_came_forward = (zindex(host) >= 0 and zindex(host) < zindex(tw)) or bool(api.IsIconic(tw))
            if expect("Win+D took effect on this machine", desktop_came_forward,
                      f"z(host)={zindex(host)} z(test)={zindex(tw)} iconic={bool(api.IsIconic(tw))}", warn_only=True):
                expect("after Win+D the verse is above the desktop", zindex(verse) < zindex(host),
                       f"z(verse)={zindex(verse)} z(host)={zindex(host)}")
                expect("after Win+D the verse is not covered", visible_on_top_at(verse, [host, tw]))
                # nothing covers the verse now, so this hit test really decides click-through
                check_click_through(verse, "after Win+D")
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
