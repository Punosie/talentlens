"""PDF text extraction with PyMuPDF, falling back to OCR for image-only pages."""

from __future__ import annotations

import logging
from pathlib import Path

import pymupdf

from . import ParseError, ParseResult

log = logging.getLogger(__name__)

_OCR_DPI = 200
_MAX_PAGES = 30  # resumes are short; guard against huge PDFs


def parse_pdf(path: Path, *, ocr_min_chars_per_page: int = 50) -> ParseResult:
    try:
        doc = pymupdf.open(path)  # read-only open
    except Exception as e:  # pymupdf raises various types
        raise ParseError(f"Cannot open PDF: {e}") from e
    with doc:
        if doc.needs_pass:
            raise ParseError("PDF is password protected")
        parts: list[str] = []
        ocr_pages = 0
        warnings: list[str] = []
        for i, page in enumerate(doc):
            if i >= _MAX_PAGES:
                warnings.append(f"Only the first {_MAX_PAGES} pages were read")
                break
            # 'blocks' sort keeps multi-column layouts mostly in reading order
            text = page.get_text("text", sort=True) or ""
            if len(text.strip()) < ocr_min_chars_per_page:
                ocr_text = _ocr_page(page)
                if len(ocr_text.strip()) > len(text.strip()):
                    text = ocr_text
                    ocr_pages += 1
            parts.append(text)
        return ParseResult(
            text="\n\n".join(parts),
            parser="pymupdf+ocr" if ocr_pages else "pymupdf",
            pages=doc.page_count,
            ocr_used=ocr_pages > 0,
            warnings=warnings,
        )


def _ocr_page(page: pymupdf.Page) -> str:
    try:
        from .ocr import ocr_png_bytes

        pix = page.get_pixmap(dpi=_OCR_DPI, colorspace=pymupdf.csGRAY)
        return ocr_png_bytes(pix.tobytes("png"))
    except Exception:  # OCR is best-effort; never fail the whole document
        log.exception("OCR failed for a page")
        return ""
