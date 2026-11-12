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
from typing import Any

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


def embedding_text(f: CVFields, text: str, chars: int = 6000) -> str:
    """What we embed: the structured highlights first, then the start of the resume.
    chars < 6000 (CPU): the whole text is capped there; the model only reads ~512 tokens
    anyway, and a shorter focused input embeds several times faster."""
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
    if chars < 6000:
        return (f"{head}\n\n{text}" if head else text)[:chars]
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
        self.backfill_confidence()
        files = self.store.iter_files()
        report.scanned = len(files)
        on_disk = {f.rel_path: f for f in files}

        with self.db.connect() as conn:
            rows = {
                r["rel_path"]: r
                for r in conn.execute(
                    "SELECT id, rel_path, size, mtime, sha256, status, embed_model FROM cvs "
                    "WHERE source='file'"
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

        llm_json = self._stored_llm_json(f.rel_path, sha)
        fields = self.enricher.extract(parsed.text, f.path.name, llm_json)
        blob = self._embed(fields, parsed.text)
        self._write(f, sha, parsed, fields, blob)
        return "indexed"

    def _embed(self, fields: CVFields, text: str) -> bytes | None:
        chars = getattr(self.enricher, "embed_chars", 6000)
        emb = self.enricher.embed_documents([embedding_text(fields, text, chars)])
        return emb[0].astype(np.float32).tobytes() if emb is not None and len(emb) else None

    def _stored_llm_json(self, rel_path: str, sha: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT llm_json, llm_sha FROM cvs WHERE rel_path=?", (rel_path,)
            ).fetchone()
        if row and row["llm_json"] and row["llm_sha"] == sha:
            try:
                return json.loads(row["llm_json"])
            except json.JSONDecodeError:
                return None
        return None

    # ------------------------------------------------------------------
    # Stage 2: LLM refinement (slow; runs in the background, newest first)
    # ------------------------------------------------------------------
    # CVs that still need the LLM: not done for this content, not already confident by rules
    _PENDING = (
        "status='indexed' AND source='file' AND confident=0 "
        "AND (llm_sha IS NULL OR llm_sha != sha256) AND llm_attempts < 2"
    )

    def backfill_confidence(self) -> int:
        """One-time for libraries made before v0.2: mark CVs the rules already read well."""
        if self.db.get_meta("confidence_v") == "1":
            return 0
        from .ai import rules

        marked = 0
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT id, text, filename, name, title, city FROM cvs WHERE status='indexed' "
                "AND source='file' AND (llm_sha IS NULL OR llm_sha != sha256)"
            ).fetchall()
        ids = [
            r["id"]
            for r in rows
            if rules.is_confident(r["text"] or "", r["filename"], r["name"], r["title"], r["city"])
        ]
        if ids:
            with self.db.write() as conn:
                conn.executemany("UPDATE cvs SET confident=1 WHERE id=?", [(i,) for i in ids])
            marked = len(ids)
        self.db.set_meta("confidence_v", "1")
        return marked

    def pending_llm_count(self) -> int:
        with self.db.connect() as conn:
            return conn.execute(f"SELECT COUNT(*) FROM cvs WHERE {self._PENDING}").fetchone()[0]

    def prioritize(self, ids: list[int]) -> None:
        """Ask the background AI to read these CVs next (e.g. top shortlist results)."""
        if not ids:
            return
        stamp = time.time()
        with self.db.write() as conn:
            conn.executemany(
                "UPDATE cvs SET ai_priority=? WHERE id=?",
                [(stamp - i * 1e-3, cid) for i, cid in enumerate(ids)],  # keep their order
            )

    def _twin_llm_json(self, conn: Any, row: Any) -> str | None:
        """An already-read copy of the same person (same email, or same name and near-identical
        text) lets us reuse its AI result instead of calling the model again."""
        if row["email"]:
            twin = conn.execute(
                "SELECT llm_json FROM cvs WHERE id != ? AND email = ? AND llm_json IS NOT NULL "
                "AND llm_sha = sha256 LIMIT 1",
                (row["id"], row["email"]),
            ).fetchone()
            if twin:
                return twin["llm_json"]
        if row["name"] and row["embedding"] is not None:
            mine = np.frombuffer(row["embedding"], dtype=np.float32)
            for t in conn.execute(
                "SELECT llm_json, embedding FROM cvs WHERE id != ? AND name = ? "
                "AND llm_json IS NOT NULL AND llm_sha = sha256 AND embedding IS NOT NULL",
                (row["id"], row["name"]),
            ):
                other = np.frombuffer(t["embedding"], dtype=np.float32)
                if other.shape == mine.shape and float(mine @ other) >= 0.98:
                    return t["llm_json"]
        return None

    def refine_pending(
        self,
        *,
        should_stop: Callable[[], bool],
        progress: ProgressFn | None = None,
    ) -> dict[str, int]:
        """Run the LLM for each CV that still needs it, highest priority first, then newest.

        The next CV is chosen fresh each time, so CVs prioritised mid-pass (shortlist results,
        opened profiles) are read next. Stops between CVs when asked.
        """
        done = failed = reused = 0
        if not self.enricher.llm_available():
            return {"refined": 0, "failed": 0, "reused": 0, "skipped": self.pending_llm_count()}
        total = self.pending_llm_count()
        tried: set[int] = set()
        i = 0
        while not should_stop():
            with self.db.connect() as conn:
                skip = ",".join(str(x) for x in tried) or "-1"
                row = conn.execute(
                    "SELECT id, filename, text, sha256, email, name, embedding FROM cvs "
                    f"WHERE {self._PENDING} AND id NOT IN ({skip}) "
                    "ORDER BY ai_priority DESC, added_at DESC, id DESC LIMIT 1"
                ).fetchone()
                twin = self._twin_llm_json(conn, row) if row is not None else None
            if row is None:
                break
            cv_id = row["id"]
            tried.add(cv_id)
            if progress:
                progress(i, max(total, i + 1), row["filename"])
            i += 1
            try:
                if twin is not None:
                    llm_json = json.loads(twin)
                    reused += 1
                else:
                    llm_json = self.enricher.llm_extract(row["text"] or "", row["filename"])
            except Exception as e:
                log.warning("LLM extraction failed for %s: %s", row["filename"], e)
                failed += 1
                with self.db.write() as conn:
                    conn.execute(
                        "UPDATE cvs SET llm_attempts=llm_attempts+1, llm_error=? WHERE id=?",
                        (str(e)[:300], cv_id),
                    )
                if not self.enricher.llm_available():
                    break  # Ollama went away; try again on the next pass
                continue
            fields = self.enricher.extract(row["text"] or "", row["filename"], llm_json)
            blob = self._embed(fields, row["text"] or "")
            with self.db.write() as conn:
                cur = conn.execute(
                    "UPDATE cvs SET llm_json=?, llm_sha=?, llm_at=?, llm_error=NULL "
                    "WHERE id=? AND sha256=?",
                    (json.dumps(llm_json), row["sha256"], _now(), cv_id, row["sha256"]),
                )
                if cur.rowcount:
                    self._apply_fields(
                        conn, cv_id, fields, blob, row["text"] or "", row["filename"]
                    )
            done += 1
            if done % 5 == 0:
                self._notify()
        if progress:
            progress(i, max(total, i), "")
        if done:
            self._notify()
        return {"refined": done, "failed": failed, "reused": reused, "skipped": 0}

    def _apply_fields(
        self,
        conn: Any,
        cv_id: int,
        fields: CVFields,
        blob: bytes | None,
        text: str,
        filename: str,
    ) -> None:
        conn.execute(
            """UPDATE cvs SET extractor=?, name=?, email=?, phone=?, location=?, city=?,
                 country=?, years_exp=?, title=?, skills=?, domains=?, education=?, summary=?,
                 embedding=?, embed_model=? WHERE id=?""",
            (
                fields.extractor,
                fields.name,
                fields.email,
                fields.phone,
                fields.location,
                fields.city,
                fields.country,
                fields.years_exp,
                fields.title,
                json.dumps(fields.skills),
                json.dumps(fields.domains),
                json.dumps(fields.education),
                fields.summary,
                blob,
                self.enricher.embed_model_name if blob else None,
                cv_id,
            ),
        )
        self._write_facets(conn, cv_id, fields, text, filename)

    def _write_facets(
        self, conn: Any, cv_id: int, fields: CVFields, text: str, filename: str
    ) -> None:
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
                fields.name or Path(filename).stem,
                fields.title or "",
                " ; ".join(fields.skills),
                " ; ".join(fields.domains),
                fields.location or "",
                text,
            ),
        )

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
            "confident": int(fields.confident and fields.extractor == "rules"),
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
            row = conn.execute(
                "SELECT id, llm_sha FROM cvs WHERE rel_path=?", (f.rel_path,)
            ).fetchone()
            if row["llm_sha"] != sha:  # new content: give the LLM fresh attempts
                conn.execute("UPDATE cvs SET llm_attempts=0 WHERE id=?", (row["id"],))
            self._write_facets(conn, row["id"], fields, parsed.text, f.path.name)

    # ---- records that do not come from a file (e.g. LinkedIn profiles synced from MongoDB) ----

    def upsert_external(
        self,
        conn: Any,
        *,
        rel_path: str,
        filename: str,
        source: str,
        sha: str,
        text: str,
        fields: CVFields,
        blob: bytes | None,
        mtime: float,
        extra: dict[str, Any],
    ) -> int:
        """Insert/update a non-file record inside an open write transaction; returns its id.

        These rows never touch the CV folder: the folder scan and the background AI pass
        only look at source='file' rows."""
        values = {
            "rel_path": rel_path,
            "filename": filename,
            "ext": source,
            "sha256": sha,
            "size": len(text),
            "mtime": mtime,
            "status": "indexed",
            "error": None,
            "text": text,
            "text_chars": len(text),
            "pages": None,
            "ocr_used": 0,
            "parser": source,
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
            "confident": 1,
            "source": source,
            **extra,
        }
        cols = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        updates = ", ".join(f"{c}=excluded.{c}" for c in values if c != "rel_path")
        conn.execute(
            f"INSERT INTO cvs({cols}) VALUES ({marks}) "
            f"ON CONFLICT(rel_path) DO UPDATE SET {updates}",
            tuple(values.values()),
        )
        cv_id = conn.execute("SELECT id FROM cvs WHERE rel_path=?", (rel_path,)).fetchone()["id"]
        self._write_facets(conn, cv_id, fields, text, filename)
        return cv_id

    def delete_ids(self, conn: Any, ids: list[int]) -> None:
        conn.executemany("DELETE FROM cv_fts WHERE rowid=?", [(i,) for i in ids])
        conn.executemany("DELETE FROM cvs WHERE id=?", [(i,) for i in ids])

    def notify_changed(self) -> None:
        self._notify()
