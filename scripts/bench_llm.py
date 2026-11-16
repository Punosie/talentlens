"""Benchmark local LLMs (Ollama) for TalentLens against the Opus gold standard.

    uv run python scripts/bench_llm.py run --models qwen3:8b-q4_K_M [--tasks extract,judge]
    uv run python scripts/bench_llm.py run --models all --rm-after
    uv run python scripts/bench_llm.py appbase   # the app as shipped (qwen2.5:3b, ctx 2048)
    uv run python scripts/bench_llm.py rank      # Task B for every stored extraction + fixes
    uv run python scripts/bench_llm.py unjudged  # candidates in a top 10 the gold hasn't judged
    uv run python scripts/bench_llm.py report    # leaderboard CSVs

Task A: JD extraction vs gold requirements.     Task B: end-to-end ranking from each model's
requirements.  Task C: the model grades a fixed top-50 per JD; re-ranked by grade.
Inputs: benchmark JDs (TALENTLENS_BENCH_JDS), gold + snapshot (TALENTLENS_BENCH_DIR, default
%LOCALAPPDATA%\\TalentLens\\benchmarks). Raw results with real ids stay in that private folder;
`report` writes anonymised aggregates to benchmarks/results/ in the repo.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.bench import prompts
from scripts.bench.cards import cards, render
from scripts.bench.env import gold_dir, load_gold, load_jds, rank, results_dir
from scripts.bench.metrics import agreement, extraction_scores, ranking_scores
from scripts.bench.models import (
    ROSTER,
    SHORTLIST,
    THINKING_VARIANTS,
    by_tag,
    installed,
    pull,
    remove,
)
from scripts.bench.ollama_client import MemSampler, chat_json, unload

REPO_RESULTS = Path(__file__).resolve().parents[1] / "benchmarks" / "results"
JUDGE_K = 50
CARD_CHARS = 2000


def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9.]+", "_", s).strip("_")


def save(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8")


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ Task A
def to_req(data: dict[str, Any], text: str) -> dict[str, Any]:
    from talentlens.jd import parse_rules, requirements_from_llm

    return requirements_from_llm(data, text, parse_rules(text)).as_dict()


def task_extract(
    model: str,
    *,
    think: bool | None,
    prompt: str = "v2",
    num_ctx: int = 8192,
    max_tokens: int = 1200,
    tag: str = "",
    repeats: int = 1,
) -> dict[str, Any]:
    from talentlens.jd import JD_SCHEMA, JD_SYSTEM, MAX_JD_CHARS

    jds = load_jds()
    out: dict[str, Any] = {
        "model": model,
        "think": think,
        "prompt": prompt,
        "num_ctx": num_ctx,
        "max_tokens": max_tokens,
        "runs": [],
    }
    for _rep in range(repeats):
        per: dict[str, Any] = {}
        for jd, text in jds.items():
            if prompt == "app":
                system, schema = JD_SYSTEM, JD_SCHEMA
                user = f"Job description:\n<<<\n{text[:MAX_JD_CHARS]}\n>>>"
            else:
                system, schema, user = (
                    prompts.JD_SYSTEM_V2,
                    prompts.JD_SCHEMA_V2,
                    prompts.jd_user(text),
                )
            mt = max(max_tokens, 4096) if think else max_tokens
            r = chat_json(model, system, user, schema, num_ctx=num_ctx, max_tokens=mt, think=think)
            gold_req, _ = load_gold(jd)
            req = to_req(r.data, text) if r.ok else None
            per[jd] = {
                "ok": r.ok,
                "error": r.error,
                "data": r.data,
                "req": req,
                "scores": extraction_scores(req, gold_req, text) if req else None,
                "stats": {
                    "wall_s": r.wall_s,
                    "tok_s": r.tok_per_s,
                    "eval_tokens": r.eval_tokens,
                    "prompt_tokens": r.prompt_tokens,
                    "load_s": r.load_s,
                    "thinking_chars": r.thinking_chars,
                },
            }
            print(f"  A {jd} ok={r.ok} {r.wall_s:5.1f}s {r.tok_per_s:5.1f} tok/s", flush=True)
        out["runs"].append(per)
    name = f"{slug(model)}__{prompt}_ctx{num_ctx}_mt{max_tokens}{'_think' if think else ''}{tag}"
    save(results_dir() / "extract" / f"{name}.json", out)
    return out


# ------------------------------------------------------------------ Task C
def judge_candidates() -> dict[str, list[int]]:
    """Fixed top-50 per JD: the app's ranking from the gold requirements (same for every model)."""
    p = results_dir() / "judge" / "_candidates.json"
    if p.exists():
        return {k: [int(x) for x in v] for k, v in load(p).items()}
    jds = load_jds()
    out = {}
    for jd, text in jds.items():
        gold_req, _ = load_gold(jd)
        out[jd] = [it["id"] for it in rank(gold_req, text, limit=JUDGE_K)]
    save(p, out)
    return out


def rerank_by_grade(ids: list[int], grades: dict[int, int]) -> list[int]:
    pos = {cid: n for n, cid in enumerate(ids)}  # app order breaks ties
    return sorted(ids, key=lambda c: (-grades.get(c, -1), pos[c]))


def task_judge(
    model: str, *, think: bool | None, variant: str = "zero", tag: str = ""
) -> dict[str, Any]:
    jds = load_jds()
    cand = judge_candidates()
    out: dict[str, Any] = {"model": model, "think": think, "variant": variant, "jds": {}}
    mt = 4096 if think else (400 if variant == "cot" else 200)
    for jd, text in jds.items():
        ids = cand[jd]
        cs = {c["id"]: render(c).split("\n", 1)[1] for c in cards(ids, chars=CARD_CHARS)}
        grades: dict[int, int] = {}
        reasons: dict[int, str] = {}
        stats = {"calls": 0, "fail": 0, "wall_s": 0.0, "eval_tokens": 0, "eval_s": 0.0}
        if variant == "listwise":
            for k in range(0, len(ids), 5):
                chunk = [(cid, cs.get(cid, "")) for cid in ids[k : k + 5]]
                r = chat_json(
                    model,
                    prompts.JUDGE_SYSTEM,
                    prompts.listwise_user(text, chunk),
                    prompts.LISTWISE_SCHEMA,
                    num_ctx=16384,
                    max_tokens=max(mt, 900),
                    think=think,
                )
                stats["calls"] += 1
                stats["wall_s"] += r.wall_s
                stats["eval_tokens"] += r.eval_tokens
                stats["eval_s"] += r.eval_s
                if not r.ok:
                    stats["fail"] += 1
                    continue
                for g in r.data.get("grades", []):
                    try:
                        cid, gr = int(g["id"]), int(g["grade"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if cid in cs and 0 <= gr <= 3:
                        grades[cid], reasons[cid] = gr, str(g.get("reason", ""))[:200]
        else:
            system = prompts.JUDGE_SYSTEM_COT if variant == "cot" else prompts.JUDGE_SYSTEM
            schema = prompts.JUDGE_SCHEMA_COT if variant == "cot" else prompts.JUDGE_SCHEMA
            for cid in ids:
                user = prompts.judge_user(
                    text, cs.get(cid, ""), with_fewshot=(variant == "fewshot")
                )
                r = chat_json(model, system, user, schema, num_ctx=8192, max_tokens=mt, think=think)
                stats["calls"] += 1
                stats["wall_s"] += r.wall_s
                stats["eval_tokens"] += r.eval_tokens
                stats["eval_s"] += r.eval_s
                try:
                    g = int(r.data["grade"]) if r.ok else -1
                except (KeyError, TypeError, ValueError):
                    g = -1
                if 0 <= g <= 3:
                    grades[cid], reasons[cid] = g, str(r.data.get("reason", ""))[:200]
                else:
                    stats["fail"] += 1
        _, gold = load_gold(jd)
        order = rerank_by_grade(ids, grades)
        out["jds"][jd] = {
            "grades": grades,
            "reasons": reasons,
            "order": order,
            "stats": stats,
            "rank": ranking_scores(order, gold),
            "app_rank": ranking_scores(ids, gold),
            "agree": agreement(grades, gold),
        }
        m = out["jds"][jd]
        print(
            f"  C {jd} nDCG {m['app_rank']['ndcg10']:.2f}->{m['rank']['ndcg10']:.2f} "
            f"qwk {m['agree']['qwk']:.2f} fail {stats['fail']} {stats['wall_s']:.0f}s",
            flush=True,
        )
    name = f"{slug(model)}__{variant}{'_think' if think else ''}{tag}"
    save(results_dir() / "judge" / f"{name}.json", out)
    return out


# ------------------------------------------------------------------ Task B + code fixes
FIXES: dict[str, dict[str, Any]] = {
    "base": {},
    "hard_years": {"years_mode": "hard"},
    "strong_years": {"years_mode": "strong"},
    "role10": {"role_weight": 10.0},
    "role20": {"role_weight": 20.0},
    "hard_role20": {"years_mode": "hard", "role_weight": 20.0},
    "strong_role20": {"years_mode": "strong", "role_weight": 20.0},
}


def task_rank(sources: list[Path], fixes: list[str]) -> None:
    from talentlens.shortlist import RankOptions

    jds = load_jds()
    for src in sources:
        ex = load(src)
        run = ex["runs"][0]
        for fx in fixes:
            opts = RankOptions(**FIXES[fx])
            res: dict[str, Any] = {"source": src.stem, "fix": fx, "jds": {}}
            for jd, text in jds.items():
                req = run.get(jd, {}).get("req")
                if not req:
                    res["jds"][jd] = None
                    continue
                items = rank(req, text, limit=50, options=opts)
                ids = [it["id"] for it in items]
                _, gold = load_gold(jd)
                res["jds"][jd] = {"ids": ids, "rank": ranking_scores(ids, gold)}
            save(results_dir() / "rank" / f"{src.stem}__{fx}.json", res)
            nd = [v["rank"]["ndcg10"] for v in res["jds"].values() if v]
            print(f"B {src.stem} {fx}: nDCG@10 {statistics.mean(nd):.3f}", flush=True)


def baseline_sources() -> None:
    """Rules-only and gold requirements stored in the same 'extract' shape for Task B."""
    from talentlens.jd import parse_rules

    jds = load_jds()
    for name, fn in (
        ("rules", lambda jd, t: parse_rules(t).as_dict()),
        ("opus_gold", lambda jd, t: load_gold(jd)[0]),
    ):
        per = {}
        for jd, text in jds.items():
            req = fn(jd, text)
            per[jd] = {
                "ok": True,
                "req": req,
                "scores": extraction_scores(req, load_gold(jd)[0], text),
            }
        save(results_dir() / "extract" / f"{name}.json", {"model": name, "runs": [per]})


# ------------------------------------------------------------------ driver
def run_model(
    model: str, tasks: list[str], *, think: bool | None, variants: list[str], rm_after: bool
) -> None:
    if model not in installed():
        print(f"pulling {model}", flush=True)
        t = time.perf_counter()
        if not pull(model):
            print(f"!! pull failed: {model}", flush=True)
            return
        print(f"pulled in {time.perf_counter() - t:.0f}s", flush=True)
    with MemSampler() as mem:
        t0 = time.perf_counter()
        if "extract" in tasks:
            task_extract(model, think=think)
        if "judge" in tasks:
            for v in variants:
                task_judge(model, think=think, variant=v)
        total = time.perf_counter() - t0
    unload(model)
    save(
        results_dir() / "mem" / f"{slug(model)}{'_think' if think else ''}.json",
        {
            "model": model,
            "think": think,
            "peak_vram_mb": mem.peak_vram_mb,
            "peak_ram_mb": mem.peak_ram_mb,
            "total_s": total,
        },
    )
    print(
        f"== {model} done in {total / 60:.1f} min, VRAM {mem.peak_vram_mb:.0f} MB, "
        f"RAM {mem.peak_ram_mb:.0f} MB",
        flush=True,
    )
    if rm_after and model != "qwen2.5:3b-instruct":
        remove(model)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--models", default="all")
    r.add_argument("--tasks", default="extract,judge")
    r.add_argument("--variants", default="zero")
    r.add_argument("--think", action="store_true", help="thinking variant for hybrid models")
    r.add_argument("--rm-after", action="store_true")
    sub.add_parser("appbase")
    rk = sub.add_parser("rank")
    rk.add_argument("--fixes", default="base")
    rk.add_argument("--only", default="")
    sub.add_parser("baselines")
    sub.add_parser("unjudged")
    sub.add_parser("report")
    a = ap.parse_args()

    if a.cmd == "run":
        tags = (
            [m.tag for m in ROSTER]
            if a.models == "all"
            else SHORTLIST
            if a.models == "shortlist"
            else a.models.split(",")
        )
        for tag in tags:
            m = by_tag(tag)
            think = True if a.think else m.think
            if a.think and tag not in THINKING_VARIANTS and m.think is not True:
                continue
            print(f"\n### {tag} think={think}", flush=True)
            run_model(
                tag,
                a.tasks.split(","),
                think=think,
                variants=a.variants.split(","),
                rm_after=a.rm_after,
            )
    elif a.cmd == "appbase":
        # the app as shipped vs each separate fix to the LLM call
        m = "qwen2.5:3b-instruct"
        task_extract(m, think=None, prompt="app", num_ctx=2048, max_tokens=400)
        task_extract(m, think=None, prompt="app", num_ctx=8192, max_tokens=400)
        task_extract(m, think=None, prompt="app", num_ctx=8192, max_tokens=1200)
        task_extract(m, think=None, prompt="v2", num_ctx=8192, max_tokens=1200)
    elif a.cmd == "baselines":
        baseline_sources()
    elif a.cmd == "rank":
        srcs = sorted((results_dir() / "extract").glob("*.json"))
        if a.only:
            srcs = [s for s in srcs if re.search(a.only, s.stem)]
        task_rank(srcs, a.fixes.split(","))
    elif a.cmd == "unjudged":
        unjudged()
    elif a.cmd == "report":
        report()


def unjudged() -> None:
    """Every candidate that any stored ranking puts in its top 10 (top 25 for app runs) but the
    gold has not judged: these get judged with the same rubric (pooling top-up)."""
    need: dict[str, set[int]] = {}
    for p in list((results_dir() / "rank").glob("*.json")):
        res = load(p)
        for jd, v in res["jds"].items():
            if not v:
                continue
            _, gold = load_gold(jd)
            need.setdefault(jd, set()).update(i for i in v["ids"][:10] if i not in gold)
    for p in list((results_dir() / "judge").glob("*.json")):
        if p.stem.startswith("_"):
            continue
        res = load(p)
        for jd, v in res["jds"].items():
            _, gold = load_gold(jd)
            need.setdefault(jd, set()).update(i for i in v["order"][:10] if i not in gold)
    out = {jd: sorted(s) for jd, s in need.items() if s}
    save(gold_dir() / "_unjudged.json", out)
    print({jd: len(v) for jd, v in out.items()})


def _mean(xs: list[float]) -> float:
    xs = [x for x in xs if x is not None]
    return statistics.mean(xs) if xs else float("nan")


def report() -> None:
    REPO_RESULTS.mkdir(parents=True, exist_ok=True)
    rows_a = []
    for p in sorted((results_dir() / "extract").glob("*.json")):
        ex = load(p)
        runs = ex["runs"]
        keys = [
            "must_p",
            "must_r",
            "must_f1",
            "all_f1",
            "min_exact",
            "min_abs_err",
            "max_invented",
            "loc_ok",
            "domain_jaccard",
            "domain_invented",
            "skill_halluc_rate",
        ]
        row: dict[str, Any] = {"config": p.stem, "model": ex["model"]}
        for k in keys:
            row[k] = round(
                _mean([v["scores"][k] for run in runs for v in run.values() if v.get("scores")]), 3
            )
        row["json_valid"] = round(_mean([float(v["ok"]) for run in runs for v in run.values()]), 3)
        row["sec_per_jd"] = round(
            _mean([v.get("stats", {}).get("wall_s") for run in runs for v in run.values()]), 1
        )
        row["tok_s"] = round(
            _mean([v.get("stats", {}).get("tok_s") for run in runs for v in run.values()]), 1
        )
        rows_a.append(row)
    _csv(REPO_RESULTS / "task_a_extraction.csv", rows_a)

    rows_b = []
    for p in sorted((results_dir() / "rank").glob("*.json")):
        res = load(p)
        for jd, v in res["jds"].items():  # re-score against the current (topped-up) gold
            if v:
                v["rank"] = ranking_scores(v["ids"], load_gold(jd)[1])
        vals = [v for v in res["jds"].values() if v]
        row = {"source": res["source"], "fix": res["fix"]}
        for k in ("ndcg10", "p10", "r25", "mrr", "unjudged10"):
            row[k] = round(_mean([v["rank"][k] for v in vals]), 3)
        for jd, v in res["jds"].items():
            row[f"{jd}_ndcg10"] = round(v["rank"]["ndcg10"], 3) if v else None
        rows_b.append(row)
    _csv(REPO_RESULTS / "task_b_ranking.csv", rows_b)

    rows_c = []
    mem = {p.stem: load(p) for p in (results_dir() / "mem").glob("*.json")}
    for p in sorted((results_dir() / "judge").glob("*.json")):
        if p.stem.startswith("_"):
            continue
        res = load(p)
        cand = judge_candidates()
        for jd, v in res["jds"].items():  # re-score against the current (topped-up) gold
            gold = load_gold(jd)[1]
            grades = {int(k): g for k, g in v["grades"].items()}
            v["rank"] = ranking_scores(v["order"], gold)
            v["app_rank"] = ranking_scores(cand[jd], gold)
            v["agree"] = agreement(grades, gold)
        vals = list(res["jds"].values())
        row = {"config": p.stem, "model": res["model"], "variant": res["variant"]}
        for k in ("ndcg10", "p10", "r25", "mrr"):
            row[k] = round(_mean([v["rank"][k] for v in vals]), 3)
            row[f"app_{k}"] = round(_mean([v["app_rank"][k] for v in vals]), 3)
        for k in ("acc", "acc1", "qwk"):
            row[k] = round(_mean([v["agree"][k] for v in vals]), 3)
        calls = sum(v["stats"]["calls"] for v in vals)
        row["fail_rate"] = (
            round(sum(v["stats"]["fail"] for v in vals) / calls, 3) if calls else None
        )
        row["sec_per_jd"] = round(_mean([v["stats"]["wall_s"] for v in vals]), 1)
        ev = sum(v["stats"]["eval_tokens"] for v in vals)
        es = sum(v["stats"]["eval_s"] for v in vals)
        row["tok_s"] = round(ev / es, 1) if es else None
        mk = slug(res["model"]) + ("_think" if res.get("think") else "")
        if mk in mem:
            row["peak_vram_mb"] = round(mem[mk]["peak_vram_mb"])
            row["peak_ram_mb"] = round(mem[mk]["peak_ram_mb"])
        for jd, v in res["jds"].items():
            row[f"{jd}_ndcg10"] = round(v["rank"]["ndcg10"], 3)
        rows_c.append(row)
    _csv(REPO_RESULTS / "task_c_judging.csv", rows_c)
    print(
        f"wrote {len(rows_a)} A rows, {len(rows_b)} B rows, {len(rows_c)} C rows to {REPO_RESULTS}"
    )


def _csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    cols: list[str] = []
    for r in rows:
        cols += [k for k in r if k not in cols]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
