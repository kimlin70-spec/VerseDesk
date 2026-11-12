"""Logging to %APPDATA%\\VerseDesk\\log.txt.

The app is a resident tray program, so the rules are:
  * every error goes to log.txt with a traceback,
  * nothing may crash the process (excepthooks only log),
  * the log stays small (rotates at 512 KB, keeps one old file: log.txt.1).
"""

from __future__ import annotations

import faulthandler
import logging
import logging.handlers
import sys
import threading
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_BYTES = 512 * 1024

log = logging.getLogger("versedesk")

_crash_file = None  # kept open for faulthandler


class _NullStream:
    """Replacement for sys.stdout/sys.stderr in a windowed (no console) exe."""

    encoding = "utf-8"

    def write(self, s: str) -> int:
        return len(s)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False


class _LoggingStream(_NullStream):
    """Sends anything printed to stderr into the log (one record per line)."""

    def __init__(self, logger: logging.Logger):
        self._logger = logger
        self._buf = ""

    def write(self, s: str) -> int:
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self._logger.warning(line.rstrip())
        return len(s)


def _excepthook(exc_type, exc, tb) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        return
    log.error("Unhandled exception", exc_info=(exc_type, exc, tb))


def _thread_excepthook(args) -> None:
    if args.exc_type is SystemExit:
        return
    log.error(
        "Unhandled exception in thread %s",
        getattr(args.thread, "name", "?"),
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )


def _unraisablehook(unraisable) -> None:
    log.error(
        "Unraisable exception in %r: %s",
        unraisable.object,
        unraisable.err_msg or "",
        exc_info=(unraisable.exc_type, unraisable.exc_value, unraisable.exc_traceback),
    )


def setup_logging(log_file: Path, crash_file: Path | None = None, level: int = logging.INFO) -> None:
    """Configure the root logger. Never raises: if the log file cannot be opened we log nowhere."""
    global _crash_file

    if sys.stdout is None:
        sys.stdout = _NullStream()
    if sys.stderr is None:
        sys.stderr = _LoggingStream(logging.getLogger("stderr"))

    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)

    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=MAX_BYTES, backupCount=1, encoding="utf-8", delay=False
        )
    except OSError:
        handler = logging.NullHandler()
    handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    root.addHandler(handler)

    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
    sys.unraisablehook = _unraisablehook

    if crash_file is not None:
        _adopt_previous_crash(crash_file)
        try:
            _crash_file = open(crash_file, "w", encoding="utf-8")
            faulthandler.enable(file=_crash_file, all_threads=True)
        except OSError:
            _crash_file = None


def _adopt_previous_crash(crash_file: Path) -> None:
    """If the previous run died hard, copy faulthandler's report into log.txt."""
    try:
        if crash_file.is_file() and crash_file.stat().st_size > 0:
            text = crash_file.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                # On Windows faulthandler also records native exceptions that were handled,
                # so this is a hint for diagnosis, not proof of a crash.
                log.warning("faulthandler output from the previous run:\n%s", text[-8000:])
    except OSError:
        pass


def shutdown_logging() -> None:
    global _crash_file
    try:
        faulthandler.disable()
    except Exception:
        pass
    if _crash_file is not None:
        try:
            _crash_file.close()
        except OSError:
            pass
        _crash_file = None
    logging.shutdown()


def install_qt_message_handler() -> None:
    """Route Qt's own warnings into the log (deduplicating repeats)."""
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    qt_log = logging.getLogger("qt")
    last = {"msg": None, "count": 0}
    levels = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }

    def handler(mode, context, message):  # noqa: ARG001 - Qt signature
        try:
            if message == last["msg"]:
                last["count"] += 1
                if last["count"] in (10, 100, 1000):
                    qt_log.warning("(previous Qt message repeated %d times)", last["count"])
                return
            last["msg"], last["count"] = message, 0
            qt_log.log(levels.get(mode, logging.WARNING), "%s", message)
        except Exception:
            pass

    qInstallMessageHandler(handler)
