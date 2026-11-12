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
    datas=[
        ("versedesk/data/verses.json", "versedesk/data"),
        ("versedesk/data/bsb.txt.xz", "versedesk/data"),  # the whole BSB, for the verse list editor
        ("versedesk/data/psalm_titles.json", "versedesk/data"),
    ],
    hiddenimports=["lzma", "_lzma"],  # imported by versedesk.bible (loaded only when the editor opens)
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick"],
    noarchive=False,
)

# Trim what a tray app with a few widgets never uses: Qt's UI translations (our strings
# are written directly in Korean) and the software OpenGL renderer.
DROP_SUFFIXES = (
    "opengl32sw.dll",              # software OpenGL renderer (20 MB); widgets use the raster engine
    "platforms/qdirect2d.dll",     # alternative platform plugin; we use qwindows
    "generic/qtuiotouchplugin.dll",  # TUIO touch input over the network
    "qt6network.dll",              # only needed by the TUIO plugin; PySide6.QtNetwork is excluded
)


def _keep(entry):
    dest = entry[0].replace("\\", "/").lower()
    if "/translations/" in dest or dest.endswith(".qm"):
        return False
    return not dest.endswith(DROP_SUFFIXES)


a.datas = [e for e in a.datas if _keep(e)]
a.binaries = [e for e in a.binaries if _keep(e)]

# A bad filter must fail the build, not the user's PC.
_dests = {e[0].replace("\\", "/").lower() for e in a.binaries}
for required in ("platforms/qwindows.dll", "styles/qmodernwindowsstyle.dll", "qt6widgets.dll"):
    if not any(d.endswith(required) for d in _dests):
        raise SystemExit(f"VerseDesk.spec: required Qt file missing from the bundle: {required}")

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
