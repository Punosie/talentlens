"""Benchmark local-AI configurations on real CVs, using a COPY of a library database.

    uv run python scripts/bench_ai.py <path-to-talentlens.db> [--n 12]

For CVs that already have an AI result (the reference), each config is timed and compared on
name, title, years (within 1.5) and city. Nothing is written to the source database.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path

from talentlens.ai.extract import llm_extract, llm_extract_full
from talentlens.ai.llm import OllamaLLM
from talentlens.ai.taxonomy import gazetteer

CONFIGS = [
    ("3b full prompt, ctx 6144 (v0.1)", "qwen2.5:3b-instruct", 6144, llm_extract_full),
    ("3b compact, ctx 2048", "qwen2.5:3b-instruct", 2048, llm_extract),
    ("1.5b compact, ctx 2048", "qwen2.5:1.5b-instruct", 2048, llm_extract),
]


def norm(s: object) -> str:
    return re.sub(r"[^a-z ]", "", str(s or "").lower()).strip()


def tokens(s: object) -> set[str]:
    return {t for t in norm(s).split() if len(t) > 1}


def agree(ref: dict, got: dict) -> dict[str, bool]:
    gz = gazetteer()
    rc, _ = gz.normalize(ref.get("city") or None, ref.get("country") or None)
    gc, _ = gz.normalize(got.get("city") or None, got.get("country") or None)
    rt, gt = tokens(ref.get("current_title")), tokens(got.get("current_title"))
    try:
        ry, gy = (
            float(ref.get("total_years_experience") or 0),
            float(got.get("total_years_experience") or 0),
        )
    except (TypeError, ValueError):
        ry, gy = 0, -99
    rc_s, gc_s = norm(ref.get("city")), norm(got.get("city"))
    city_ok = (
        (rc or "") == (gc or "")
        or bool(
            rc_s and gc_s and (rc_s in gc_s or gc_s in rc_s)
        )  # "Coppell" vs "Coppell Texas USA"
    )
    return {
        "name": bool(tokens(ref.get("name")) & tokens(got.get("name"))),
        "title": not rt or len(rt & gt) / max(len(rt), 1) >= 0.5,
        "years": abs(ry - gy) <= 1.5,
        "city": city_ok,
    }


def gpu_share() -> str:
    try:
        out = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=10).stdout
        return " | ".join(
            line.split("  ")[0] + " " + " ".join(line.split()[3:6])
            for line in out.splitlines()[1:]
            if line.strip()
        )
    except OSError:
        return "?"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--only", help="run only configs whose label contains this text")
    ap.add_argument("--show", action="store_true", help="print each disagreement")
    args = ap.parse_args()
    tmp = Path(tempfile.mkdtemp()) / "copy.db"
    src = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    dst = sqlite3.connect(tmp)
    src.backup(dst)
    src.close()
    rows = dst.execute(
        "SELECT filename, text, llm_json FROM cvs WHERE llm_json IS NOT NULL AND llm_sha = sha256 "
        "ORDER BY id LIMIT ?",
        (args.n,),
    ).fetchall()
    dst.close()
    print(f"{len(rows)} reference CVs (AI results from the current setup)\n")
    for label, model, ctx, fn in CONFIGS:
        if args.only and args.only not in label:
            continue
        llm = OllamaLLM("http://127.0.0.1:11434", model, timeout_s=300, num_ctx=ctx)
        try:
            fn(llm, "warm up", "x.pdf")  # load model
        except Exception as e:
            print(f"== {label}: warm-up failed: {e!r}", flush=True)
        share = gpu_share()
        times, scores = [], {"name": 0, "title": 0, "years": 0, "city": 0}
        for filename, text, ref_json in rows:
            t = time.perf_counter()
            try:
                got = fn(llm, text, filename)
            except Exception as e:
                print(f"   ! {filename}: {e!r}", flush=True)
                got = {}
            times.append(time.perf_counter() - t)
            ref = json.loads(ref_json)
            for k, ok in agree(ref, got).items():
                scores[k] += ok
                if args.show and not ok:
                    key = {"title": "current_title", "years": "total_years_experience"}.get(k, k)
                    print(
                        f"   ~ {filename[:40]:40} {k}: ref={ref.get(key)!r} got={got.get(key)!r}",
                        flush=True,
                    )
        n = max(len(rows), 1)
        print(f"== {label}")
        print(f"   load: {share}")
        print(f"   seconds/CV: mean {sum(times) / n:.1f}, max {max(times):.1f}")
        print(
            "   agreement with reference: "
            + ", ".join(f"{k} {100 * v / n:.0f}%" for k, v in scores.items())
        )
    shutil.rmtree(tmp.parent, ignore_errors=True)


if __name__ == "__main__":
    main()
