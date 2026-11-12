"""CI helper: stamp the build number into the app and write PyInstaller's version resource.

    python tools/write_build_info.py --build 42 --commit abcdef1234

Writes versedesk/_build_info.py (read by versedesk/version.py) and build/version_info.txt
(the Windows "Details" tab of VerseDesk.exe).  Both files are git-ignored.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def app_version() -> str:
    text = (REPO / "versedesk" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"(\d+)\.(\d+)\.(\d+)"', text)
    if not m:
        raise SystemExit("cannot find __version__")
    return ".".join(m.groups())


VERSION_TEMPLATE = """# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({a}, {b}, {c}, {build}),
    prodvers=({a}, {b}, {c}, {build}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'VerseDesk'),
        StringStruct('FileDescription', 'VerseDesk'),
        StringStruct('FileVersion', '{version}.{build}'),
        StringStruct('InternalName', 'VerseDesk'),
        StringStruct('LegalCopyright', 'Scripture: Berean Standard Bible (BSB), public domain'),
        StringStruct('OriginalFilename', 'VerseDesk.exe'),
        StringStruct('ProductName', 'VerseDesk'),
        StringStruct('ProductVersion', '{version}.{build}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", required=True, type=int)
    ap.add_argument("--commit", default="")
    args = ap.parse_args(argv)
    version = app_version()
    a, b, c = (int(x) for x in version.split("."))
    short = args.commit[:7]
    label = f"build {args.build}" + (f", {short}" if short else "")
    (REPO / "versedesk" / "_build_info.py").write_text(f'BUILD = "{label}"\n', encoding="utf-8")
    out = REPO / "build" / "version_info.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(VERSION_TEMPLATE.format(a=a, b=b, c=c, build=args.build, version=version), encoding="utf-8")
    print(f"VerseDesk {version} ({label})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
