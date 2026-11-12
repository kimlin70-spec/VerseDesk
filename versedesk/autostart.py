"""'Start with Windows' via HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run.

No admin rights needed (HKCU only).  Windows' Task Manager / Settings > Apps > Startup can
switch a Run entry off without deleting it; they record that under
HKCU\\...\\Explorer\\StartupApproved\\Run as a 12-byte value whose first byte is even
(02, 06) for "enabled" and odd (03, 07) for "disabled".  We read it so the tray menu shows
the real state, and clear it when the user turns autostart back on from our menu.

The registry access is behind a tiny interface so the logic can be tested with a fake.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Protocol

log = logging.getLogger("versedesk.autostart")

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
VALUE_NAME = "VerseDesk"


class RegistryBackend(Protocol):
    def get(self, key: str, name: str) -> object | None: ...
    def set_string(self, key: str, name: str, value: str) -> None: ...
    def delete(self, key: str, name: str) -> None: ...


class WinRegBackend:
    """HKEY_CURRENT_USER access through the standard-library winreg module."""

    def __init__(self) -> None:
        import winreg  # noqa: F401 - fails on non-Windows, by design

    def get(self, key: str, name: str) -> object | None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_READ) as k:
                value, _type = winreg.QueryValueEx(k, name)
                return value
        except FileNotFoundError:
            return None

    def set_string(self, key: str, name: str, value: str) -> None:
        import winreg

        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)

    def delete(self, key: str, name: str) -> None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, name)
        except FileNotFoundError:
            pass


def approved_flag_enabled(value: object | None) -> bool:
    """Interpret a StartupApproved value. Missing/unknown means enabled."""
    if isinstance(value, (bytes, bytearray)) and len(value) >= 1:
        return value[0] % 2 == 0
    return True


def launch_command(executable: str | Path) -> str:
    """The Run value: the exe path in quotes (paths may contain spaces)."""
    return f'"{Path(executable)}"'


def same_command(a: str | None, b: str | None) -> bool:
    """Run values naming the same exe (ignoring quotes and letter case, as Windows does)."""
    if a is None or b is None:
        return False

    def norm(s: str) -> str:
        return os.path.normcase(os.path.normpath(s.strip().strip('"')))

    return norm(a) == norm(b)


def current_exe() -> Path | None:
    """Path of the running VerseDesk.exe, or None when not running as a frozen exe."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return None


class Autostart:
    def __init__(self, backend: RegistryBackend | None, exe: Path | None):
        self.backend = backend
        self.exe = exe

    @classmethod
    def for_this_process(cls) -> "Autostart":
        backend: RegistryBackend | None = None
        if sys.platform == "win32":
            try:
                backend = WinRegBackend()
            except Exception:
                log.exception("registry unavailable")
        return cls(backend, current_exe())

    @property
    def supported(self) -> bool:
        """Only a real exe on Windows registers itself (never a development checkout)."""
        return self.backend is not None and self.exe is not None

    def registered_command(self) -> str | None:
        if self.backend is None:
            return None
        value = self.backend.get(RUN_KEY, VALUE_NAME)
        return value if isinstance(value, str) else None

    def is_enabled(self) -> bool:
        """True if Windows will actually start us at logon."""
        if self.backend is None or self.registered_command() is None:
            return False
        return approved_flag_enabled(self.backend.get(APPROVED_KEY, VALUE_NAME))

    def enable(self, user_request: bool = True) -> bool:
        """Register the Run value. Only an explicit "on" from the user (the tray menu) also
        clears a "disabled" mark left by Task Manager / Settings; startup never does."""
        if not self.supported:
            return False
        assert self.backend is not None and self.exe is not None
        try:
            self.backend.set_string(RUN_KEY, VALUE_NAME, launch_command(self.exe))
            if user_request:
                self.backend.delete(APPROVED_KEY, VALUE_NAME)
            log.info("autostart enabled: %s", launch_command(self.exe))
            return True
        except OSError:
            log.exception("could not enable autostart")
            return False

    def disable(self) -> bool:
        if self.backend is None:
            return False
        try:
            self.backend.delete(RUN_KEY, VALUE_NAME)
            log.info("autostart disabled")
            return True
        except OSError:
            log.exception("could not disable autostart")
            return False

    def sync_at_startup(self, wanted: bool) -> bool:
        """Make the registry match the saved preference; returns the effective state.

        * wanted and registered -> refresh the path if the exe was moved (but respect a
          Task-Manager "disabled" flag: that is the user's choice too).
        * wanted and not registered -> register.
        * not wanted -> make sure nothing is registered.
        """
        if not self.supported:
            return self.is_enabled()
        assert self.backend is not None and self.exe is not None
        try:
            registered = self.registered_command()
            if wanted:
                expected = launch_command(self.exe)
                if registered is None:
                    self.enable(user_request=False)
                elif not same_command(registered, expected):
                    self.backend.set_string(RUN_KEY, VALUE_NAME, expected)
                    log.info("autostart path updated: %s -> %s", registered, expected)
            elif registered is not None:
                self.disable()
        except OSError:
            log.exception("autostart sync failed")
        return self.is_enabled()
