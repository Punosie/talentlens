"""Render frontend/public/favicon.svg into app icons:

- assets/talentlens.ico  (Windows shortcut; PNG-compressed frames)
- assets/TalentLens.icns (macOS app bundle; PNG frames, supported since macOS 10.7)

    uv run python scripts/make_icon.py
"""

from __future__ import annotations

import struct
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "frontend" / "public" / "favicon.svg"
ICO = ROOT / "assets" / "talentlens.ico"
ICNS = ROOT / "assets" / "TalentLens.icns"
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
# ICNS type codes holding PNG data, with their pixel sizes
ICNS_TYPES = (
    (b"icp4", 16),
    (b"icp5", 32),
    (b"icp6", 64),
    (b"ic07", 128),
    (b"ic08", 256),
    (b"ic09", 512),
    (b"ic10", 1024),  # 512@2x
    (b"ic11", 32),  # 16@2x
    (b"ic12", 64),  # 32@2x
    (b"ic13", 256),  # 128@2x
    (b"ic14", 512),  # 256@2x
)


def render(size: int, *, pad: float = 0.0) -> bytes:
    """PNG of the logo at `size` px; `pad` adds transparent margin (macOS icon grid)."""
    doc = pymupdf.open(stream=SVG.read_bytes(), filetype="svg")
    page = doc[0]
    inner = size * (1 - 2 * pad)
    zoom = inner / max(page.rect.width, page.rect.height)
    logo = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=True)
    doc.close()
    if not pad:
        return logo.tobytes("png")
    canvas = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, size, size), 1)
    canvas.clear_with(0)
    off = round(size * pad)
    logo.set_origin(off, off)
    canvas.copy(logo, logo.irect)
    return canvas.tobytes("png")


def write_ico() -> None:
    frames = [(s, render(s)) for s in ICO_SIZES]
    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = 6 + 16 * len(frames)
    entries = b""
    blobs = b""
    for size, png in frames:
        dim = 0 if size >= 256 else size  # 0 means 256 in the ICO format
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        blobs += png
        offset += len(png)
    ICO.parent.mkdir(parents=True, exist_ok=True)
    ICO.write_bytes(header + entries + blobs)
    print(f"wrote {ICO} ({ICO.stat().st_size} bytes)")


def write_icns() -> None:
    cache: dict[int, bytes] = {}
    chunks = b""
    for code, size in ICNS_TYPES:
        # macOS icons sit on a grid with ~10% transparent margin
        png = cache.setdefault(size, render(size, pad=0.1))
        chunks += code + struct.pack(">I", 8 + len(png)) + png
    ICNS.write_bytes(b"icns" + struct.pack(">I", 8 + len(chunks)) + chunks)
    print(f"wrote {ICNS} ({ICNS.stat().st_size} bytes)")


if __name__ == "__main__":
    write_ico()
    write_icns()
