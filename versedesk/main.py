"""Program entry point."""

from __future__ import annotations

import argparse
import logging
import platform
import sys

from versedesk import paths
from versedesk.version import version_string

log = logging.getLogger("versedesk")

EXIT_ALREADY_RUNNING = 3


def _parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="VerseDesk", add_help=True)
    ap.add_argument("--exit-after", type=float, default=None, metavar="SECONDS",
                    help="quit automatically after SECONDS (used by automated checks)")
    ap.add_argument("--no-duplicate-dialog", action="store_true",
                    help="do not show the 'already running' message box (automated checks)")
    ap.add_argument("--version", action="store_true", help="print the version and exit")
    # parse_known_args: never die because of an unexpected argument (e.g. from a shortcut)
    args, _unknown = ap.parse_known_args(argv)
    return args


def _log_startup() -> None:
    log.info("=" * 70)
    log.info("VerseDesk %s starting", version_string())
    log.info("python %s on %s (%s)", platform.python_version(), platform.platform(), platform.machine())
    log.info("executable %s frozen=%s", sys.executable, bool(getattr(sys, "frozen", False)))
    log.info("data folder %s", paths.app_data_dir())


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = _parse_args(argv)
    if args.version:
        if sys.stdout is not None:
            print(version_string())
        return 0

    from versedesk.logging_setup import (
        enable_crash_report,
        install_qt_message_handler,
        setup_logging,
        shutdown_logging,
    )

    setup_logging(paths.log_path())
    clean_exit = False
    try:
        _log_startup()
        from versedesk.single_instance import SingleInstance, show_already_running_message

        instance = SingleInstance(paths.app_data_dir())
        if not instance.acquire():
            log.info("another VerseDesk is already running; exiting")
            if not args.no_duplicate_dialog:
                show_already_running_message()
            return EXIT_ALREADY_RUNNING
        enable_crash_report(paths.crash_path())

        from PySide6 import __version__ as pyside_version
        from PySide6.QtCore import QTimer, qVersion
        from PySide6.QtWidgets import QApplication

        log.info("PySide6 %s, Qt %s", pyside_version, qVersion())
        install_qt_message_handler()
        qapp = QApplication([sys.argv[0]] if sys.argv else ["VerseDesk"])
        qapp.setApplicationName("VerseDesk")
        qapp.setQuitOnLastWindowClosed(False)  # we only have tool windows and a tray icon

        from versedesk.app import VerseDeskApp
        from versedesk.housekeeping import clean_in_background
        from versedesk.settings import SettingsStore

        clean_in_background()

        store = SettingsStore(paths.settings_path())
        result = store.load()
        if store.settings.debug_log:
            from PySide6.QtCore import QLoggingCategory

            logging.getLogger().setLevel(logging.DEBUG)
            QLoggingCategory.setFilterRules(
                "qt.qpa.window.debug=true\nqt.qpa.screen.debug=true\nqt.qpa.trayicon.debug=true"
            )
            log.info("debug logging enabled (settings.json debug_log)")
        controller = VerseDeskApp(qapp, store, result)
        controller.start()
        if args.exit_after is not None:
            QTimer.singleShot(int(max(0.0, args.exit_after) * 1000), controller.quit)
        code = qapp.exec()
        log.info("event loop finished (code %s)", code)
        instance.release()
        clean_exit = True
        return int(code)
    except Exception:
        log.exception("fatal error during startup")
        return 1
    finally:
        shutdown_logging(clean_exit=clean_exit)
