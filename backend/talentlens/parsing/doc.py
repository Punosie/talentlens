"""Legacy .doc extraction.

Tries these in order:
1. LibreOffice headless (`soffice --convert-to txt`), converting into a temp directory.
2. Microsoft Word via COM, opened ReadOnly and closed without saving.
3. Raises ParseError, so the CV is marked "unreadable".
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from . import ParseError, ParseResult, decode_text_bytes

_word_lock = threading.Lock()

_SOFFICE_CANDIDATES = [
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "/usr/bin/soffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
]


def _find_soffice() -> str | None:
    exe = shutil.which("soffice")
    if exe:
        return exe
    return next((c for c in _SOFFICE_CANDIDATES if os.path.isfile(c)), None)


def _via_libreoffice(path: Path, soffice: str) -> str:
    with tempfile.TemporaryDirectory(prefix="talentlens-doc-") as tmp:
        profile = Path(tmp) / "profile"
        cmd = [
            soffice,
            f"-env:UserInstallation={profile.as_uri()}",
            "--headless",
            "--norestore",
            "--convert-to",
            "txt:Text (encoded):UTF8",
            "--outdir",
            tmp,
            str(path),
        ]
        subprocess.run(cmd, capture_output=True, timeout=120, check=False)
        out = Path(tmp) / f"{path.stem}.txt"
        if not out.is_file():
            raise ParseError("LibreOffice could not convert the document")
        return decode_text_bytes(out.read_bytes())


def _via_word(path: Path) -> str:
    import pythoncom
    import win32com.client

    with _word_lock:
        pythoncom.CoInitialize()
        word = None
        try:
            word = win32com.client.DispatchEx("Word.Application")
            word.Visible = False
            word.DisplayAlerts = 0
            doc = word.Documents.Open(
                str(path.resolve()),
                ConfirmConversions=False,
                ReadOnly=True,
                AddToRecentFiles=False,
                Visible=False,
                NoEncodingDialog=True,
            )
            try:
                return str(doc.Content.Text)
            finally:
                doc.Close(SaveChanges=0)  # wdDoNotSaveChanges
        finally:
            if word is not None:
                word.Quit(SaveChanges=0)
            pythoncom.CoUninitialize()


def parse_doc(path: Path) -> ParseResult:
    # Work on a private temp copy so neither converter can drop lock files
    # (e.g. Word's "~$name.doc") or anything else into the CV folder.
    with tempfile.TemporaryDirectory(prefix="talentlens-docsrc-") as tmp:
        copy = Path(tmp) / f"source{path.suffix.lower()}"
        shutil.copyfile(path, copy)
        return _parse_doc_copy(copy)


def _parse_doc_copy(path: Path) -> ParseResult:
    errors: list[str] = []
    soffice = _find_soffice()
    if soffice:
        try:
            return ParseResult(text=_via_libreoffice(path, soffice), parser="libreoffice")
        except (ParseError, subprocess.SubprocessError, OSError) as e:
            errors.append(f"LibreOffice: {e}")
    if sys.platform == "win32":
        try:
            return ParseResult(text=_via_word(path), parser="word-com")
        except Exception as e:  # COM errors are varied
            errors.append(f"Word: {e}")
    if not errors:
        errors.append("Install LibreOffice or Microsoft Word to read .doc files")
    raise ParseError("; ".join(errors))
