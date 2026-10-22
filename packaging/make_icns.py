"""Write Litreader.icns (the 'L' brand icon) without iconutil: an .icns file is a 'icns' header followed by
(type, length, PNG bytes) entries, so this runs (and is tested) on any OS with PySide6 offscreen.
Usage: python packaging/make_icns.py build/Litreader.icns"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

# OSType -> pixel size (PNG payloads; supported since macOS 10.7)
TYPES = [("icp4", 16), ("icp5", 32), ("icp6", 64), ("ic07", 128), ("ic08", 256), ("ic09", 512), ("ic10", 1024),
         ("ic11", 32), ("ic12", 64), ("ic13", 256), ("ic14", 512)]


def png_for(size: int) -> bytes:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from litreader.gui import avatar
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    avatar.default_avatar(size).save(buf, "PNG")
    return bytes(ba.data())


def build_icns(png=png_for) -> bytes:
    cache: dict[int, bytes] = {}
    body = b""
    for t, n in TYPES:
        data = cache.setdefault(n, png(n))
        body += t.encode("ascii") + struct.pack(">I", len(data) + 8) + data
    return b"icns" + struct.pack(">I", len(body) + 8) + body


def parse_icns(raw: bytes) -> list[tuple[str, int]]:
    assert raw[:4] == b"icns" and struct.unpack(">I", raw[4:8])[0] == len(raw)
    out, i = [], 8
    while i < len(raw):
        t, n = raw[i:i + 4].decode("ascii"), struct.unpack(">I", raw[i + 4:i + 8])[0]
        out.append((t, n))
        i += n
    return out


if __name__ == "__main__":
    dst = Path(sys.argv[1] if len(sys.argv) > 1 else "build/Litreader.icns")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(build_icns())
    print(dst)
