"""Read-only lookup into the optional cv_index.csv (where each CV came from)."""

from __future__ import annotations

import csv
import threading
from pathlib import Path

_FIELDS = (
    "source_type",
    "primary_source",
    "mail_subject",
    "mail_from",
    "mail_received",
    "duplicate_sources",
)


class Provenance:
    def __init__(self, csv_path: Path | None) -> None:
        self.csv_path = csv_path
        self._lock = threading.Lock()
        self._mtime: float | None = None
        self._by_file: dict[str, dict[str, str]] = {}
        self._by_sha: dict[str, dict[str, str]] = {}

    def _load(self) -> None:
        if not self.csv_path or not self.csv_path.is_file():
            self._by_file, self._by_sha, self._mtime = {}, {}, None
            return
        mtime = self.csv_path.stat().st_mtime
        if mtime == self._mtime:
            return
        by_file: dict[str, dict[str, str]] = {}
        by_sha: dict[str, dict[str, str]] = {}
        with self.csv_path.open("r", encoding="utf-8-sig", newline="") as f:  # read-only
            for row in csv.DictReader(f):
                info = {
                    k: (row.get(k) or "").strip() for k in _FIELDS if (row.get(k) or "").strip()
                }
                if fn := (row.get("file") or "").strip():
                    by_file[fn.lower()] = info
                if sha := (row.get("sha256") or "").strip():
                    by_sha[sha.upper()] = info
        self._by_file, self._by_sha, self._mtime = by_file, by_sha, mtime

    def lookup(self, filename: str, sha256: str | None = None) -> dict[str, str]:
        with self._lock:
            try:
                self._load()
            except OSError:
                return {}
            if sha256 and (hit := self._by_sha.get(sha256.upper())):
                return hit
            return self._by_file.get(filename.lower(), {})
