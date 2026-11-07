"""Safe reading of resume ZIP archives for bulk import.

Defences:
- entry count and total uncompressed size caps,
- per-file size cap, enforced on the bytes actually read (headers can lie),
- compression-ratio check against "zip bombs",
- nested archives, folders, hidden and macOS metadata entries are skipped,
- entry names are flattened to a safe base name, so a ZIP can never write outside the folder
  (the actual write goes through CVStore.save_upload).
"""

from __future__ import annotations

import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import IO

from .config import CV_EXTENSIONS

MAX_ENTRIES = 2000
MAX_TOTAL_UNCOMPRESSED = 500 * 1024 * 1024
MAX_RATIO = 200  # uncompressed / compressed; real PDFs and DOCX are nowhere near this


class ArchiveRejected(ValueError):
    """The whole archive is refused. The message is user-facing."""


@dataclass
class ZipItem:
    name: str  # base file name inside the archive
    data: bytes | None  # None when skipped
    skipped: str | None = None  # user-facing reason when skipped


def iter_zip(fileobj: IO[bytes], *, max_file_bytes: int) -> Iterator[ZipItem]:
    try:
        zf = zipfile.ZipFile(fileobj)
    except (zipfile.BadZipFile, OSError) as e:
        raise ArchiveRejected(f"This isn't a valid ZIP file ({e}).") from e
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > MAX_ENTRIES:
            raise ArchiveRejected(
                f"The ZIP has {len(infos)} files; import at most {MAX_ENTRIES} at a time."
            )
        if sum(i.file_size for i in infos) > MAX_TOTAL_UNCOMPRESSED:
            raise ArchiveRejected("The ZIP is too large when unpacked (over 500 MB).")
        total = 0
        for info in infos:
            path = PurePosixPath(info.filename.replace("\\", "/"))
            base = path.name
            if ".." in path.parts or path.is_absolute():
                yield ZipItem(base or info.filename, None, "Unsafe path inside the ZIP, skipped")
                continue
            if not base or any(part.startswith((".", "__MACOSX")) for part in path.parts):
                continue  # hidden files and macOS metadata: silently ignored
            if base.startswith("~$"):
                continue  # Office lock files
            ext = PurePosixPath(base).suffix.lower()
            if ext == ".zip":
                yield ZipItem(base, None, "ZIPs inside ZIPs aren't opened")
                continue
            if ext not in CV_EXTENSIONS:
                yield ZipItem(base, None, "Not a resume file (PDF, DOCX or DOC)")
                continue
            if info.flag_bits & 0x1:
                yield ZipItem(base, None, "This file is password protected inside the ZIP")
                continue
            if info.file_size > max_file_bytes:
                yield ZipItem(base, None, f"Larger than {max_file_bytes // (1024 * 1024)} MB")
                continue
            if info.compress_size and info.file_size / info.compress_size > MAX_RATIO:
                raise ArchiveRejected("This ZIP looks unsafe (it expands far too much).")
            with zf.open(info) as f:
                data = f.read(max_file_bytes + 1)
            if len(data) > max_file_bytes:
                yield ZipItem(base, None, f"Larger than {max_file_bytes // (1024 * 1024)} MB")
                continue
            total += len(data)
            if total > MAX_TOTAL_UNCOMPRESSED:
                raise ArchiveRejected("The ZIP is too large when unpacked (over 500 MB).")
            yield ZipItem(base, data)
