"""A tiny in-memory model of the Windows window manager, good enough to drive
versedesk/win32/desktop.py on Linux.

It models one z-ordered list of top-level windows (topmost band first), child windows
(for SHELLDLL_DefView), owners, ex-styles, visibility/minimized/cloaked flags and the
SetWindowPos rules the keeper relies on:
  * HWND_TOPMOST / HWND_NOTOPMOST / HWND_TOP within bands,
  * HWND_BOTTOM lands just above the desktop windows that sit at the very bottom
    (Explorer's Progman/WorkerW group) — measured behaviour on real Windows — and at the
    very bottom while the desktop is raised,
  * insert-after keeps a window topmost only when inserted inside the topmost band.
It is exposed as a module-like object so it can replace ``versedesk.win32.api``.
"""

from __future__ import annotations

import ctypes
import types
from ctypes import wintypes
from dataclasses import dataclass, field

C = dict(
    GWL_STYLE=-16, GWL_EXSTYLE=-20, GWLP_HWNDPARENT=-8,
    WS_POPUP=0x80000000, WS_CHILD=0x40000000, WS_VISIBLE=0x10000000, WS_DISABLED=0x08000000,
    WS_EX_TOPMOST=0x8, WS_EX_TRANSPARENT=0x20, WS_EX_TOOLWINDOW=0x80, WS_EX_APPWINDOW=0x40000,
    WS_EX_LAYERED=0x80000, WS_EX_NOACTIVATE=0x08000000, WS_EX_NOREDIRECTIONBITMAP=0x00200000,
    GW_HWNDFIRST=0, GW_HWNDLAST=1, GW_HWNDNEXT=2, GW_HWNDPREV=3, GW_OWNER=4, GA_PARENT=1, GA_ROOT=2,
    SWP_NOSIZE=0x1, SWP_NOMOVE=0x2, SWP_NOZORDER=0x4, SWP_NOACTIVATE=0x10, SWP_NOOWNERZORDER=0x200,
    SWP_NOSENDCHANGING=0x400, HWND_TOP=0, HWND_BOTTOM=1, HWND_TOPMOST=-1, HWND_NOTOPMOST=-2,
    WM_WINDOWPOSCHANGING=0x46, EVENT_SYSTEM_FOREGROUND=3, EVENT_SYSTEM_MINIMIZEEND=0x17,
    WINEVENT_OUTOFCONTEXT=0, WINEVENT_SKIPOWNPROCESS=2, DWMWA_EXCLUDED_FROM_PEEK=12, DWMWA_CLOAKED=14,
    ASFW_ANY=0xFFFFFFFF,
)
DESKTOP = {"Progman", "WorkerW"}
EXPLORER_PID = 4242


class WINDOWPOS(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("hwndInsertAfter", wintypes.HWND), ("x", ctypes.c_int),
                ("y", ctypes.c_int), ("cx", ctypes.c_int), ("cy", ctypes.c_int), ("flags", wintypes.UINT)]


@dataclass
class Win:
    hwnd: int
    cls: str
    title: str = ""
    visible: bool = True
    iconic: bool = False
    cloaked: bool = False
    ex: int = 0
    owner: int = 0
    parent: int = 0  # child windows only
    rect: tuple = (0, 0, 800, 600)
    pid: int = 1000
    children: list = field(default_factory=list)


class FakeWM:
    def __init__(self):
        self.wins: dict[int, Win] = {}
        self.z: list[int] = []  # top-level windows, top first
        self.next_hwnd = 0x1000
        self.shell = 0
        self.foreground = 0
        self.calls: list[tuple] = []
        self.api = self._make_api()

    # ---------------------------------------------------------------- building scenes
    def new(self, cls, *, title="", top=True, child_of=0, **kw) -> int:
        self.next_hwnd += 0x10
        h = self.next_hwnd
        w = Win(h, cls, title, **kw)
        self.wins[h] = w
        if child_of:
            w.parent = child_of
            self.wins[child_of].children.append(h)
        elif top:
            self._insert(h, 0 if not (w.ex & C["WS_EX_TOPMOST"]) else 0)
            self._normalize()
        else:
            self.z.append(h)
        return h

    def adopt(self, hwnd: int, cls="Qt6QWindowToolSaveBits", **kw) -> None:
        """Register a real Qt winId as a top-level window (top of the normal band)."""
        self.wins[hwnd] = Win(hwnd, cls, **kw)
        self.z.insert(self._first_normal_index(), hwnd)

    def explorer_24h2(self) -> int:
        """Windows 11 24H2+: Progman (bottom) holds DefView and a wallpaper WorkerW."""
        prog = self.new("Progman", title="Program Manager", top=False, pid=EXPLORER_PID,
                        rect=(0, 0, 1920, 1080), ex=C["WS_EX_NOREDIRECTIONBITMAP"])
        self.new("SHELLDLL_DefView", child_of=prog, pid=EXPLORER_PID)
        self.new("WorkerW", child_of=prog, pid=EXPLORER_PID)
        self.shell = prog
        return prog

    def explorer_win10(self) -> int:
        """Windows 10: Progman at the bottom holding DefView (not split yet)."""
        prog = self.new("Progman", title="Program Manager", top=False, pid=EXPLORER_PID, rect=(0, 0, 1920, 1080))
        self.new("SHELLDLL_DefView", child_of=prog, pid=EXPLORER_PID)
        self.shell = prog
        return prog

    def taskbar(self) -> int:
        return self.new("Shell_TrayWnd", ex=C["WS_EX_TOPMOST"] | C["WS_EX_TOOLWINDOW"], pid=EXPLORER_PID,
                        rect=(0, 1040, 1920, 1080))

    # ---------------------------------------------------------------- explorer behaviours
    def win_d_24h2(self) -> None:
        for h in list(self.z):
            w = self.wins[h]
            if w.cls not in DESKTOP and w.visible and not w.ex & (C["WS_EX_TOOLWINDOW"] | C["WS_EX_TOPMOST"]):
                w.iconic = True
        self._move(self.shell, self._first_normal_index())
        self.foreground = self.shell

    def win_d_win10(self) -> int:
        """Split the desktop: DefView moves into a new top-level WorkerW, which is raised."""
        prog = self.shell
        dv = next(c for c in self.wins[prog].children if self.wins[c].cls == "SHELLDLL_DefView")
        self.wins[prog].children.remove(dv)
        worker = self.new("WorkerW", top=False, pid=EXPLORER_PID, rect=(0, 0, 1920, 1080))
        self.wins[worker].children.append(dv)
        self.wins[dv].parent = worker
        self.new("WorkerW", top=False, pid=EXPLORER_PID, rect=(0, 0, 1920, 1080))  # wallpaper
        self.z.remove(prog)
        self.z.append(prog)
        for h in list(self.z):
            w = self.wins[h]
            if w.cls not in DESKTOP and w.visible and not w.ex & (C["WS_EX_TOOLWINDOW"] | C["WS_EX_TOPMOST"]):
                w.iconic = True
        self._move(worker, self._first_normal_index())
        self.foreground = worker
        return worker

    def restore_app(self, app: int, desktop_window: int) -> None:
        """Clicking an app on the taskbar: the desktop drops to the bottom, the app comes back on top."""
        for w in self.wins.values():
            w.iconic = False
        self.z.remove(desktop_window)
        bottom_group = [h for h in self.z if self.wins[h].cls in DESKTOP]
        idx = self.z.index(bottom_group[0]) if bottom_group else len(self.z)
        self.z.insert(idx, desktop_window)
        self._move(app, self._first_normal_index())
        self.foreground = app

    def restart_explorer(self) -> int:
        for h in [h for h in self.z if self.wins[h].pid == EXPLORER_PID]:
            self.destroy(h)
        return self.explorer_24h2()

    def destroy(self, h: int) -> None:
        w = self.wins.pop(h, None)
        if w is None:
            return
        for c in list(w.children):
            self.wins.pop(c, None)
        if h in self.z:
            self.z.remove(h)
        for other in self.wins.values():  # owned windows of other threads become unowned
            if other.owner == h:
                other.owner = 0
        if self.shell == h:
            self.shell = 0

    # ---------------------------------------------------------------- z-order mechanics
    def _top(self, h):
        return bool(self.wins[h].ex & C["WS_EX_TOPMOST"])

    def _first_normal_index(self) -> int:
        for i, h in enumerate(self.z):
            if not self._top(h):
                return i
        return len(self.z)

    def _insert(self, h, idx):
        if h in self.z:
            self.z.remove(h)
        self.z.insert(idx, h)

    def _move(self, h, idx):
        if h in self.z:
            old = self.z.index(h)
            self.z.remove(h)
            if old < idx:
                idx -= 1
        self.z.insert(idx, h)

    def _normalize(self):
        top = [h for h in self.z if self._top(h)]
        rest = [h for h in self.z if not self._top(h)]
        self.z = top + rest

    def set_window_pos(self, h, after, flags):
        self.calls.append(("SetWindowPos", h, after, flags))
        if h not in self.wins or h not in self.z or flags & C["SWP_NOZORDER"]:
            return True
        w = self.wins[h]
        after = after or 0
        if after in (-1, 0xFFFFFFFFFFFFFFFF):  # HWND_TOPMOST
            w.ex |= C["WS_EX_TOPMOST"]
            self._move(h, 0)
        elif after in (-2, 0xFFFFFFFFFFFFFFFE):  # HWND_NOTOPMOST
            w.ex &= ~C["WS_EX_TOPMOST"]
            self.z.remove(h)
            self.z.insert(self._first_normal_index(), h)
        elif after == 0:  # HWND_TOP
            self.z.remove(h)
            self.z.insert(0 if self._top(h) else self._first_normal_index(), h)
        elif after == 1:  # HWND_BOTTOM
            w.ex &= ~C["WS_EX_TOPMOST"]
            self.z.remove(h)
            i = len(self.z)
            while i > 0 and self.wins[self.z[i - 1]].cls in DESKTOP and self.wins[self.z[i - 1]].pid == EXPLORER_PID:
                i -= 1
            self.z.insert(i, h)
        else:
            if after not in self.z:
                return False
            self.z.remove(h)
            idx = self.z.index(after) + 1
            nxt = self.z[idx] if idx < len(self.z) else 0
            if self._top(after) and (self._top(h) or (nxt and self._top(nxt))):
                w.ex |= C["WS_EX_TOPMOST"]
            else:
                w.ex &= ~C["WS_EX_TOPMOST"]
            self.z.insert(idx, h)
        self._normalize()
        return True

    # ---------------------------------------------------------------- the api module
    def _make_api(self):
        wm = self
        m = types.SimpleNamespace(**C)
        m.ctypes = ctypes
        m.wintypes = wintypes
        m.WINDOWPOS = WINDOWPOS
        m.WINEVENTPROC = lambda fn: fn
        m.WNDENUMPROC = lambda fn: fn

        def h(v):
            if v is None:
                return 0
            return v if isinstance(v, int) else int(getattr(v, "value", 0) or 0)

        def norm(v):
            v = h(v)
            return v - (1 << 64) if v >= (1 << 63) else v

        m.h = h
        m.FindWindowW = lambda cls, title: next((x for x in wm.z if wm.wins[x].cls == cls), 0)

        def find_window_ex(parent, after, cls, title):
            parent, after = h(parent), h(after)
            seq = wm.wins[parent].children if parent else wm.z
            start = seq.index(after) + 1 if after in seq else (0 if not after else len(seq))
            for x in seq[start:]:
                w = wm.wins[x]
                if (cls is None or w.cls.lower() == cls.lower()) and (title is None or w.title == title):
                    return x
            return 0

        m.FindWindowExW = find_window_ex
        m.GetShellWindow = lambda: wm.shell
        m.GetDesktopWindow = lambda: 1
        m.GetForegroundWindow = lambda: wm.foreground

        def get_window(x, cmd):
            x = h(x)
            if cmd == C["GW_OWNER"]:
                return wm.wins[x].owner if x in wm.wins else 0
            if x not in wm.z:
                return 0
            i = wm.z.index(x)
            if cmd == C["GW_HWNDNEXT"]:
                return wm.z[i + 1] if i + 1 < len(wm.z) else 0
            if cmd == C["GW_HWNDPREV"]:
                return wm.z[i - 1] if i > 0 else 0
            return 0

        m.GetWindow = get_window
        m.GetTopWindow = lambda parent: wm.z[0] if wm.z else 0
        m.GetAncestor = lambda x, flag: wm.wins[h(x)].parent if h(x) in wm.wins else 0

        def get_long(x, idx):
            w = wm.wins.get(h(x))
            if w is None:
                return 0
            return w.ex if idx == C["GWL_EXSTYLE"] else 0

        def set_long(x, idx, val):
            w = wm.wins.get(h(x))
            if w is None:
                return 0
            wm.calls.append(("SetWindowLongPtrW", h(x), idx, val))
            if idx == C["GWL_EXSTYLE"]:
                old, w.ex = w.ex, val & 0xFFFFFFFF
                return old
            if idx == C["GWLP_HWNDPARENT"]:
                old, w.owner = w.owner, h(val)
                return old
            return 0

        m.GetWindowLongPtrW = get_long
        m.SetWindowLongPtrW = set_long
        m.SetWindowPos = lambda x, after, X, Y, cx, cy, flags: wm.set_window_pos(h(x), norm(after), flags)
        m.IsWindow = lambda x: h(x) in wm.wins
        m.IsWindowVisible = lambda x: h(x) in wm.wins and wm.wins[h(x)].visible
        m.IsIconic = lambda x: h(x) in wm.wins and wm.wins[h(x)].iconic
        m.class_name = lambda x: wm.wins[h(x)].cls if h(x) in wm.wins else ""
        m.window_text = lambda x: wm.wins[h(x)].title if h(x) in wm.wins else ""
        m.window_rect = lambda x: wm.wins[h(x)].rect if h(x) in wm.wins else (0, 0, 0, 0)
        m.ex_style = lambda x: wm.wins[h(x)].ex if h(x) in wm.wins else 0
        m.style = lambda x: 0
        m.is_cloaked = lambda x: h(x) in wm.wins and wm.wins[h(x)].cloaked
        m.is_topmost = lambda x: h(x) in wm.wins and bool(wm.wins[h(x)].ex & C["WS_EX_TOPMOST"])
        m.process_id = lambda x: wm.wins[h(x)].pid if h(x) in wm.wins else 0
        m.exclude_from_peek = lambda x: wm.calls.append(("exclude_from_peek", h(x)))
        m.describe = lambda x: (f"0x{h(x):X} {wm.wins[h(x)].cls}" if h(x) in wm.wins else f"0x{h(x):X}?")
        m.SetWinEventHook = lambda *a: 1
        m.UnhookWinEvent = lambda hook: True
        m.GetModuleHandleW = lambda name: 0

        def create_window(ex, cls, title, style, x, y, cx, cy, parent, menu, inst, param):
            wm.next_hwnd += 0x10
            hh = wm.next_hwnd
            wm.wins[hh] = Win(hh, cls, title, visible=bool(style & C["WS_VISIBLE"]), ex=ex, rect=(0, 0, 0, 0))
            wm.z.insert(wm._first_normal_index(), hh)
            return hh

        m.CreateWindowExW = create_window
        m.DestroyWindow = lambda x: wm.destroy(h(x)) or True
        return m
