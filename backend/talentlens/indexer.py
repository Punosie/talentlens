"""Incremental indexer: scans the CV folder and keeps the DB in sync.

* Source files are only ever opened for reading.
* Unchanged files (same size and mtime, or same SHA-256) are skipped unless a full
  refresh is asked for.
* Files that disappeared from disk are dropped from the DB. The disk is never touched.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from .db import Database
from .enrich import CVFields, Enricher
from .parsing import ParseError, parse_file
from .storage import CVStore, FileInfo, sha256_file

log = logging.getLogger(__name__)

MIN_TEXT_CHARS = 40
ProgressFn = Callable[[int, int, str], None]


@dataclass
class IndexReport:
    scanned: int = 0
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    failed: int = 0
    unreadable: int = 0
    seconds: float = 0.0
    errors: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def embedding_text(f: CVFields, text: str) -> str:
    """What we embed: the structured highlights first, then the start of the resume."""
    head = " | ".join(
        x
        for x in (
            f.title,
            f"{f.years_exp:g} years experience" if f.years_exp else None,
            f.location,
            ", ".join(f.domains) if f.domains else None,
            ", ".join(f.skills[:40]) if f.skills else None,
            f.summary,
        )
        if x
    )
    return f"{head}\n\n{text[:6000]}" if head else text[:6000]


class Indexer:
    def __init__(
        self,
        db: Database,
        store: CVStore,
        enricher: Enricher,
        *,
        ocr_min_chars_per_page: int = 50,
    ) -> None:
        self.db = db
        self.store = store
        self.enricher = enricher
        self.ocr_min_chars_per_page = ocr_min_chars_per_page
        self.listeners: list[Callable[[], None]] = []

    # ------------------------------------------------------------------
    def run(self, *, full: bool = False, progress: ProgressFn | None = None) -> IndexReport:
        t0 = time.perf_counter()
        report = IndexReport()
        files = self.store.iter_files()
        report.scanned = len(files)
        on_disk = {f.rel_path: f for f in files}

        with self.db.connect() as conn:
            rows = {
                r["rel_path"]: r
                for r in conn.execute(
                    "SELECT id, rel_path, size, mtime, sha256, status, embed_model FROM cvs"
                )
            }

        # 1) forget DB rows whose file is gone (never touches disk)
        gone = [r["id"] for p, r in rows.items() if p not in on_disk]
        if gone:
            with self.db.write() as conn:
                conn.executemany("DELETE FROM cv_fts WHERE rowid=?", [(i,) for i in gone])
                conn.executemany("DELETE FROM cvs WHERE id=?", [(i,) for i in gone])
            report.removed = len(gone)

        # 2) decide what needs (re)processing
        todo: list[tuple[FileInfo, str | None]] = []  # (file, known sha if unchanged content)
        for f in files:
            row = rows.get(f.rel_path)
            if row is None:
                todo.append((f, None))
                continue
            stale_model = (
                row["status"] == "indexed"
                and (row["embed_model"] or "none") != self.enricher.embed_model_name
            )
            same_stat = row["size"] == f.size and abs(row["mtime"] - f.mtime) < 1e-3
            if full or row["status"] == "pending" or stale_model:
                todo.append((f, None))
            elif not same_stat:
                todo.append((f, row["sha256"]))
            else:
                report.unchanged += 1

        total = len(todo)
        for i, (f, old_sha) in enumerate(todo, start=1):
            if progress:
                progress(i - 1, total, f.rel_path)
            try:
                status = self._process(f, old_sha=old_sha, existed=f.rel_path in rows)
            except Exception as e:  # one bad file must never stop the run
                log.exception("Indexing failed for %s", f.rel_path)
                self._mark(f, "error", str(e)[:500])
                report.failed += 1
                report.errors.append({"file": f.rel_path, "error": str(e)[:300]})
                continue
            if status == "unchanged":
                report.unchanged += 1
            elif status == "unreadable":
                report.unreadable += 1
                report.errors.append({"file": f.rel_path, "error": "No readable text"})
            elif f.rel_path in rows:
                report.updated += 1
            else:
                report.added += 1
        if progress:
            progress(total, total, "")

        report.seconds = round(time.perf_counter() - t0, 2)
        self.db.set_meta("last_index_at", _now())
        self.db.set_meta("last_index_report", json.dumps(report.as_dict()))
        if report.added or report.updated or report.removed or full:
            self._notify()
        return report

    # ------------------------------------------------------------------
    def _notify(self) -> None:
        for cb in self.listeners:
            try:
                cb()
            except Exception:
                log.exception("Index listener failed")

    def _mark(self, f: FileInfo, status: str, error: str | None) -> None:
        sha = sha256_file(f.path) if f.path.exists() else ""
        with self.db.write() as conn:
            conn.execute(
                """INSERT INTO cvs(rel_path, filename, ext, sha256, size, mtime, status, error)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(rel_path) DO UPDATE SET sha256=excluded.sha256, size=excluded.size,
                     mtime=excluded.mtime, status=excluded.status, error=excluded.error""",
                (f.rel_path, f.path.name, f.ext, sha, f.size, f.mtime, status, error),
            )

    def _process(self, f: FileInfo, *, old_sha: str | None, existed: bool) -> str:
        sha = sha256_file(f.path)
        if old_sha is not None and sha == old_sha:
            # Touched but identical content: refresh stat only
            with self.db.write() as conn:
                conn.execute(
                    "UPDATE cvs SET size=?, mtime=? WHERE rel_path=?",
                    (f.size, f.mtime, f.rel_path),
                )
            return "unchanged"

        try:
            parsed = parse_file(f.path, ocr_min_chars_per_page=self.ocr_min_chars_per_page)
        except ParseError as e:
            self._mark(f, "unreadable", str(e)[:500])
            return "unreadable"
        if len(parsed.text) < MIN_TEXT_CHARS:
            self._mark(f, "unreadable", "Document contains no readable text")
            return "unreadable"

        fields = self.enricher.extract(parsed.text, f.path.name)
        emb = self.enricher.embed_documents([embedding_text(fields, parsed.text)])
        blob = emb[0].astype(np.float32).tobytes() if emb is not None and len(emb) else None
        self._write(f, sha, parsed, fields, blob)
        return "indexed"

    def _write(self, f: FileInfo, sha: str, parsed, fields: CVFields, blob: bytes | None) -> None:
        values = {
            "rel_path": f.rel_path,
            "filename": f.path.name,
            "ext": f.ext,
            "sha256": sha,
            "size": f.size,
            "mtime": f.mtime,
            "status": "indexed",
            "error": "; ".join(parsed.warnings) or None,
            "text": parsed.text,
            "text_chars": len(parsed.text),
            "pages": parsed.pages,
            "ocr_used": int(parsed.ocr_used),
            "parser": parsed.parser,
            "extractor": fields.extractor,
            "name": fields.name,
            "email": fields.email,
            "phone": fields.phone,
            "location": fields.location,
            "city": fields.city,
            "country": fields.country,
            "years_exp": fields.years_exp,
            "title": fields.title,
            "skills": json.dumps(fields.skills),
            "domains": json.dumps(fields.domains),
            "education": json.dumps(fields.education),
            "summary": fields.summary,
            "embedding": blob,
            "embed_model": self.enricher.embed_model_name if blob else None,
            "indexed_at": _now(),
        }
        cols = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        updates = ", ".join(f"{c}=excluded.{c}" for c in values if c != "rel_path")
        with self.db.write() as conn:
            conn.execute(
                f"INSERT INTO cvs({cols}) VALUES ({marks}) "
                f"ON CONFLICT(rel_path) DO UPDATE SET {updates}",
                tuple(values.values()),
            )
            cv_id = conn.execute("SELECT id FROM cvs WHERE rel_path=?", (f.rel_path,)).fetchone()[
                "id"
            ]
            conn.execute("DELETE FROM cv_skills WHERE cv_id=?", (cv_id,))
            conn.execute("DELETE FROM cv_domains WHERE cv_id=?", (cv_id,))
            conn.executemany(
                "INSERT OR IGNORE INTO cv_skills(cv_id, skill) VALUES (?,?)",
                [(cv_id, s) for s in fields.skills],
            )
            conn.executemany(
                "INSERT OR IGNORE INTO cv_domains(cv_id, domain) VALUES (?,?)",
                [(cv_id, d) for d in fields.domains],
            )
            conn.execute("DELETE FROM cv_fts WHERE rowid=?", (cv_id,))
            conn.execute(
                "INSERT INTO cv_fts(rowid, name, title, skills, domains, location, body) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    cv_id,
                    fields.name or Path(f.path.name).stem,
                    fields.title or "",
                    " ; ".join(fields.skills),
                    " ; ".join(fields.domains),
                    fields.location or "",
                    parsed.text,
                ),
            )
