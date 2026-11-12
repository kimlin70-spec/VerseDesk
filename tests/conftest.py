import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Qt tests run without a display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Isolated %APPDATA%\\VerseDesk equivalent."""
    d = tmp_path / "VerseDeskHome"
    monkeypatch.setenv("VERSEDESK_HOME", str(d))
    return d


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    yield app
