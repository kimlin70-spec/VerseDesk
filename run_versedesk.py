"""Entry script for PyInstaller (and for `python run_versedesk.py` during development)."""

from versedesk.main import main

if __name__ == "__main__":
    raise SystemExit(main())
