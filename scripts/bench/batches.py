"""Split each JD's pool into anonymised judging batches (private dir).

    uv run python -m scripts.bench.batches [--size 34] [--ids-file JDxx:path ...]

Cards are shuffled with a fixed seed so batch order carries no ranking signal.
"""

from __future__ import annotations

import argparse
import json
import random

from .cards import cards, render
from .env import gold_dir, load_jds


def make(jd: str, ids: list[int], size: int, prefix: str = "b") -> int:
    d = gold_dir() / jd / "batches"
    d.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(f"{jd}-{prefix}")
    ids = sorted(ids)
    rnd.shuffle(ids)
    n = 0
    for k in range(0, len(ids), size):
        chunk = cards(ids[k : k + size], chars=2500)
        body = "\n".join(render(c) for c in chunk)
        (d / f"{prefix}{n:02d}.md").write_text(body, encoding="utf-8")
        (d / f"{prefix}{n:02d}.ids.json").write_text(json.dumps([c["id"] for c in chunk]))
        n += 1
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=34)
    ap.add_argument("jds", nargs="*")
    a = ap.parse_args()
    for jd in a.jds or list(load_jds()):
        pool = json.loads((gold_dir() / jd / "pool.json").read_text(encoding="utf-8"))
        n = make(jd, [int(i) for i in pool["ids"]], a.size)
        print(jd, pool["size"], "->", n, "batches")
