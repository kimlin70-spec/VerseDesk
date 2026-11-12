"""Windows shell helpers for folder zones: the system icon of a path, and opening a path.

Everything here may block (network paths, slow disks), so callers run it on worker
threads.  Each worker thread initialises COM for itself (apartment-threaded, as the shell
expects); the GUI thread is never touched.

Opening a path ("double-click"):
  * ShellExecuteExW with the default verb: folders open in Explorer, files in the
    program associated with them.  Nothing is ever moved, copied or deleted.
  * The started program must not inherit VerseDesk's packaged environment: the PyInstaller
    bootloader called SetDllDirectoryW(_MEIPASS) (inherited by child processes) and the
    PySide6 runtime hook put _MEIPASS on PATH and set QT_PLUGIN_PATH/QML2_IMPORT_PATH, so
    a Qt or MSVC program opened from a zone could load VerseDesk's copies of its DLLs.
    ``clean_launch_environment`` removes all that for the moment of the launch.
  * AllowSetForegroundWindow lets the started program come to the front (our windows
    never activate, so without it the program could open behind other windows).
"""

from __future__ import annotations

import contextlib
import ctypes
import logging
import os
import sys
import threading
from ctypes import wintypes

log = logging.getLogger("versedesk.win32.shell")

shell32 = ctypes.WinDLL("shell32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ole32 = ctypes.WinDLL("ole32", use_last_error=True)

# --- constants ---------------------------------------------------------------------------
SHGFI_ICON = 0x000000100
SHGFI_LARGEICON = 0x000000000
SHGFI_USEFILEATTRIBUTES = 0x000000010
FILE_ATTRIBUTE_DIRECTORY = 0x10
FILE_ATTRIBUTE_NORMAL = 0x80

SEE_MASK_NOASYNC = 0x00000100
SEE_MASK_FLAG_LOG_USAGE = 0x04000000
SW_SHOWNORMAL = 1

COINIT_APARTMENTTHREADED = 0x2
COINIT_DISABLE_OLE1DDE = 0x4

ASFW_ANY = 0xFFFFFFFF
DIB_RGB_COLORS = 0
BI_RGB = 0


class SHFILEINFOW(ctypes.Structure):
    _fields_ = [
        ("hIcon", wintypes.HICON),
        ("iIcon", ctypes.c_int),
        ("dwAttributes", wintypes.DWORD),
        ("szDisplayName", wintypes.WCHAR * 260),
        ("szTypeName", wintypes.WCHAR * 80),
    ]


class SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", wintypes.ULONG),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIconOrMonitor", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


class ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HBITMAP),
        ("hbmColor", wintypes.HBITMAP),
    ]


class BITMAP(ctypes.Structure):
    _fields_ = [
        ("bmType", wintypes.LONG),
        ("bmWidth", wintypes.LONG),
        ("bmHeight", wintypes.LONG),
        ("bmWidthBytes", wintypes.LONG),
        ("bmPlanes", wintypes.WORD),
        ("bmBitsPixel", wintypes.WORD),
        ("bmBits", ctypes.c_void_p),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def _proto(fn, restype, *argtypes):
    fn.restype = restype
    fn.argtypes = list(argtypes)
    return fn


SHGetFileInfoW = _proto(
    shell32.SHGetFileInfoW, ctypes.c_size_t,
    wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(SHFILEINFOW), wintypes.UINT, wintypes.UINT,
)
ShellExecuteExW = _proto(shell32.ShellExecuteExW, wintypes.BOOL, ctypes.POINTER(SHELLEXECUTEINFOW))
DestroyIcon = _proto(user32.DestroyIcon, wintypes.BOOL, wintypes.HICON)
GetIconInfo = _proto(user32.GetIconInfo, wintypes.BOOL, wintypes.HICON, ctypes.POINTER(ICONINFO))
GetDC = _proto(user32.GetDC, wintypes.HDC, wintypes.HWND)
ReleaseDC = _proto(user32.ReleaseDC, ctypes.c_int, wintypes.HWND, wintypes.HDC)
AllowSetForegroundWindow = _proto(user32.AllowSetForegroundWindow, wintypes.BOOL, wintypes.DWORD)
GetObjectW = _proto(gdi32.GetObjectW, ctypes.c_int, wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p)
GetDIBits = _proto(
    gdi32.GetDIBits, ctypes.c_int,
    wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT,
)
DeleteObject = _proto(gdi32.DeleteObject, wintypes.BOOL, wintypes.HANDLE)
SetDllDirectoryW = _proto(kernel32.SetDllDirectoryW, wintypes.BOOL, wintypes.LPCWSTR)
CoInitializeEx = _proto(ole32.CoInitializeEx, ctypes.c_long, ctypes.c_void_p, wintypes.DWORD)
CoUninitialize = _proto(ole32.CoUninitialize, None)


# --- COM per worker thread -------------------------------------------------------------

def init_thread_com() -> bool:
    """Call once at the start of a worker thread. Returns True if CoUninitialize is due."""
    hr = CoInitializeEx(None, COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE)
    return hr >= 0  # S_OK or S_FALSE (already initialised); RPC_E_CHANGED_MODE is negative


def uninit_thread_com() -> None:
    CoUninitialize()


# --- icons -----------------------------------------------------------------------------

def _bitmap_bits(hdc, hbm, width: int, height: int) -> bytes | None:
    """The bitmap as 32-bit top-down BGRA rows."""
    bmi = (ctypes.c_byte * (ctypes.sizeof(BITMAPINFOHEADER) + 16))()
    header = BITMAPINFOHEADER.from_buffer(bmi)
    header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    header.biWidth = width
    header.biHeight = -height  # negative: top-down rows
    header.biPlanes = 1
    header.biBitCount = 32
    header.biCompression = BI_RGB
    buf = (ctypes.c_ubyte * (width * height * 4))()
    lines = GetDIBits(hdc, hbm, 0, height, buf, bmi, DIB_RGB_COLORS)
    if lines != height:
        return None
    return bytes(buf)


def hicon_to_bgra(hicon) -> tuple[int, int, bytes] | None:
    """(width, height, BGRA bytes with straight alpha) of an icon, or None."""
    info = ICONINFO()
    if not GetIconInfo(hicon, ctypes.byref(info)):
        return None
    try:
        bm = BITMAP()
        source = info.hbmColor or info.hbmMask
        if not GetObjectW(source, ctypes.sizeof(BITMAP), ctypes.byref(bm)):
            return None
        width = bm.bmWidth
        height = bm.bmHeight if info.hbmColor else bm.bmHeight // 2  # mask-only icons stack AND+XOR
        if width <= 0 or height <= 0 or width > 512 or height > 512:
            return None
        hdc = GetDC(None)
        try:
            if not info.hbmColor:
                return None  # monochrome icons are not worth the trouble; caller uses a generic one
            color = _bitmap_bits(hdc, info.hbmColor, width, height)
            if color is None:
                return None
            pixels = bytearray(color)
            if not any(pixels[3::4]):
                # an old-style icon without an alpha channel: take transparency from the mask
                mask = _bitmap_bits(hdc, info.hbmMask, width, height) if info.hbmMask else None
                for i in range(0, len(pixels), 4):
                    transparent = mask is not None and mask[i] != 0  # mask bit 1 = transparent
                    pixels[i + 3] = 0 if transparent else 255
            return width, height, bytes(pixels)
        finally:
            ReleaseDC(None, hdc)
    finally:
        if info.hbmColor:
            DeleteObject(info.hbmColor)
        if info.hbmMask:
            DeleteObject(info.hbmMask)


def file_icon_bgra(path: str, exists: bool, is_dir: bool) -> tuple[int, int, bytes] | None:
    """The large system icon Explorer shows for ``path`` (a generic one when it is missing)."""
    sfi = SHFILEINFOW()
    flags = SHGFI_ICON | SHGFI_LARGEICON
    attributes = 0
    if not exists:
        flags |= SHGFI_USEFILEATTRIBUTES  # do not touch the disk: icon by name/extension only
        attributes = FILE_ATTRIBUTE_DIRECTORY if is_dir else FILE_ATTRIBUTE_NORMAL
    if not SHGetFileInfoW(path, attributes, ctypes.byref(sfi), ctypes.sizeof(sfi), flags) or not sfi.hIcon:
        return None
    try:
        return hicon_to_bgra(sfi.hIcon)
    finally:
        DestroyIcon(sfi.hIcon)


# --- launching -------------------------------------------------------------------------

_launch_lock = threading.Lock()
_CLEARED_VARIABLES = ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH")


def _under(path: str, root: str) -> bool:
    try:
        p = os.path.normcase(os.path.abspath(path))
        r = os.path.normcase(os.path.abspath(root))
    except (OSError, ValueError):
        return False
    return p == r or p.startswith(r.rstrip("\\/") + os.sep)


@contextlib.contextmanager
def clean_launch_environment():
    """While inside: no PyInstaller DLL directory, no _MEIPASS on PATH, no Qt plugin
    variables, so a program started now gets a normal environment.  Restored afterwards
    (VerseDesk itself still needs them for Qt plugins it loads later)."""
    meipass = getattr(sys, "_MEIPASS", None)
    with _launch_lock:
        saved = {k: os.environ.get(k) for k in ("PATH",) + _CLEARED_VARIABLES}
        try:
            if meipass:
                SetDllDirectoryW(None)
                parts = (saved["PATH"] or "").split(os.pathsep)
                os.environ["PATH"] = os.pathsep.join(p for p in parts if p and not _under(p, meipass))
            for k in _CLEARED_VARIABLES:
                os.environ.pop(k, None)
            yield
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            if meipass:
                SetDllDirectoryW(meipass)


def allow_foreground() -> None:
    try:
        AllowSetForegroundWindow(ASFW_ANY)
    except Exception:  # never matters enough to fail an open
        pass


def open_path(path: str) -> str | None:
    """Open a folder in Explorer or a file in its program. Returns None or an error text."""
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
    info.fMask = SEE_MASK_NOASYNC | SEE_MASK_FLAG_LOG_USAGE
    info.lpVerb = None  # the default action, exactly what a double-click in Explorer does
    info.lpFile = path
    info.lpDirectory = os.path.dirname(path) or None
    info.nShow = SW_SHOWNORMAL
    allow_foreground()
    with clean_launch_environment():
        ok = ShellExecuteExW(ctypes.byref(info))
        err = ctypes.get_last_error()
    if ok:
        return None
    if err == 1223:  # ERROR_CANCELLED: the user closed an "Open with" dialog
        return None
    return ctypes.FormatError(err).strip() or f"error {err}"
