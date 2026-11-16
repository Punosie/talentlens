"""Rank resumes against JD requirements.

Pipeline:
1. Semantic retrieval: embed the JD and compare it with every indexed CV.
2. Lexical retrieval: BM25 over the must-have skills.
3. RRF fusion, then keep the top candidates plus anyone covering at least half the must-haves.
4. Cross-encoder rerank of the top N.
5. Explicit, explainable score:
   35 semantic, 30 must-have coverage, 10 nice-to-have, 10 experience, 8 domain, 7 location.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import numpy as np

from .ai import taxonomy
from .ai.rerank import Reranker
from .db import Database, loads_list
from .enrich import CVFields
from .indexer import embedding_text
from .jd import Requirements
from .search import RRF_K, Filters, SearchEngine
from .serializers import SUMMARY_COLUMNS, cv_summary

WEIGHTS = {
    "semantic": 35.0,
    "must": 30.0,
    "nice": 10.0,
    "experience": 10.0,
    "domain": 8.0,
    "location": 7.0,
}
RETRIEVE_K = 120
RERANK_K = 30  # cross-encoder only for the closest candidates...
RERANK_MARGIN = 0.15  # ...within this cosine distance of the best match
RERANK_CHARS = 1200  # text per candidate given to the cross-encoder


@dataclass(frozen=True)
class RankOptions:
    """Ranking switches measured by scripts/bench_llm.py (defaults = the original behaviour).

    years_mode: "soft" (score component only), "hard" (drop candidates more than `years_tol`
    years outside a stated min/max) or "strong" (keep them but multiply their score by
    `years_penalty`). Unknown years are never dropped.
    role_weight: weight of a role-family match between the JD (role_family, else title) and the
    candidate's title (embedding similarity), added to the explicit score.
    """

    years_mode: str = "soft"
    years_tol: float = 2.0
    years_penalty: float = 0.6
    role_weight: float = 0.0


DEFAULT_OPTIONS = RankOptions()


def years_outside(years: float | None, lo: float | None, hi: float | None, tol: float) -> bool:
    if years is None:
        return False
    if lo is not None and years < lo - tol:
        return True
    return hi is not None and years > hi + tol


@dataclass
class Candidate:
    id: int
    row: Any
    cosine: float = 0.0
    rerank: float = 0.0
    fused: float = 0.0


def _skill_hits(
    required: list[str], cv_skills: list[str], cv_id: int, text_hits: dict[str, set[int]]
) -> list[str]:
    """Which required skills the CV has: from its skills list, its canonical form, or (for
    free-text requirements) a whole-phrase match in its text, found up front via the FTS index."""
    have = {s.lower() for s in cv_skills}
    tax = taxonomy.skills()
    hits: list[str] = []
    for req in required:
        canon = tax.canonicalize(req)
        if (
            req.lower() in have
            or (canon and canon.lower() in have)
            or cv_id in text_hits.get(req, ())
        ):
            hits.append(req)
    return hits


def _phrase_hits(conn: Any, phrases: list[str]) -> dict[str, set[int]]:
    """CV ids whose text contains each phrase (FTS5 phrase query: no full-text scan)."""
    out: dict[str, set[int]] = {}
    for p in phrases:
        tokens = re.findall(r"[\w+#.]+", p)
        if not tokens or len(p) < 3:
            continue
        q = '"' + " ".join(t.replace('"', "") for t in tokens) + '"'
        try:
            out[p] = {
                r[0] for r in conn.execute("SELECT rowid FROM cv_fts WHERE cv_fts MATCH ?", (q,))
            }
        except Exception:  # odd tokens FTS can't parse: just no text hits
            out[p] = set()
    return out


def experience_score(years: float | None, lo: float | None, hi: float | None) -> float:
    if lo is None and hi is None:
        return 1.0
    if years is None:
        return 0.4
    if lo is not None and years < lo:
        return max(0.0, 1.0 - (lo - years) / max(lo, 2.0))
    if hi is not None and years > hi:
        return max(0.5, 1.0 - (years - hi) / 10.0)
    return 1.0


def location_score(
    city: str | None, country: str | None, wanted: list[str], full: str | None = None
) -> float:
    """1.0 in a wanted place (city, country, or a state/region in the full written location),
    0.7 elsewhere in the same country, else 0."""
    if not wanted:
        return 1.0
    if any(taxonomy.location_matches(x, city, country, full) for x in wanted):
        return 1.0
    gz = taxonomy.gazetteer()
    wanted_countries = set()
    for x in wanted:
        wanted_countries.add((gz.city_country.get(x) or x).lower())
        if x.upper() in taxonomy.US_STATES or x.lower() in {
            s.lower() for s in taxonomy.US_STATES.values()
        }:
            wanted_countries.add("united states")
    if country and country.lower() in wanted_countries:
        return 0.7
    return 0.0


def domain_score(cv_domains: list[str], wanted: list[str]) -> float:
    if not wanted:
        return 1.0
    have = {d.lower() for d in cv_domains}
    return 1.0 if any(d.lower() in have for d in wanted) else 0.0


class Shortlister:
    def __init__(self, db: Database, search: SearchEngine, reranker: Reranker) -> None:
        self.db = db
        self.search = search
        self.reranker = reranker

    def rank(
        self,
        req: Requirements,
        jd_text: str,
        *,
        limit: int = 50,
        min_score: float = 0.0,
        rerank: bool = True,
        sources: list[str] | None = None,
        owners: list[str] | None = None,
        options: RankOptions = DEFAULT_OPTIONS,
        filters: Filters | None = None,
    ) -> dict[str, Any]:
        """rerank=False: embeddings + skills only. rerank=True (what the UI uses) also re-scores the
        closest candidates with the cross-encoder, so the list is shown once, in its final order."""
        t0 = time.perf_counter()
        query = req.query_text() or jd_text[:1500]
        # who may be ranked at all: the user's filters (hard) plus the source/owner scope
        scope = filters or Filters()
        if sources:
            scope.sources = list(sources)
        if owners:
            scope.owners = list(owners)
        scope_sql, scope_args = scope.sql()
        with self.db.connect() as conn:
            rows = {
                r["id"]: r
                for r in conn.execute(
                    f"SELECT {SUMMARY_COLUMNS} FROM cvs c WHERE {scope_sql}", scope_args
                )
            }
            if not rows:
                return {"total": 0, "items": [], "timings": {}, "refined": rerank}
            ids = list(rows)

            # 1) dense: JD summary + start of JD text
            dense_q = f"{query}\n\n{jd_text[:1500]}" if jd_text else query
            sims = self.search.vectors.similarities(self.search.embedder.embed_query(dense_q), ids)
            dense = sorted(sims.items(), key=lambda kv: kv[1], reverse=True)
            # 2) lexical over skills
            skill_q = " ".join(req.must_have_skills + req.nice_to_have_skills) or query
            lex = self.search.lexical(conn, skill_q, set(ids), limit=300)
            # 3) free-text requirement phrases, resolved once through the FTS index
            text_hits = _phrase_hits(conn, req.must_have_skills + req.nice_to_have_skills)

        fused: dict[int, float] = {}
        for rank, (cid, _) in enumerate(dense):
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (RRF_K + rank + 1)
        for rank, (cid, _) in enumerate(lex):
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (RRF_K + rank + 1)

        cands: dict[int, Candidate] = {}
        for cid in sorted(fused, key=lambda c: fused[c], reverse=True)[:RETRIEVE_K]:
            cands[cid] = Candidate(cid, rows[cid], cosine=sims.get(cid, 0.0), fused=fused[cid])
        # never drop someone who covers at least half of the must-haves
        if req.must_have_skills:
            need = max(1, len(req.must_have_skills) // 2)
            for cid, row in rows.items():
                if cid in cands:
                    continue
                hits = _skill_hits(req.must_have_skills, loads_list(row["skills"]), cid, text_hits)
                if len(hits) >= need:
                    cands[cid] = Candidate(
                        cid, row, cosine=sims.get(cid, 0.0), fused=fused.get(cid, 0)
                    )
        t_retrieve = time.perf_counter() - t0

        # 4) cross-encoder rerank, only for candidates close to the best (adaptive, capped)
        top: list[Candidate] = []
        t1 = time.perf_counter()
        if rerank and cands:
            order = sorted(cands.values(), key=lambda c: c.fused, reverse=True)
            best_cos = max(c.cosine for c in cands.values())
            top = [c for c in order if c.cosine >= best_cos - RERANK_MARGIN][:RERANK_K]
            texts = self._texts([c.id for c in top])
            docs = [self._doc(c.row, texts.get(c.id, "")) for c in top]
            scores = self.reranker.scores(query, docs)
            for c, s in zip(top, scores, strict=True):
                c.rerank = float(s)
        t_rerank = time.perf_counter() - t1

        # 4) explicit scoring
        rr = np.array([c.rerank for c in top]) if top else np.zeros(0)
        rr_lo, rr_hi = (float(rr.min()), float(rr.max())) if len(rr) else (0.0, 1.0)
        cos = np.array([c.cosine for c in cands.values()])
        cos_lo, cos_hi = (float(cos.min()), float(cos.max())) if len(cos) else (0.0, 1.0)

        def norm(v: float, lo: float, hi: float) -> float:
            return (v - lo) / (hi - lo) if hi > lo else 1.0

        reranked = {c.id for c in top}
        role_sim = self._role_similarity(req, cands, options) if options.role_weight else {}
        items = []
        for c in cands.values():
            row = c.row
            outside = years_outside(
                row["years_exp"], req.min_years, req.max_years, options.years_tol
            )
            if outside and options.years_mode == "hard":
                continue
            cv_skills = loads_list(row["skills"])
            must_hits = _skill_hits(req.must_have_skills, cv_skills, c.id, text_hits)
            nice_hits = _skill_hits(req.nice_to_have_skills, cv_skills, c.id, text_hits)
            sem_cos = norm(c.cosine, cos_lo, cos_hi)
            if not rerank:
                sem = sem_cos  # quick pass: embedding similarity only
            elif c.id in reranked:
                sem = 0.5 * sem_cos + 0.5 * norm(c.rerank, rr_lo, rr_hi)
            else:
                sem = 0.6 * sem_cos  # far from the best match: not worth reranking
            parts = {
                "semantic": sem,
                "must": len(must_hits) / len(req.must_have_skills) if req.must_have_skills else 1.0,
                "nice": len(nice_hits) / len(req.nice_to_have_skills)
                if req.nice_to_have_skills
                else 1.0,
                "experience": experience_score(row["years_exp"], req.min_years, req.max_years),
                "domain": domain_score(loads_list(row["domains"]), req.domains),
                "location": location_score(
                    row["city"], row["country"], req.locations, row["location_full"]
                ),
            }
            weights = dict(WEIGHTS)
            if options.role_weight:
                parts["role"] = role_sim.get(c.id, 0.0)
                weights["role"] = options.role_weight
            score = sum(weights[k] * v for k, v in parts.items())
            if outside and options.years_mode == "strong":
                score *= options.years_penalty
            if score < min_score:
                continue
            item = cv_summary(row)
            item.update(
                score=round(score, 1),
                breakdown={k: round(weights[k] * v, 1) for k, v in parts.items()},
                matched_must=must_hits,
                missing_must=[s for s in req.must_have_skills if s not in must_hits],
                matched_nice=nice_hits,
            )
            items.append(item)

        items.sort(key=lambda i: i["score"], reverse=True)
        items = _collapse_duplicates(items)
        for rank, it in enumerate(items, start=1):
            it["rank"] = rank
        return {
            "total": len(items),
            "items": items[:limit],
            "weights": WEIGHTS,
            "refined": rerank,
            "timings": {
                "retrieve_s": round(t_retrieve, 2),
                "rerank_s": round(t_rerank, 2),
                "total_s": round(time.perf_counter() - t0, 2),
                "reranked": len(top),
            },
        }

    def _role_similarity(
        self, req: Requirements, cands: dict[int, Candidate], options: RankOptions
    ) -> dict[int, float]:
        """How close each candidate's own title is to the job's real role family (0..1).

        The JD title can mislead ("Enterprise Architect" for a QE-leadership role), so the
        role_family the LLM extracted is preferred; the title is the fallback."""
        role = (req.role_family or req.title or "").strip()
        if not role or not cands:
            return {}
        ids = list(cands)
        titles = [(cands[i].row["title"] or "").strip() for i in ids]
        have = [k for k, t in enumerate(titles) if t]
        if not have:
            return {}
        emb = self.search.embedder
        q = np.asarray(emb.embed_query(role), dtype=np.float32)
        docs = np.asarray(emb.embed_documents([titles[k] for k in have]), dtype=np.float32)
        sims = docs @ q
        lo, hi = float(sims.min()), float(sims.max())
        out: dict[int, float] = {}
        for k, s in zip(have, sims, strict=True):
            out[ids[k]] = (float(s) - lo) / (hi - lo) if hi > lo else 1.0
        return out

    def _texts(self, ids: list[int]) -> dict[int, str]:
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        with self.db.connect() as conn:
            return {
                r[0]: r[1] or ""
                for r in conn.execute(
                    f"SELECT id, substr(text, 1, 2500) FROM cvs WHERE id IN ({marks})", ids
                )
            }

    @staticmethod
    def _doc(row: Any, text: str) -> str:
        f = CVFields(
            title=row["title"],
            years_exp=row["years_exp"],
            location=row["location"],
            skills=loads_list(row["skills"]),
            domains=loads_list(row["domains"]),
            summary=row["summary"],
        )
        # title, skills, years and summary come first; the cross-encoder cost grows with length,
        # and the start of a profile carries nearly all of the signal
        return embedding_text(f, text)[:RERANK_CHARS]


def _person_key(item: dict[str, Any]) -> str | None:
    if item.get("person_id"):  # same person in the connections database (LinkedIn + their CV)
        return "p:" + str(item["person_id"]).lower()
    if item.get("email"):
        return "e:" + item["email"].lower()
    name = re.sub(r"[^a-z]", "", (item.get("name") or "").lower())
    if len(name) >= 6:
        return f"n:{name}:{item.get('years_exp')}"
    return None


def _collapse_duplicates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Several files of the same person (CV.pdf, CV-1.pdf) appear once; extras are listed."""
    keep: list[dict[str, Any]] = []
    by_key: dict[str, dict[str, Any]] = {}
    for it in items:  # already sorted best-first
        key = _person_key(it)
        if key and key in by_key:
            by_key[key].setdefault("other_files", []).append(
                {"id": it["id"], "filename": it["filename"], "source": it.get("source", "file")}
            )
            continue
        if key:
            by_key[key] = it
        keep.append(it)
    return keep


# --- explanations (streamed plain text, so the first words appear within about a second) ---
EXPLAIN_SYSTEM = (
    "You are a precise recruiting assistant. Compare the candidate with the job requirements. "
    "Answer in exactly three short lines and nothing else:\n"
    "Verdict: <one neutral sentence, max 25 words>\n"
    "Strengths: <2-3 short points separated by '; '>\n"
    "Gaps: <1-3 short points separated by '; ', or 'none'>\n"
    "Base every point on the resume; never invent facts."
)


def _req_brief(req: Requirements) -> str:
    parts = [
        f"Role: {req.title}" if req.title else "",
        f"Must have: {', '.join(req.must_have_skills)}" if req.must_have_skills else "",
        f"Nice to have: {', '.join(req.nice_to_have_skills)}" if req.nice_to_have_skills else "",
        f"Experience: {req.min_years:g}+ years" if req.min_years else "",
        f"Location: {', '.join(req.locations)}" if req.locations else "",
        f"Industry: {', '.join(req.domains)}" if req.domains else "",
    ]
    return "\n".join(p for p in parts if p)


def explain_stream(llm: Any, req: Requirements, cv_text: str) -> Iterator[str]:
    user = (
        f"Job requirements:\n{_req_brief(req)}\n\n"
        f"Candidate resume (start):\n<<<\n{cv_text[:3500]}\n>>>"
    )
    yield from llm.text_stream(EXPLAIN_SYSTEM, user, max_tokens=160)
