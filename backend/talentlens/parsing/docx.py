"""DOCX text extraction straight from the OOXML parts.

Reads the body (paragraphs, tables and text boxes in document order) plus the
headers and footers, where many resumes keep the name and contact details.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from lxml import etree

from . import ParseError, ParseResult

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_PARTS = re.compile(r"^word/(header\d*|document|footer\d*)\.xml$")
_MAX_XML_BYTES = 50 * 1024 * 1024


def _paragraph_texts(root: etree._Element) -> list[str]:
    """Each w:p becomes one line; nested paragraphs (text boxes) become their own lines."""
    out: list[str] = []

    def walk(el: etree._Element, buf: list[str] | None) -> None:
        for child in el:
            tag = child.tag
            if tag == f"{W}p":
                own: list[str] = []
                walk(child, own)
                line = "".join(own).strip()
                if line:
                    out.append(line)
            elif tag == f"{W}t" and buf is not None:
                buf.append(child.text or "")
            elif tag == f"{W}tab" and buf is not None:
                buf.append("\t")
            elif tag in (f"{W}br", f"{W}cr") and buf is not None:
                buf.append("\n")
            elif tag == f"{W}tc":  # table cell boundary
                walk(child, buf)
                if buf is not None:
                    buf.append(" | ")
            else:
                walk(child, buf)

    walk(root, None)
    return out


def parse_docx(path: Path) -> ParseResult:
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        raise ParseError(f"Not a valid DOCX file: {e}") from e
    with zf:
        names = [n for n in zf.namelist() if _PARTS.match(n)]
        if "word/document.xml" not in names:
            raise ParseError("DOCX has no document body")
        # header(s) first, then body, then footer(s)
        order = sorted(
            names, key=lambda n: (0 if "header" in n else 1 if "document" in n else 2, n)
        )
        parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
        sections: list[str] = []
        seen: set[str] = set()
        for name in order:
            info = zf.getinfo(name)
            if info.file_size > _MAX_XML_BYTES:
                continue
            root = etree.fromstring(zf.read(name), parser=parser)
            lines = [ln for ln in _paragraph_texts(root) if ln not in seen or "document" in name]
            seen.update(lines)
            if lines:
                sections.append("\n".join(lines))
    return ParseResult(text="\n\n".join(sections), parser="docx-xml")
