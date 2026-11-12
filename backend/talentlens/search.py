"""Hybrid search: SQL facet filters, BM25 (FTS5) and dense cosine similarity, fused with RRF."""

from __future__ import annotations

import re
import sqlite3
import threading
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from .ai.embed import Embedder
from .db import Database
from .serializers import SUMMARY_COLUMNS, cv_summary

RRF_K = 60
SortKey = Literal["relevance", "recent", "experience", "name"]


@dataclass
class Filters:
    skills: list[str] = field(default_factory=list)
    skills_mode: Literal["all", "any"] = "all"
    years_min: float | None = None
    years_max: float | None = None
    locations: list[str] = field(default_factory=list)  # city or country names
    domains: list[str] = field(default_factory=list)
    exts: list[str] = field(default_factory=list)
    include_unreadable: bool = False
    sources: list[str] = field(default_factory=list)  # file | linkedin
    owners: list[str] = field(default_factory=list)  # LinkedIn accounts (connected via)

    def sql(self) -> tuple[str, list[Any]]:
        where: list[str] = []
        args: list[Any] = []
        if not self.include_unreadable:
            where.append("c.status = 'indexed'")
        if self.skills:
            marks = ",".join("?" * len(self.skills))
            if self.skills_mode == "all":
                where.append(
                    f"(SELECT COUNT(DISTINCT s.skill) FROM cv_skills s "
                    f"WHERE s.cv_id = c.id AND s.skill IN ({marks})) = ?"
                )
                args.extend(self.skills)
                args.append(len({s.lower() for s in self.skills}))
            else:
                where.append(
                    f"EXISTS (SELECT 1 FROM cv_skills s WHERE s.cv_id = c.id "
                    f"AND s.skill IN ({marks}))"
                )
                args.extend(self.skills)
        if self.years_min is not None:
            where.append("c.years_exp >= ?")
            args.append(self.years_min)
        if self.years_max is not None:
            where.append("c.years_exp <= ?")
            args.append(self.years_max)
        if self.locations:
            marks = ",".join("?" * len(self.locations))
            where.append(
                f"(c.city COLLATE NOCASE IN ({marks}) OR c.country COLLATE NOCASE IN ({marks}))"
            )
            args.extend(self.locations)
            args.extend(self.locations)
        if self.domains:
            marks = ",".join("?" * len(self.domains))
            where.append(
                f"EXISTS (SELECT 1 FROM cv_domains d WHERE d.cv_id = c.id "
                f"AND d.domain IN ({marks}))"
            )
            args.extend(self.domains)
        if self.exts:
            marks = ",".join("?" * len(self.exts))
            where.append(f"c.ext IN ({marks})")
            args.extend("." + e.lower().lstrip(".") for e in self.exts)
        if self.sources:
            marks = ",".join("?" * len(self.sources))
            where.append(f"c.source IN ({marks})")
            args.extend(self.sources)
        if self.owners:
            marks = ",".join("?" * len(self.owners))
            where.append(
                f"EXISTS (SELECT 1 FROM json_each(c.owners) o "
                f"WHERE o.value COLLATE NOCASE IN ({marks}))"
            )
            args.extend(self.owners)
        return (" AND ".join(where) or "1=1"), args


_TOKEN = re.compile(r"[\w+#.]+", re.UNICODE)


def fts_query(q: str, mode: Literal["and", "or"] = "and") -> str | None:
    """Turn free text into a safe FTS5 query (quoted tokens, prefix on the last one)."""
    tokens = [t.strip(".") for t in _TOKEN.findall(q)]
    tokens = [t for t in tokens if t and len(t) <= 40]
    if not tokens:
        return None
    quoted = [f'"{t.replace(chr(34), "")}"' for t in tokens[:20]]
    if len(tokens[-1]) >= 3 and tokens[-1].isalnum():
        quoted[-1] = quoted[-1] + "*"
    return (" AND " if mode == "and" else " OR ").join(quoted)


class VectorIndex:
    """All embeddings in one normalised float32 matrix, reloaded lazily after index changes."""

    def __init__(self, db: Database, model_name: str) -> None:
        self.db = db
        self.model_name = model_name
        self._lock = threading.Lock()
        self._dirty = True
        self.ids = np.zeros(0, dtype=np.int64)
        self.matrix = np.zeros((0, 1), dtype=np.float32)
        self._pos: dict[int, int] = {}

    def mark_dirty(self) -> None:
        self._dirty = True

    def _load(self) -> None:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT id, embedding FROM cvs WHERE status='indexed' AND embedding IS NOT NULL "
                "AND embed_model = ?",
                (self.model_name,),
            ).fetchall()
        if rows:
            self.ids = np.array([r["id"] for r in rows], dtype=np.int64)
            self.matrix = np.vstack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
        else:
            self.ids = np.zeros(0, dtype=np.int64)
            self.matrix = np.zeros((0, 1), dtype=np.float32)
        self._pos = {int(i): k for k, i in enumerate(self.ids)}
        self._dirty = False

    def similarities(self, query_vec: np.ndarray, candidate_ids: list[int]) -> dict[int, float]:
        with self._lock:
            if self._dirty:
                self._load()
            idx = [self._pos[i] for i in candidate_ids if i in self._pos]
            if not idx or self.matrix.shape[1] != query_vec.shape[0]:
                return {}
            sims = self.matrix[idx] @ query_vec
            return {int(self.ids[k]): float(s) for k, s in zip(idx, sims, strict=True)}


class SearchEngine:
    def __init__(self, db: Database, embedder: Embedder) -> None:
        self.db = db
        self.embedder = embedder
        self.vectors = VectorIndex(db, embedder.model_name)

    def on_index_changed(self) -> None:
        self.vectors.mark_dirty()

    # ------------------------------------------------------------------
    def candidate_ids(self, conn: sqlite3.Connection, filters: Filters) -> list[int]:
        where, args = filters.sql()
        return [r[0] for r in conn.execute(f"SELECT c.id FROM cvs c WHERE {where}", args)]

    def lexical(
        self, conn: sqlite3.Connection, q: str, allowed: set[int], limit: int = 500
    ) -> list[tuple[int, float]]:
        out: list[tuple[int, float]] = []
        for mode in ("and", "or"):
            fq = fts_query(q, mode)  # type: ignore[arg-type]
            if not fq:
                return []
            try:
                rows = conn.execute(
                    # column weights: name, title, skills, domains, location, body
                    "SELECT rowid, bm25(cv_fts, 4.0, 3.0, 3.0, 1.5, 1.5, 1.0) AS r "
                    "FROM cv_fts WHERE cv_fts MATCH ? ORDER BY r LIMIT ?",
                    (fq, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            out = [(r[0], -r[1]) for r in rows if r[0] in allowed]
            if out:
                return out
        return out

    def dense(self, q: str, candidates: list[int]) -> list[tuple[int, float]]:
        qv = self.embedder.embed_query(q)
        sims = self.vectors.similarities(qv, candidates)
        return sorted(sims.items(), key=lambda kv: kv[1], reverse=True)

    def search(
        self,
        q: str | None,
        filters: Filters,
        *,
        sort: SortKey = "relevance",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        q = (q or "").strip()
        with self.db.connect() as conn:
            cands = self.candidate_ids(conn, filters)
            scores: dict[int, float] = {}
            if q and cands:
                allowed = set(cands)
                lex = self.lexical(conn, q, allowed)
                dense = self.dense(q, cands)
                lex_rank = {cid: r for r, (cid, _) in enumerate(lex)}
                # Dense retrieval always returns everything; keep only reasonably similar docs,
                # unless lexical search found nothing at all.
                top_sim = dense[0][1] if dense else 0.0
                dense_kept = [
                    (cid, s) for cid, s in dense if s >= max(0.0, top_sim - 0.12) or cid in lex_rank
                ]
                if not lex:
                    dense_kept = dense_kept[:50]
                dense_rank = {cid: r for r, (cid, _) in enumerate(dense_kept)}
                for cid in set(lex_rank) | set(dense_rank):
                    s = 0.0
                    if cid in lex_rank:
                        s += 1.0 / (RRF_K + lex_rank[cid] + 1)
                    if cid in dense_rank:
                        s += 1.0 / (RRF_K + dense_rank[cid] + 1)
                    scores[cid] = s
                ordered = sorted(scores, key=lambda c: scores[c], reverse=True)
            else:
                ordered = cands

            total = len(ordered)
            if sort != "relevance" or not q:
                ordered = self._sorted(conn, ordered, sort if sort != "relevance" else "recent")
            page = ordered[offset : offset + limit]
            rows = self._rows(conn, page)
            snippets = self._snippets(conn, q, page) if q else {}

        max_score = max(scores.values()) if scores else 1.0
        items = []
        for cid in page:
            row = rows.get(cid)
            if row is None:
                continue
            item = cv_summary(row)
            if q:
                item["score"] = round(scores.get(cid, 0.0) / max_score, 3)
                item["snippet"] = snippets.get(cid)
            if filters.skills:
                wanted = {s.lower() for s in filters.skills}
                item["matched_skills"] = [s for s in item["skills"] if s.lower() in wanted]
            items.append(item)
        return {"total": total, "items": items}

    def _sorted(self, conn: sqlite3.Connection, ids: list[int], sort: str) -> list[int]:
        if not ids:
            return ids
        order = {
            "recent": "added_at DESC, id DESC",
            "experience": "years_exp IS NULL, years_exp DESC, id DESC",
            "name": "COALESCE(name, filename) COLLATE NOCASE ASC",
        }[sort]
        marks = ",".join("?" * len(ids))
        return [
            r[0]
            for r in conn.execute(f"SELECT id FROM cvs WHERE id IN ({marks}) ORDER BY {order}", ids)
        ]

    def _rows(self, conn: sqlite3.Connection, ids: list[int]) -> dict[int, sqlite3.Row]:
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        rows = conn.execute(f"SELECT {SUMMARY_COLUMNS} FROM cvs WHERE id IN ({marks})", ids)
        return {r["id"]: r for r in rows}

    def _snippets(self, conn: sqlite3.Connection, q: str, ids: list[int]) -> dict[int, str]:
        fq = fts_query(q, "or")
        if not fq or not ids:
            return {}
        marks = ",".join("?" * len(ids))
        try:
            rows = conn.execute(
                f"SELECT rowid, snippet(cv_fts, 5, '[[', ']]', ' … ', 18) FROM cv_fts "
                f"WHERE cv_fts MATCH ? AND rowid IN ({marks})",
                [fq, *ids],
            ).fetchall()
        except sqlite3.OperationalError:
            return {}
        return {r[0]: r[1] for r in rows}

    # ------------------------------------------------------------------
    def facets(self) -> dict[str, Any]:
        with self.db.connect() as conn:
            skills = conn.execute(
                "SELECT s.skill AS v, COUNT(*) AS n FROM cv_skills s JOIN cvs c ON c.id=s.cv_id "
                "WHERE c.status='indexed' GROUP BY s.skill COLLATE NOCASE ORDER BY n DESC, v "
                "LIMIT 400"
            ).fetchall()
            domains = conn.execute(
                "SELECT d.domain AS v, COUNT(*) AS n FROM cv_domains d JOIN cvs c ON c.id=d.cv_id "
                "WHERE c.status='indexed' GROUP BY d.domain ORDER BY n DESC, v"
            ).fetchall()
            countries = conn.execute(
                "SELECT country AS v, COUNT(*) AS n FROM cvs WHERE status='indexed' "
                "AND country IS NOT NULL GROUP BY country ORDER BY n DESC, v"
            ).fetchall()
            cities = conn.execute(
                "SELECT city AS v, country AS c, COUNT(*) AS n FROM cvs WHERE status='indexed' "
                "AND city IS NOT NULL GROUP BY city ORDER BY n DESC, v"
            ).fetchall()
            yrs = conn.execute(
                "SELECT MIN(years_exp), MAX(years_exp), COUNT(years_exp), COUNT(*) FROM cvs "
                "WHERE status='indexed'"
            ).fetchone()
            buckets = conn.execute(
                "SELECT CASE WHEN years_exp < 3 THEN '0-3' WHEN years_exp < 6 THEN '3-6' "
                "WHEN years_exp < 10 THEN '6-10' WHEN years_exp < 15 THEN '10-15' "
                "ELSE '15+' END AS b, COUNT(*) FROM cvs WHERE status='indexed' "
                "AND years_exp IS NOT NULL GROUP BY b"
            ).fetchall()
            sources = conn.execute(
                "SELECT source AS v, COUNT(*) AS n FROM cvs WHERE status='indexed' GROUP BY source"
            ).fetchall()
            owners = conn.execute(
                "SELECT o.value AS v, COUNT(*) AS n FROM cvs c, json_each(c.owners) o "
                "WHERE c.status='indexed' GROUP BY o.value ORDER BY n DESC LIMIT 50"
            ).fetchall()
        return {
            "sources": [{"value": r["v"], "count": r["n"]} for r in sources],
            "owners": [{"value": r["v"], "count": r["n"]} for r in owners],
            "skills": [{"value": r["v"], "count": r["n"]} for r in skills],
            "domains": [{"value": r["v"], "count": r["n"]} for r in domains],
            "countries": [{"value": r["v"], "count": r["n"]} for r in countries],
            "cities": [{"value": r["v"], "country": r["c"], "count": r["n"]} for r in cities],
            "years": {
                "min": yrs[0],
                "max": yrs[1],
                "known": yrs[2],
                "total": yrs[3],
                "buckets": {b: n for b, n in buckets},
            },
        }
