"""Minimal, correctly-typed ctypes bindings for the Win32 calls VerseDesk uses.

Every function gets explicit argtypes/restype: on 64-bit Windows the ctypes default
(C int) would truncate HWNDs and LONG_PTRs.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
try:
    dwmapi = ctypes.WinDLL("dwmapi")
except OSError:  # pragma: no cover - dwmapi exists on every supported Windows
    dwmapi = None

HWND = wintypes.HWND
LONG_PTR = ctypes.c_ssize_t
HWINEVENTHOOK = wintypes.HANDLE

# --- constants -----------------------------------------------------------------------
GWL_STYLE = -16
GWL_EXSTYLE = -20
GWLP_HWNDPARENT = -8

WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
WS_EX_NOREDIRECTIONBITMAP = 0x00200000  # set on Progman by the Windows 11 24H2+ desktop layout

GW_HWNDFIRST = 0
GW_HWNDLAST = 1
GW_HWNDNEXT = 2
GW_HWNDPREV = 3
GW_OWNER = 4

GA_PARENT = 1
GA_ROOT = 2

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_NOOWNERZORDER = 0x0200
SWP_NOSENDCHANGING = 0x0400  # our own z-order moves bypass WM_WINDOWPOSCHANGING (and our veto)

HWND_TOP = 0
HWND_BOTTOM = 1
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2

WM_WINDOWPOSCHANGING = 0x0046

EVENT_SYSTEM_FOREGROUND = 0x0003
EVENT_SYSTEM_MINIMIZEEND = 0x0017
WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002

DWMWA_EXCLUDED_FROM_PEEK = 12
DWMWA_CLOAKED = 14

ASFW_ANY = 0xFFFFFFFF

# --- prototypes ----------------------------------------------------------------------
WINEVENTPROC = ctypes.WINFUNCTYPE(
    None,
    HWINEVENTHOOK,
    wintypes.DWORD,
    HWND,
    wintypes.LONG,
    wintypes.LONG,
    wintypes.DWORD,
    wintypes.DWORD,
)
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, HWND, wintypes.LPARAM)


class WINDOWPOS(ctypes.Structure):
    _fields_ = [
        ("hwnd", HWND),
        ("hwndInsertAfter", HWND),
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("cx", ctypes.c_int),
        ("cy", ctypes.c_int),
        ("flags", wintypes.UINT),
    ]


def _proto(fn, restype, *argtypes):
    fn.restype = restype
    fn.argtypes = list(argtypes)
    return fn


FindWindowW = _proto(user32.FindWindowW, HWND, wintypes.LPCWSTR, wintypes.LPCWSTR)
FindWindowExW = _proto(user32.FindWindowExW, HWND, HWND, HWND, wintypes.LPCWSTR, wintypes.LPCWSTR)
GetShellWindow = _proto(user32.GetShellWindow, HWND)
GetDesktopWindow = _proto(user32.GetDesktopWindow, HWND)
GetForegroundWindow = _proto(user32.GetForegroundWindow, HWND)
GetWindow = _proto(user32.GetWindow, HWND, HWND, wintypes.UINT)
GetAncestor = _proto(user32.GetAncestor, HWND, HWND, wintypes.UINT)
GetWindowLongPtrW = _proto(user32.GetWindowLongPtrW, LONG_PTR, HWND, ctypes.c_int)
SetWindowLongPtrW = _proto(user32.SetWindowLongPtrW, LONG_PTR, HWND, ctypes.c_int, LONG_PTR)
SetWindowPos = _proto(
    user32.SetWindowPos,
    wintypes.BOOL,
    HWND,
    HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
)
IsWindow = _proto(user32.IsWindow, wintypes.BOOL, HWND)
IsWindowVisible = _proto(user32.IsWindowVisible, wintypes.BOOL, HWND)
IsIconic = _proto(user32.IsIconic, wintypes.BOOL, HWND)
GetClassNameW = _proto(user32.GetClassNameW, ctypes.c_int, HWND, wintypes.LPWSTR, ctypes.c_int)
GetWindowTextW = _proto(user32.GetWindowTextW, ctypes.c_int, HWND, wintypes.LPWSTR, ctypes.c_int)
GetWindowRect = _proto(user32.GetWindowRect, wintypes.BOOL, HWND, ctypes.POINTER(wintypes.RECT))
GetWindowThreadProcessId = _proto(
    user32.GetWindowThreadProcessId, wintypes.DWORD, HWND, ctypes.POINTER(wintypes.DWORD)
)
SetWinEventHook = _proto(
    user32.SetWinEventHook,
    HWINEVENTHOOK,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HMODULE,
    WINEVENTPROC,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
)
UnhookWinEvent = _proto(user32.UnhookWinEvent, wintypes.BOOL, HWINEVENTHOOK)
AllowSetForegroundWindow = _proto(user32.AllowSetForegroundWindow, wintypes.BOOL, wintypes.DWORD)
GetTopWindow = _proto(user32.GetTopWindow, HWND, HWND)
if dwmapi is not None:
    DwmSetWindowAttribute = _proto(
        dwmapi.DwmSetWindowAttribute,
        ctypes.c_long,
        HWND,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    DwmGetWindowAttribute = _proto(
        dwmapi.DwmGetWindowAttribute,
        ctypes.c_long,
        HWND,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
else:  # pragma: no cover
    DwmGetWindowAttribute = None
    DwmSetWindowAttribute = None


# --- small helpers -------------------------------------------------------------------


def h(value) -> int:
    """Normalise an HWND (None / int / c_void_p) to a plain int (0 for NULL)."""
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    return int(getattr(value, "value", 0) or 0)


def class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    n = GetClassNameW(hwnd, buf, 256)
    return buf.value[:n] if n > 0 else ""


def window_text(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    n = GetWindowTextW(hwnd, buf, 256)
    return buf.value[:n] if n > 0 else ""


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    r = wintypes.RECT()
    if not GetWindowRect(hwnd, ctypes.byref(r)):
        return (0, 0, 0, 0)
    return (r.left, r.top, r.right, r.bottom)


def ex_style(hwnd: int) -> int:
    return GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF


def style(hwnd: int) -> int:
    return GetWindowLongPtrW(hwnd, GWL_STYLE) & 0xFFFFFFFF


def is_cloaked(hwnd: int) -> bool:
    if DwmGetWindowAttribute is None:
        return False
    val = wintypes.DWORD(0)
    hr = DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(val), ctypes.sizeof(val))
    return hr == 0 and val.value != 0


def exclude_from_peek(hwnd: int) -> None:
    """Keep the window visible while the user peeks at the desktop (taskbar corner hover)."""
    if DwmSetWindowAttribute is None:
        return
    val = wintypes.BOOL(True)
    DwmSetWindowAttribute(hwnd, DWMWA_EXCLUDED_FROM_PEEK, ctypes.byref(val), ctypes.sizeof(val))


def is_topmost(hwnd: int) -> bool:
    return bool(ex_style(hwnd) & WS_EX_TOPMOST)


def process_id(hwnd: int) -> int:
    pid = wintypes.DWORD(0)
    GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def describe(hwnd: int) -> str:
    if not hwnd:
        return "NULL"
    try:
        l, t, r, b = window_rect(hwnd)
        return (
            f"0x{hwnd:X} {class_name(hwnd)!r} {window_text(hwnd)[:40]!r} "
            f"vis={bool(IsWindowVisible(hwnd))} rect=({l},{t},{r},{b}) pid={process_id(hwnd)}"
        )
    except Exception as e:  # pragma: no cover - diagnostics must never fail
        return f"0x{hwnd:X} (describe failed: {e})"
