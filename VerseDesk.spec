# -*- mode: python ; coding: utf-8 -*-
# PyInstaller recipe for the single-file, windowed VerseDesk.exe.
#   python tools/write_build_info.py --build N   (optional: version resource + build label)
#   python -m PyInstaller --noconfirm --clean VerseDesk.spec
import os

version_file = os.path.join("build", "version_info.txt")

a = Analysis(
    ["run_versedesk.py"],
    pathex=[],
    binaries=[],
    datas=[("versedesk/data/verses.json", "versedesk/data")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick"],
    noarchive=False,
)

# Trim what a tray app with a few widgets never uses: Qt's UI translations (our strings
# are written directly in Korean) and the software OpenGL renderer.
def _keep(entry):
    dest = entry[0].replace("\\", "/").lower()
    if "/translations/" in dest or dest.endswith(".qm"):
        return False
    if dest.endswith("opengl32sw.dll"):
        return False
    return True

a.datas = [e for e in a.datas if _keep(e)]
a.binaries = [e for e in a.binaries if _keep(e)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="VerseDesk",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon="assets/versedesk.ico",
    version=version_file if os.path.exists(version_file) else None,
)
