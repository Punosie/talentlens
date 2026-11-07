"""Render frontend/public/favicon.svg into a multi-size Windows .ico (PNG-compressed frames).

uv run python scripts/make_icon.py
"""

from __future__ import annotations

import struct
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "frontend" / "public" / "favicon.svg"
OUT = ROOT / "assets" / "talentlens.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def render(size: int) -> bytes:
    doc = pymupdf.open(stream=SVG.read_bytes(), filetype="svg")
    page = doc[0]
    zoom = size / max(page.rect.width, page.rect.height)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=True)
    data = pix.tobytes("png")
    doc.close()
    return data


def main() -> None:
    frames = [(s, render(s)) for s in SIZES]
    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = 6 + 16 * len(frames)
    entries = b""
    blobs = b""
    for size, png in frames:
        dim = 0 if size >= 256 else size  # 0 means 256 in the ICO format
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        blobs += png
        offset += len(png)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(header + entries + blobs)
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
