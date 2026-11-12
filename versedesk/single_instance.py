"""Allow only one VerseDesk per Windows logon session.

Windows: a named mutex in the session-local namespace ("Local\\...").  The handle is held
for the life of the process; Windows releases it automatically when the process exits,
even after a crash, so a stale lock is impossible.
Elsewhere (development/tests): an exclusive lock on a file in the app data folder.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

log = logging.getLogger("versedesk.single_instance")

MUTEX_NAME = "Local\\VerseDesk.SingleInstance.6f0c2a"
ERROR_ALREADY_EXISTS = 183


class SingleInstance:
    def __init__(self, lock_dir: Path):
        self._lock_dir = Path(lock_dir)
        self._handle = None
        self._file = None

    def acquire(self) -> bool:
        """True if we are the only instance. Errors are logged and treated as 'go ahead'."""
        try:
            if sys.platform == "win32":
                return self._acquire_mutex()
            return self._acquire_file_lock()
        except Exception:
            log.exception("single-instance check failed; continuing")
            return True

    def _acquire_mutex(self) -> bool:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        err = ctypes.get_last_error()
        if not handle:
            log.warning("CreateMutexW failed (error %s); continuing", err)
            return True
        self._handle = handle  # keep it open until exit
        return err != ERROR_ALREADY_EXISTS

    def _acquire_file_lock(self) -> bool:
        import fcntl

        self._lock_dir.mkdir(parents=True, exist_ok=True)
        self._file = open(self._lock_dir / "instance.lock", "w")
        try:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._file.close()
            self._file = None
            return False
        self._file.write(str(os.getpid()))
        self._file.flush()
        return True

    def release(self) -> None:
        if self._handle:
            try:
                import ctypes

                ctypes.WinDLL("kernel32").CloseHandle(self._handle)
            except Exception:
                pass
            self._handle = None
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None


def show_already_running_message() -> None:
    """Tell the user (who probably double-clicked the exe again) where the app is."""
    text = (
        "VerseDesk가 이미 실행 중입니다.\n\n"
        "화면 오른쪽 아래 작업 표시줄의 트레이 아이콘(보이지 않으면 ^ 단추를 누르세요)을 "
        "눌러 메뉴를 열 수 있습니다."
    )
    if sys.platform == "win32":
        try:
            import ctypes

            MB_ICONINFORMATION, MB_SETFOREGROUND, MB_TOPMOST = 0x40, 0x10000, 0x40000
            ctypes.WinDLL("user32").MessageBoxW(
                None, text, "VerseDesk", MB_ICONINFORMATION | MB_SETFOREGROUND | MB_TOPMOST
            )
            return
        except Exception:
            log.exception("could not show message box")
    log.info("another instance is already running")
