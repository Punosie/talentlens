"""Local OCR via RapidOCR (PaddleOCR models exported to ONNX; runs on CPU, no internet)."""

from __future__ import annotations

import threading
from typing import Any

_engine: Any = None
_lock = threading.Lock()


def _get_engine() -> Any:
    global _engine
    if _engine is None:
        with _lock:
            if _engine is None:
                from rapidocr_onnxruntime import RapidOCR

                _engine = RapidOCR()
    return _engine


def ocr_png_bytes(png: bytes) -> str:
    """Return recognised text lines in reading order (top-to-bottom, left-to-right)."""
    engine = _get_engine()
    with _lock:  # onnxruntime sessions are not guaranteed re-entrant
        result, _elapsed = engine(png)
    if not result:
        return ""
    # result: [[box(4 points), text, score], ...]
    lines = []
    for box, text, score in result:
        if float(score) < 0.5 or not text.strip():
            continue
        top = min(p[1] for p in box)
        left = min(p[0] for p in box)
        height = max(p[1] for p in box) - top
        lines.append((top, left, max(height, 1.0), text.strip()))
    lines.sort(key=lambda t: (t[0], t[1]))

    # Group boxes whose vertical centre is within half a line height into one row
    rows: list[list[tuple[float, float, float, str]]] = []
    for item in lines:
        if rows and abs(item[0] - rows[-1][0][0]) < item[2] * 0.6:
            rows[-1].append(item)
        else:
            rows.append([item])
    return "\n".join(" ".join(t[3] for t in sorted(r, key=lambda t: t[1])) for r in rows)
