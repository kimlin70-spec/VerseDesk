"""Write assets/versedesk.ico (used as the exe icon) from versedesk/ui/icon.py.

    QT_QPA_PLATFORM=offscreen python tools/make_icon.py

The .ico holds PNG-compressed images (supported since Windows Vista) at the usual sizes.
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from versedesk.ui.icon import draw_icon  # noqa: E402

ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def png_bytes(size: int) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    draw_icon(size).save(buf, "PNG")
    buf.close()
    return bytes(data)


def write_ico(path: Path) -> None:
    images = [(s, png_bytes(s)) for s in ICO_SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, blob in images:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        blobs += blob
        offset += len(blob)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + entries + blobs)


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841 - needed for QPainter/fonts
    out = REPO / "assets" / "versedesk.ico"
    write_ico(out)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
