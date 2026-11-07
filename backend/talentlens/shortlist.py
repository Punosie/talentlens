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

import json
import re
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from .ai import taxonomy
from .ai.rerank import Reranker
from .db import Database, loads_list
from .enrich import CVFields
from .indexer import embedding_text
from .jd import Requirements
from .search import RRF_K, SearchEngine
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
RERANK_K = 60


@dataclass
class Candidate:
    id: int
    row: Any
    cosine: float = 0.0
    rerank: float = 0.0
    fused: float = 0.0


def _skill_hits(required: list[str], cv_skills: list[str], text_lower: str) -> list[str]:
    """Which required skills the CV has: from its skills list, or mentioned in its text."""
    have = {s.lower() for s in cv_skills}
    tax = taxonomy.skills()
    hits: list[str] = []
    for req in required:
        if req.lower() in have:
            hits.append(req)
            continue
        # free-text requirement or alias: look for it in the CV text as a whole word
        if len(req) >= 3 and re.search(
            rf"(?<![\w+#]){re.escape(req.lower())}(?![\w+#])", text_lower
        ):
            hits.append(req)
            continue
        canon = tax.canonicalize(req)
        if canon and canon.lower() in have:
            hits.append(req)
    return hits


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


def location_score(city: str | None, country: str | None, wanted: list[str]) -> float:
    if not wanted:
        return 1.0
    gz = taxonomy.gazetteer()
    w = {x.lower() for x in wanted}
    if city and city.lower() in w:
        return 1.0
    if country and country.lower() in w:
        return 1.0
    wanted_countries = {(gz.city_country.get(x) or x).lower() for x in wanted}
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
        self, req: Requirements, jd_text: str, *, limit: int = 50, min_score: float = 0.0
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        query = req.query_text() or jd_text[:1500]
        with self.db.connect() as conn:
            rows = {
                r["id"]: r
                for r in conn.execute(
                    f"SELECT {SUMMARY_COLUMNS}, text FROM cvs WHERE status='indexed'"
                )
            }
            if not rows:
                return {"total": 0, "items": [], "timings": {}}
            ids = list(rows)

            # 1) dense: JD summary + start of JD text
            dense_q = f"{query}\n\n{jd_text[:1500]}" if jd_text else query
            sims = self.search.vectors.similarities(self.search.embedder.embed_query(dense_q), ids)
            dense = sorted(sims.items(), key=lambda kv: kv[1], reverse=True)
            # 2) lexical over skills
            skill_q = " ".join(req.must_have_skills + req.nice_to_have_skills) or query
            lex = self.search.lexical(conn, skill_q, set(ids), limit=300)

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
                hits = _skill_hits(
                    req.must_have_skills, loads_list(row["skills"]), (row["text"] or "").lower()
                )
                if len(hits) >= need:
                    cands[cid] = Candidate(
                        cid, row, cosine=sims.get(cid, 0.0), fused=fused.get(cid, 0)
                    )
        t_retrieve = time.perf_counter() - t0

        # 3) cross-encoder rerank of the best fused candidates
        order = sorted(cands.values(), key=lambda c: c.fused, reverse=True)
        top = order[:RERANK_K]
        t1 = time.perf_counter()
        if top:
            docs = [self._doc(c.row) for c in top]
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
        items = []
        for c in cands.values():
            row = c.row
            cv_skills = loads_list(row["skills"])
            text_lower = (row["text"] or "").lower()
            must_hits = _skill_hits(req.must_have_skills, cv_skills, text_lower)
            nice_hits = _skill_hits(req.nice_to_have_skills, cv_skills, text_lower)
            sem_cos = norm(c.cosine, cos_lo, cos_hi)
            sem = (
                0.5 * sem_cos + 0.5 * norm(c.rerank, rr_lo, rr_hi)
                if c.id in reranked
                else 0.6 * sem_cos
            )
            parts = {
                "semantic": sem,
                "must": len(must_hits) / len(req.must_have_skills) if req.must_have_skills else 1.0,
                "nice": len(nice_hits) / len(req.nice_to_have_skills)
                if req.nice_to_have_skills
                else 1.0,
                "experience": experience_score(row["years_exp"], req.min_years, req.max_years),
                "domain": domain_score(loads_list(row["domains"]), req.domains),
                "location": location_score(row["city"], row["country"], req.locations),
            }
            score = sum(WEIGHTS[k] * v for k, v in parts.items())
            if score < min_score:
                continue
            item = cv_summary(row)
            item.update(
                score=round(score, 1),
                breakdown={k: round(WEIGHTS[k] * v, 1) for k, v in parts.items()},
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
            "timings": {
                "retrieve_s": round(t_retrieve, 2),
                "rerank_s": round(t_rerank, 2),
                "total_s": round(time.perf_counter() - t0, 2),
                "reranked": len(top),
            },
        }

    @staticmethod
    def _doc(row: Any) -> str:
        f = CVFields(
            title=row["title"],
            years_exp=row["years_exp"],
            location=row["location"],
            skills=loads_list(row["skills"]),
            domains=loads_list(row["domains"]),
            summary=row["summary"],
        )
        return embedding_text(f, row["text"] or "")[:2500]


def _person_key(item: dict[str, Any]) -> str | None:
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
                {"id": it["id"], "filename": it["filename"]}
            )
            continue
        if key:
            by_key[key] = it
        keep.append(it)
    return keep


# --- explanations -------------------------------------------------------------
EXPLAIN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reason": {"type": "string"},
        "strengths": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
        "gaps": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
    },
    "required": ["reason", "strengths", "gaps"],
}

EXPLAIN_SYSTEM = (
    "You are a precise recruiting assistant. Compare the candidate's resume with the job "
    "requirements and return ONLY JSON: 'reason' (max 40 words, neutral, factual), up to 4 "
    "short 'strengths' and up to 4 short 'gaps'. Base every point on the resume text; never "
    "invent facts."
)


def explain(llm: Any, req: Requirements, cv_row: Any) -> dict[str, Any]:
    user = (
        f"Job requirements:\n{json.dumps(req.as_dict(), ensure_ascii=False)}\n\n"
        f"Candidate resume:\n<<<\n{(cv_row['text'] or '')[:5000]}\n>>>"
    )
    data = llm.json_chat(EXPLAIN_SYSTEM, user, EXPLAIN_SCHEMA, max_tokens=300)
    return {
        "reason": str(data.get("reason") or "").strip(),
        "strengths": [str(s) for s in data.get("strengths") or []][:4],
        "gaps": [str(s) for s in data.get("gaps") or []][:4],
    }
