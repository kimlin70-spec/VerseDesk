"""A stand-in "File Explorer" window for the desktop check (CI only, Windows only).

VerseDesk recognises Explorer windows by their window class, CabinetWClass.  Window class
names are per process, so this script can register its own class with that name and play
the awkward cases a real Explorer cannot be made to produce on demand:

  hidden    created hidden, shown after --delay seconds   (a window Explorer kept ready)
  cloaked   shown while cloaked, uncloaked after --delay   (the same, done with DWM cloaking)
  slow      shown, then processes no messages for --delay  (a busy or hung Explorer)
  minsize   never smaller than 700x560                     (refuses the size of the slot)
  plain     just a window

It prints "HWND <number>" once the window exists and exits after --life seconds.
"""

from __future__ import annotations

import argparse
import ctypes
import sys
import time
from ctypes import wintypes

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

WS_OVERLAPPEDWINDOW = 0x00CF0000
WM_DESTROY = 0x0002
WM_GETMINMAXINFO = 0x0024
SW_SHOWNOACTIVATE = 4
PM_REMOVE = 1
DWMWA_CLOAK = 13
MIN_SIZE = (700, 560)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HANDLE),
        ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HANDLE),
        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
    ]


class MINMAXINFO(ctypes.Structure):
    _fields_ = [("ptReserved", wintypes.POINT), ("ptMaxSize", wintypes.POINT), ("ptMaxPosition", wintypes.POINT),
                ("ptMinTrackSize", wintypes.POINT), ("ptMaxTrackSize", wintypes.POINT)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", choices=["hidden", "cloaked", "slow", "minsize", "plain"])
    ap.add_argument("--delay", type=float, default=5.0)
    ap.add_argument("--life", type=float, default=40.0)
    ap.add_argument("--rect", default="60,420,420,300", help="x,y,width,height")
    args = ap.parse_args()
    x, y, width, height = (int(v) for v in args.rect.split(","))

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi")
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = LRESULT
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    user32.RegisterClassW.restype = wintypes.ATOM
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = LRESULT
    user32.PostQuitMessage.argtypes = [ctypes.c_int]
    user32.GetSysColorBrush.argtypes = [ctypes.c_int]
    user32.GetSysColorBrush.restype = wintypes.HANDLE
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    dwmapi.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]

    @WNDPROC
    def wndproc(hwnd, message, wparam, lparam):
        if message == WM_GETMINMAXINFO and args.scenario == "minsize" and lparam:
            info = MINMAXINFO.from_address(lparam)
            info.ptMinTrackSize.x, info.ptMinTrackSize.y = MIN_SIZE
            return 0
        if message == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    instance = kernel32.GetModuleHandleW(None)
    cls = WNDCLASSW()
    cls.lpfnWndProc = wndproc
    cls.hInstance = instance
    cls.hbrBackground = user32.GetSysColorBrush(5)  # COLOR_WINDOW
    cls.lpszClassName = "CabinetWClass"
    if not user32.RegisterClassW(ctypes.byref(cls)):
        print(f"RegisterClassW failed: {ctypes.get_last_error()}", flush=True)
        return 1
    if args.scenario == "minsize":
        width, height = max(width, MIN_SIZE[0]), max(height, MIN_SIZE[1])
    hwnd = user32.CreateWindowExW(0, "CabinetWClass", f"VerseDesk CI stand-in ({args.scenario})", WS_OVERLAPPEDWINDOW,
                                  x, y, width, height, None, None, instance, None)
    if not hwnd:
        print(f"CreateWindowExW failed: {ctypes.get_last_error()}", flush=True)
        return 1
    print(f"HWND {hwnd}", flush=True)

    def cloak(on: bool) -> None:
        value = wintypes.BOOL(on)
        dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_CLOAK, ctypes.byref(value), ctypes.sizeof(value))

    def pump(seconds: float) -> bool:
        """Process messages for a while. False once the window was closed."""
        end = time.monotonic() + seconds
        msg = wintypes.MSG()
        while time.monotonic() < end:
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                if msg.message == 0x0012:  # WM_QUIT
                    return False
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            time.sleep(0.01)
        return True

    start = time.monotonic()
    alive = True
    if args.scenario == "hidden":
        alive = pump(args.delay)
        user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        print("SHOWN", flush=True)
    elif args.scenario == "cloaked":
        cloak(True)
        user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        alive = pump(args.delay)
        cloak(False)
        print("UNCLOAKED", flush=True)
    elif args.scenario == "slow":
        user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        alive = pump(0.3)
        print("HUNG", flush=True)
        time.sleep(args.delay)  # no messages are processed: requests from other programs queue up
        print("AWAKE", flush=True)
    else:
        user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
    if alive:
        pump(max(0.0, args.life - (time.monotonic() - start)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
