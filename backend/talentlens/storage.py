"""Access to the CV folder.

Hard rule: existing files are READ-ONLY. This module only ever:
  * lists and hashes files, and
  * creates NEW files for uploads, using exclusive-create mode ('xb'), so an
    existing file can never be overwritten, even in a race.
"""

from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .config import CV_EXTENSIONS

_CHUNK = 1024 * 1024

# Magic-byte signatures for accepted formats
_MAGIC: dict[str, tuple[bytes, ...]] = {
    ".pdf": (b"%PDF",),
    ".docx": (b"PK\x03\x04",),
    ".doc": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
}

_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class UploadRejected(ValueError):
    """Raised when an upload is not acceptable. The message is user-facing."""


class DuplicateUpload(UploadRejected):
    def __init__(self, existing_rel_path: str) -> None:
        super().__init__(f"Already in the library as '{existing_rel_path}'")
        self.existing_rel_path = existing_rel_path


@dataclass(frozen=True)
class FileInfo:
    path: Path
    rel_path: str
    size: int
    mtime: float

    @property
    def ext(self) -> str:
        return self.path.suffix.lower()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest().upper()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sniff_matches(ext: str, head: bytes) -> bool:
    sigs = _MAGIC.get(ext)
    if sigs is None:  # .txt etc.: must decode as text, not be binary
        return b"\x00" not in head[:4096]
    return any(head.startswith(s) for s in sigs)


def safe_filename(name: str) -> str:
    """Sanitize an untrusted filename: drop any directory parts, illegal chars, reserved names."""
    # Only the final component counts; this kills ../ and absolute paths on both OSes
    base = name.replace("\\", "/").split("/")[-1]
    base = unicodedata.normalize("NFC", base)
    base = _ILLEGAL.sub("_", base).strip().rstrip(". ")  # Windows forbids trailing dots/spaces
    stem, dot, ext = base.rpartition(".")
    if not dot:
        stem, ext = base, ""
    stem = stem.strip() or "resume"
    if stem.upper() in _WINDOWS_RESERVED:
        stem = f"_{stem}"
    stem = stem[:150]
    return f"{stem}.{ext.lower()}" if ext else stem


class CVStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def exists(self) -> bool:
        return self.root.is_dir()

    def rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.root.resolve()).as_posix()

    def resolve_rel(self, rel_path: str) -> Path:
        """Map a stored rel_path back to disk, refusing anything outside the root."""
        root = self.root.resolve()
        p = (root / rel_path).resolve()
        if root != p and root not in p.parents:
            raise UploadRejected("Path escapes the CV folder")
        return p

    def iter_files(self) -> list[FileInfo]:
        if not self.exists():
            return []
        out: list[FileInfo] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if not d.startswith((".", "~"))]
            for fn in filenames:
                if fn.startswith(("~$", ".")):  # Office lock/temp files, hidden files
                    continue
                p = Path(dirpath) / fn
                if p.suffix.lower() not in CV_EXTENSIONS:
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue
                out.append(FileInfo(p, self.rel(p), st.st_size, st.st_mtime))
        out.sort(key=lambda f: f.rel_path.lower())
        return out

    def save_upload(
        self,
        filename: str,
        data: bytes,
        *,
        max_bytes: int,
        known_hashes: dict[str, str],
    ) -> tuple[Path, str]:
        """Persist a NEW resume. Returns (path, sha256).

        known_hashes maps sha256 to the rel_path of files already indexed. Files on
        disk that are not indexed yet are also checked (by size, then hash).
        """
        name = safe_filename(filename)
        ext = Path(name).suffix.lower()
        if ext not in CV_EXTENSIONS:
            raise UploadRejected(
                f"Unsupported file type '{ext or '(none)'}'. Use PDF, DOCX or DOC."
            )
        if not data:
            raise UploadRejected("The file is empty")
        if len(data) > max_bytes:
            raise UploadRejected(f"File is larger than {max_bytes // (1024 * 1024)} MB")
        if not sniff_matches(ext, data[:16]):
            raise UploadRejected(f"File content is not a valid {ext.upper()[1:]} document")

        digest = sha256_bytes(data)
        if digest in known_hashes:
            raise DuplicateUpload(known_hashes[digest])
        for f in self.iter_files():  # unindexed files with the same size
            if f.size == len(data) and sha256_file(f.path) == digest:
                raise DuplicateUpload(f.rel_path)

        self.root.mkdir(parents=True, exist_ok=True)
        stem, suffix = Path(name).stem, Path(name).suffix
        for i in range(1, 1000):
            candidate = self.root / (name if i == 1 else f"{stem} ({i}){suffix}")
            try:
                with candidate.open("xb") as f:  # exclusive: never overwrite
                    f.write(data)
                return candidate, digest
            except FileExistsError:
                continue
        raise UploadRejected("Could not find a free filename")
