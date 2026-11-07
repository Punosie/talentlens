"""Text extraction for resumes and JDs. Every parser opens files read-only."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


class ParseError(RuntimeError):
    """The document could not be read (corrupt, encrypted, unsupported)."""


@dataclass
class ParseResult:
    text: str
    parser: str
    pages: int | None = None
    ocr_used: bool = False
    warnings: list[str] = field(default_factory=list)


_MULTI_BLANK = re.compile(r"\n{3,}")
_TRAILING_WS = re.compile(r"[ \t ]+\n")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CTRL.sub(" ", text)
    text = text.replace("­", "")  # soft hyphen
    text = _TRAILING_WS.sub("\n", text)
    text = _MULTI_BLANK.sub("\n\n", text)
    return text.strip()


def decode_text_bytes(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def parse_file(path: Path, *, ocr_min_chars_per_page: int = 50) -> ParseResult:
    """Dispatch on extension. Raises ParseError when nothing usable comes out."""
    ext = path.suffix.lower()
    if ext == ".pdf":
        from .pdf import parse_pdf

        result = parse_pdf(path, ocr_min_chars_per_page=ocr_min_chars_per_page)
    elif ext == ".docx":
        from .docx import parse_docx

        result = parse_docx(path)
    elif ext == ".doc":
        from .doc import parse_doc

        result = parse_doc(path)
    elif ext == ".txt":
        result = ParseResult(text=decode_text_bytes(path.read_bytes()), parser="text")
    else:
        raise ParseError(f"Unsupported file type: {ext}")
    result.text = normalize_text(result.text)
    return result


def parse_bytes(filename: str, data: bytes, *, ocr_min_chars_per_page: int = 50) -> ParseResult:
    """Parse an in-memory document (e.g. an uploaded JD) via a private temp file."""
    import tempfile

    ext = Path(filename).suffix.lower()
    if ext == ".txt":
        return ParseResult(text=normalize_text(decode_text_bytes(data)), parser="text")
    with tempfile.TemporaryDirectory(prefix="talentlens-") as tmp:
        p = Path(tmp) / f"upload{ext}"
        p.write_bytes(data)
        return parse_file(p, ocr_min_chars_per_page=ocr_min_chars_per_page)
