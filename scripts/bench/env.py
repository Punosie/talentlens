"""Paths and an in-process ranking environment over the frozen benchmark snapshot."""

from __future__ import annotations

import json
import os
import sqlite3
from functools import cache
from pathlib import Path
from typing import Any

from talentlens.config import Settings

REPO = Path(__file__).resolve().parents[2]


def private_dir() -> Path:
    """Private benchmark root (git-ignored `bench-work/` in the repo): real names, profile cards,
    client JDs, gold sets and training data live here and must never be committed."""
    base = os.environ.get("TALENTLENS_BENCH_DIR")
    if base:
        return Path(base)
    return REPO / "bench-work"


def snapshot_db() -> Path:
    return private_dir() / "snapshot" / "talentlens.db"


def jd_dir() -> Path:
    return Path(os.environ.get("TALENTLENS_BENCH_JDS", private_dir() / "jds"))


def training_dir() -> Path:
    return private_dir() / "training"


def gold_dir() -> Path:
    return private_dir() / "gold"


def results_dir() -> Path:
    return private_dir() / "results"


def ro_connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path or snapshot_db()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def load_jds() -> dict[str, str]:
    """JDxx -> text, from the .txt files in the benchmark JD folder."""
    out = {}
    for p in sorted(jd_dir().glob("JD[0-9][0-9]*.txt")):
        out[p.name[:4]] = p.read_text(encoding="utf-8")
    return out


def load_gold(jd: str) -> tuple[dict[str, Any], dict[int, int]]:
    """Gold requirements and grades. Grades come from every judged batch file (pool rounds and
    later top-ups), with gold_ranking.json overrides (reviewed grades) applied last."""
    d = gold_dir() / jd
    req = json.loads((d / "gold_requirements.json").read_text(encoding="utf-8"))
    grades: dict[int, int] = {}
    for f in sorted((d / "judged").glob("*.json")):
        for j in json.loads(f.read_text(encoding="utf-8")):
            grades[int(j["id"])] = int(j["grade"])
    rk_path = d / "gold_ranking.json"
    if rk_path.exists():
        rk = json.loads(rk_path.read_text(encoding="utf-8"))
        grades.update({int(j["id"]): int(j["grade"]) for j in rk["judged"]})
    return req, grades


@cache
def shortlister() -> Any:
    """A Shortlister wired exactly like the app (GPU embedder + cross-encoder), on the snapshot."""
    from talentlens.ai import build_embedder, build_reranker
    from talentlens.db import Database
    from talentlens.search import SearchEngine
    from talentlens.shortlist import Shortlister

    s = Settings(data_dir=private_dir() / "snapshot" / "_data")
    db = Database(snapshot_db())
    embedder = build_embedder(s, "cuda")
    search = SearchEngine(db, embedder)
    return Shortlister(db, search, build_reranker(s, "cuda"))


def rank(req: dict[str, Any], jd_text: str, limit: int = 100, **opts: Any) -> list[dict[str, Any]]:
    from talentlens.jd import Requirements

    sl = shortlister()
    res = sl.rank(Requirements.from_dict(req), jd_text, limit=limit, **opts)
    return res["items"]
