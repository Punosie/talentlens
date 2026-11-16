"""Fine-tuning data: leakage check, (JD, profile) pair sampling, Opus judging batches, SFT export.

    uv run python -m scripts.bench.train_data leakage  # drop JDs too close to a benchmark JD
    uv run python -m scripts.bench.train_data pairs    # sample candidates per JD -> judging batches
    uv run python -m scripts.bench.train_data export   # chat-format SFT files (train/val)

Everything is written under bench-work/training (git-ignored). Profile cards carry no names.
"""

from __future__ import annotations

import json
import random
import re
import sys
from typing import Any

import numpy as np

from .cards import cards, render
from .env import load_jds, rank, training_dir

PAIRS_PER_JD = 7
VAL_FRACTION = 0.1
COS_MAX = 0.85
NGRAM = 8


def synth() -> list[dict[str, Any]]:
    out = []
    for p in sorted((training_dir() / "jds").glob("s*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


def _ngrams(text: str) -> set[tuple[str, ...]]:
    w = re.findall(r"[a-z0-9+#.]+", text.lower())
    return {tuple(w[i : i + NGRAM]) for i in range(len(w) - NGRAM + 1)}


def leakage() -> None:
    from .env import shortlister

    emb = shortlister().search.embedder
    bench = load_jds()
    b_ids = list(bench)
    b_vec = np.asarray(emb.embed_documents([bench[k] for k in b_ids]), dtype=np.float32)
    b_ng = {k: _ngrams(v) for k, v in bench.items()}
    items = synth()
    vecs = np.asarray(emb.embed_documents([it["jd_text"] for it in items]), dtype=np.float32)
    sims = vecs @ b_vec.T
    report, keep = [], []
    for it, row in zip(items, sims, strict=True):
        j = int(row.argmax())
        shared = len(_ngrams(it["jd_text"]) & b_ng[b_ids[j]])
        bad = float(row[j]) > COS_MAX or shared > 0
        report.append(
            {
                "id": it["id"],
                "nearest": b_ids[j],
                "cos": round(float(row[j]), 3),
                "shared_8grams": shared,
                "rejected": bad,
            }
        )
        if not bad:
            keep.append(it["id"])
    out = training_dir() / "leakage.json"
    out.write_text(
        json.dumps({"cos_max": COS_MAX, "ngram": NGRAM, "kept": keep, "items": report}, indent=1)
    )
    rej = [r for r in report if r["rejected"]]
    print(
        f"{len(items)} synthetic JDs, {len(rej)} rejected, max cos "
        f"{max(r['cos'] for r in report):.3f}"
    )
    for r in rej:
        print("  rejected", r)


def _split(ids: list[str]) -> tuple[set[str], set[str]]:
    rnd = random.Random("talentlens-split")
    ids = sorted(ids)
    rnd.shuffle(ids)
    n_val = max(1, int(len(ids) * VAL_FRACTION))
    return set(ids[n_val:]), set(ids[:n_val])


def pairs(batch_size: int = 35) -> None:
    from .env import ro_connect

    lk = json.loads((training_dir() / "leakage.json").read_text())
    kept = set(lk["kept"])
    items = [it for it in synth() if it["id"] in kept]
    with ro_connect() as conn:
        all_ids = [r[0] for r in conn.execute("SELECT id FROM cvs")]
    rnd = random.Random("pairs")
    plan: list[tuple[dict[str, Any], list[int]]] = []
    for it in items:
        ranked = [x["id"] for x in rank(it["gold"], it["jd_text"], limit=60)]
        pick = rnd.sample(ranked[:10], min(3, len(ranked[:10])))
        pick += rnd.sample(ranked[10:60], min(2, len(ranked[10:60])))
        pick += rnd.sample(all_ids, PAIRS_PER_JD - len(pick))
        plan.append((it, list(dict.fromkeys(pick))))
    d = training_dir() / "pair_batches"
    d.mkdir(parents=True, exist_ok=True)
    # 5 JDs per batch file; every JD carries its own cards
    k = 0
    for start in range(0, len(plan), 5):
        chunk = plan[start : start + 5]
        md, ids = [], []
        for it, cand in chunk:
            gold = json.dumps(it["gold"])
            md.append(f"# JOB {it['id']}\n\n{it['jd_text']}\n\nGOLD REQUIREMENTS: {gold}\n")
            for c in cards(cand, chars=2000):
                md.append(render(c).replace("### Candidate", f"### Pair {it['id']} | Candidate"))
                ids.append({"jd": it["id"], "id": c["id"]})
        (d / f"p{k:03d}.md").write_text("\n".join(md), encoding="utf-8")
        (d / f"p{k:03d}.ids.json").write_text(json.dumps(ids))
        k += 1
    print(f"{len(plan)} JDs -> {sum(len(c) for _, c in plan)} pairs in {k} batch files")


def export() -> None:
    """Chat-format SFT data for both tasks, split by JD (validation JDs never appear in train)."""
    from talentlens.jd import parse_rules, requirements_from_llm

    from .prompts import JD_SCHEMA_V2, JD_SYSTEM_V2, JUDGE_SYSTEM, jd_user, judge_user

    lk = json.loads((training_dir() / "leakage.json").read_text())
    kept = set(lk["kept"])
    items = {it["id"]: it for it in synth() if it["id"] in kept}
    _train_ids, val_ids = _split(list(items))
    rows: dict[str, list[dict[str, Any]]] = {"train": [], "val": []}
    for jid, it in items.items():
        g = dict(it["gold"])
        target = {k: g.get(k) for k in JD_SCHEMA_V2["required"]}
        target["locations"] = target.get("locations") or []
        split = "val" if jid in val_ids else "train"
        rows[split].append(
            {
                "task": "jd",
                "jd": jid,
                "messages": [
                    {"role": "system", "content": JD_SYSTEM_V2},
                    {"role": "user", "content": jd_user(it["jd_text"])},
                    {"role": "assistant", "content": json.dumps(target, ensure_ascii=False)},
                ],
            }
        )
        _ = requirements_from_llm(
            target, it["jd_text"], parse_rules(it["jd_text"])
        )  # schema sanity
    judged_dir = training_dir() / "pair_judged"
    for f in sorted(judged_dir.glob("p*.json")):
        for j in json.loads(f.read_text(encoding="utf-8")):
            it = items.get(j["jd"])
            if not it:
                continue
            card = cards([int(j["id"])], chars=2000)
            if not card:
                continue
            body = render(card[0]).split("\n", 1)[1]
            split = "val" if j["jd"] in val_ids else "train"
            rows[split].append(
                {
                    "task": "judge",
                    "jd": j["jd"],
                    "messages": [
                        {"role": "system", "content": JUDGE_SYSTEM},
                        {"role": "user", "content": judge_user(it["jd_text"], body)},
                        {
                            "role": "assistant",
                            "content": json.dumps(
                                {"grade": int(j["grade"]), "reason": j.get("reason", "")[:200]},
                                ensure_ascii=False,
                            ),
                        },
                    ],
                }
            )
    out = training_dir() / "sft"
    out.mkdir(exist_ok=True)
    for split, rs in rows.items():
        random.Random(split).shuffle(rs)
        with (out / f"{split}.jsonl").open("w", encoding="utf-8") as fh:
            for r in rs:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        n_jd = sum(r["task"] == "jd" for r in rs)
        print(f"{split}: {len(rs)} rows ({n_jd} extraction, {len(rs) - n_jd} judging)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"leakage": leakage, "pairs": pairs, "export": export}[cmd]()
