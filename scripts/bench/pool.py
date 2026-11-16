"""Recall-oriented candidate pools for the gold standard.

    uv run python -m scripts.bench.pool [JD01 ...]

Union of:
  - app ranking top 100 with rules-mode requirements (the app's instant reading)
  - app ranking top 100 with the current AI reading (qwen2.5:3b-instruct, ctx 2048, 400 tokens)
  - app ranking top 100 with the Opus gold requirements
  - SQL role-family queries over titles / headlines / experience lines (capped)
Writes <gold>/JDxx/pool.json (ids + provenance) and baseline requirement files.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from .env import gold_dir, load_jds, rank, ro_connect

# role-family patterns (SQL LIKE on lower(title) or the profile's headline/experience text)
FAMILY: dict[str, dict[str, Any]] = {
    "JD01": {
        "title": [
            "%quality engineer%",
            "%qa %",
            "%qa%architect%",
            "%test%architect%",
            "%automation architect%",
            "%test automation%",
            "%sdet%",
            "%quality assurance%",
            "%head of qa%",
            "%head of quality%",
            "%testing%",
            "%qe %",
            "%qe lead%",
            "%test manager%",
            "%director%quality%",
            "%quality%director%",
        ],
        "text": [
            "%quality engineering transformation%",
            "%test automation framework%",
            "%playwright%",
            "%qa transformation%",
            "%testing practice%",
            "%testing coe%",
        ],
        "min_years": 12,
    },
    "JD02": {
        "title": [
            "%program manager%",
            "%programme manager%",
            "%delivery manager%",
            "%delivery head%",
            "%head of delivery%",
            "%delivery director%",
            "%transformation%",
            "%pmo%",
            "%program director%",
            "%programme director%",
            "%engagement manager%",
        ],
        "text": ["%test automation%program%", "%qa transformation%", "%testing%program manager%"],
        "min_years": 10,
    },
    "JD03": {
        "title": ["%sdet%", "%automation%", "%qa%", "%test%", "%quality%"],
        "text": ["%rest assured%", "%restassured%", "%testng%"],
        "min_years": 6,
        "max_years": 15,
    },
    "JD04": {
        "title": [
            "%delivery manager%",
            "%programme manager%",
            "%program manager%",
            "%delivery director%",
            "%head of delivery%",
            "%account delivery%",
            "%engagement manager%",
            "%delivery lead%",
        ],
        "text": ["%retail bank%delivery%", "%delivery%retail bank%"],
        "min_years": 10,
        "countries": ["United Kingdom"],
    },
    "JD05": {
        "title": [
            "%cloud architect%",
            "%solution architect%",
            "%solutions architect%",
            "%cloud solution%",
            "%azure architect%",
            "%aws architect%",
            "%infrastructure architect%",
            "%cloud consultant%",
            "%cloud lead%",
            "%platform architect%",
        ],
        "text": ["%landing zone%", "%cloud migration%"],
        "min_years": 8,
    },
    "JD06": {
        "title": [
            "%data engineer%",
            "%big data%",
            "%etl%",
            "%ml engineer%",
            "%machine learning engineer%",
            "%ai engineer%",
            "%analytics engineer%",
            "%pyspark%",
            "%databricks%",
        ],
        "text": ["%pyspark%", "%airflow%"],
        "min_years": 1.5,
        "max_years": 8,
    },
    "JD07": {
        "title": [
            "%devops%",
            "%site reliability%",
            "%sre%",
            "%platform engineer%",
            "%cloud engineer%",
            "%infrastructure%",
            "%kubernetes%",
            "%cloud ops%",
            "%cloudops%",
        ],
        "text": ["%kubernetes%"],
        "min_years": 6,
        "countries": ["United Arab Emirates", "Saudi Arabia", "Qatar", "Bahrain", "Kuwait", "Oman"],
    },
    "JD08": {
        "title": [
            "%presales%",
            "%pre-sales%",
            "%pre sales%",
            "%solution consult%",
            "%bid %",
            "%deal%",
            "%solutioning%",
            "%solution director%",
            "%solution head%",
            "%solutions director%",
            "%large deal%",
            "%proposal%",
        ],
        "text": ["%rfp%", "%deal shaping%", "%solutioning%"],
        "min_years": 13,
    },
    "JD09": {
        "title": ["%card%", "%payment%", "%acquiring%", "%issuing%"],
        "text": ["%tsys%", "%first data%", "%iso 8583%", "%card issuing%", "%card management%"],
        "min_years": 8,
    },
    "JD10": {
        "title": [
            "%client partner%",
            "%account director%",
            "%client director%",
            "%account executive%",
            "%relationship manager%",
            "%client relationship%",
            "%engagement director%",
            "%account manager%",
            "%client executive%",
            "%customer partner%",
            "%head of%financial services%",
            "%business development%",
        ],
        "text": ["%client partner%"],
        "min_years": 10,
        "countries": ["United States"],
    },
}
SQL_CAP = 150


def sql_hits(jd: str) -> list[int]:
    f = FAMILY[jd]
    head = "lower(coalesce(title,'') || ' ' || substr(coalesce(text,''), 1, 300))"
    conds = [f"{head} LIKE ?" for _ in f["title"]] + ["lower(text) LIKE ?" for _ in f["text"]]
    args: list[Any] = list(f["title"]) + list(f["text"])
    where = "(" + " OR ".join(conds) + ")"
    if f.get("min_years") is not None:
        where += " AND (years_exp IS NULL OR years_exp >= ?)"
        args.append(f["min_years"])
    if f.get("max_years") is not None:
        where += " AND (years_exp IS NULL OR years_exp <= ?)"
        args.append(f["max_years"])
    if f.get("countries"):
        where += f" AND country IN ({','.join('?' * len(f['countries']))})"
        args += f["countries"]
    with ro_connect() as conn:
        ids = [r[0] for r in conn.execute(f"SELECT id FROM cvs WHERE {where}", args)]
    return ids


def build(jd: str, text: str) -> dict[str, Any]:
    from talentlens.ai.llm import LLMUnavailable, OllamaLLM
    from talentlens.jd import parse_llm, parse_rules

    d = gold_dir() / jd
    gold_req = json.loads((d / "gold_requirements.json").read_text(encoding="utf-8"))
    rules_req = parse_rules(text).as_dict()
    try:  # the app as shipped today: default num_ctx 2048, max_tokens 400
        ai_req = parse_llm(
            OllamaLLM("http://127.0.0.1:11434", "qwen2.5:3b-instruct", 120), text
        ).as_dict()
    except LLMUnavailable as e:
        ai_req = {"error": str(e)}
    (d / "baseline_rules_requirements.json").write_text(
        json.dumps(rules_req, indent=2), encoding="utf-8"
    )
    (d / "baseline_qwen3b_requirements.json").write_text(
        json.dumps(ai_req, indent=2), encoding="utf-8"
    )

    prov: dict[int, list[str]] = {}

    def add(ids: list[int], tag: str) -> None:
        for i in ids:
            prov.setdefault(int(i), []).append(tag)

    add([it["id"] for it in rank(rules_req, text, limit=100)], "app_rules")
    if "error" not in ai_req:
        add([it["id"] for it in rank(ai_req, text, limit=100)], "app_ai_qwen3b")
    gold_ranked = rank(gold_req, text, limit=400)
    add([it["id"] for it in gold_ranked[:100]], "app_gold_req")
    # SQL hits: keep those the gold-requirement ranking scores best, capped
    hits = set(sql_hits(jd))
    order = {it["id"]: n for n, it in enumerate(gold_ranked)}
    sql_sorted = sorted(hits, key=lambda i: order.get(i, 10_000 + i))
    add(sql_sorted[:SQL_CAP], "sql_family")
    pool = {
        "jd": jd,
        "size": len(prov),
        "sql_hits_total": len(hits),
        "sources": {
            t: sum(1 for v in prov.values() if t in v)
            for t in ("app_rules", "app_ai_qwen3b", "app_gold_req", "sql_family")
        },
        "ids": prov,
    }
    (d / "pool.json").write_text(json.dumps(pool, indent=2), encoding="utf-8")
    return pool


# Round 2 (added after the JD01 sanity check showed the 150 cap dropped real matches):
# every title-pattern hit not already pooled, narrowed by the JD's own hard-ish constraints
# where the family is very large.
ROUND2_EXTRA: dict[str, str] = {
    "JD02": "(lower(text) LIKE '%bank%' OR lower(text) LIKE '%financial%') AND years_exp >= 12",
    "JD06": "country = 'India' AND years_exp BETWEEN 2 AND 7.5",
    "JD10": "(lower(text) LIKE '%financial services%' OR lower(text) LIKE '%banking%' "
    "OR lower(text) LIKE '%bfsi%' OR lower(text) LIKE '%insurance%') "
    "AND lower(title) NOT LIKE '%sales associate%'",
}
ROUND2_CAP = 160


def round2(jd: str) -> list[int]:
    f = FAMILY[jd]
    d = gold_dir() / jd
    pool = json.loads((d / "pool.json").read_text(encoding="utf-8"))
    have = {int(i) for i in pool["ids"]}
    conds = " OR ".join(["lower(coalesce(title,'')) LIKE ?"] * len(f["title"]))
    args: list[Any] = list(f["title"])
    where = f"({conds})"
    if f.get("min_years") is not None:
        where += " AND (years_exp IS NULL OR years_exp >= ?)"
        args.append(f["min_years"])
    if f.get("max_years") is not None:
        where += " AND (years_exp IS NULL OR years_exp <= ?)"
        args.append(f["max_years"])
    if f.get("countries"):
        where += f" AND country IN ({','.join('?' * len(f['countries']))})"
        args += f["countries"]
    if jd in ROUND2_EXTRA:
        where += f" AND ({ROUND2_EXTRA[jd]})"
    with ro_connect() as conn:
        ids = [r[0] for r in conn.execute(f"SELECT id FROM cvs WHERE {where}", args)]
    if jd == "JD01":  # small family: take every SQL hit (title + text patterns)
        ids += sql_hits(jd)
    new = sorted({i for i in ids if i not in have})[:ROUND2_CAP]
    for i in new:
        pool["ids"][str(i)] = ["sql_family_r2"]
    pool["size"] = len(pool["ids"])
    pool["sources"]["sql_family_r2"] = len(new)
    (d / "pool.json").write_text(json.dumps(pool, indent=2), encoding="utf-8")
    return new


if __name__ == "__main__":
    jds = load_jds()
    args = sys.argv[1:]
    if args and args[0] == "--round2":
        from .batches import make

        for jd in args[1:] or list(jds):
            new = round2(jd)
            n = make(jd, new, 34, prefix="c") if new else 0
            print(jd, "round2 +", len(new), "->", n, "batches", flush=True)
    else:
        for jd in args or list(jds):
            p = build(jd, jds[jd])
            print(jd, p["size"], p["sql_hits_total"], p["sources"], flush=True)
