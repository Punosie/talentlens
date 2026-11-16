"""Scoring against the Opus gold standard."""

from __future__ import annotations

import math
import re
from typing import Any

from talentlens.ai import taxonomy

_STOP = {
    "and",
    "or",
    "the",
    "of",
    "with",
    "in",
    "for",
    "to",
    "a",
    "an",
    "using",
    "experience",
    "skills",
    "knowledge",
    "strong",
    "hands",
    "on",
    "based",
}


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9+#.]+", s.lower()) if t not in _STOP and len(t) > 1}


def canon(s: str) -> str:
    c = taxonomy.skills().canonicalize(s)
    return (c or s).strip().lower()


def same_skill(a: str, b: str) -> bool:
    """Synonyms count: same canonical name, one name inside the other, or strong token overlap."""
    ca, cb = canon(a), canon(b)
    if ca == cb:
        return True
    la, lb = a.lower().strip(), b.lower().strip()
    if len(la) >= 3 and len(lb) >= 3 and (la in lb or lb in la):
        return True
    ta, tb = _tokens(a), _tokens(b)
    if ta and tb:
        j = len(ta & tb) / len(ta | tb)
        if j >= 0.6:
            return True
    return False


def _matched(xs: list[str], ys: list[str]) -> int:
    return sum(1 for x in xs if any(same_skill(x, y) for y in ys))


def prf(pred: list[str], gold: list[str], gold_any: list[str] | None = None) -> dict[str, float]:
    """precision against gold_any (default gold), recall against gold."""
    gold_any = gold_any if gold_any is not None else gold
    p = _matched(pred, gold_any) / len(pred) if pred else (1.0 if not gold else 0.0)
    r = _matched(gold, pred) / len(gold) if gold else 1.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"p": p, "r": r, "f1": f}


_JD_SKILLS: dict[int, set[str]] = {}


def _jd_skills(jd_text: str) -> set[str]:
    key = hash(jd_text)
    if key not in _JD_SKILLS:
        _JD_SKILLS[key] = set(taxonomy.skills().find(jd_text))
    return _JD_SKILLS[key]


def supported(item: str, jd_text: str) -> bool:
    """Is this extracted item backed by the JD text? (exact phrase, alias, or most of its tokens)"""
    t = jd_text.lower()
    if item.lower() in t:
        return True
    tax = taxonomy.skills()
    c = tax.canonicalize(item)
    if c and c in _jd_skills(jd_text):
        return True
    toks = _tokens(item)
    if not toks:
        return False
    jd_toks = _tokens(jd_text)
    return len(toks & jd_toks) / len(toks) >= 0.67


def extraction_scores(pred: dict[str, Any], gold: dict[str, Any], jd_text: str) -> dict[str, float]:
    must, nice = pred.get("must_have_skills") or [], pred.get("nice_to_have_skills") or []
    gm, gn = gold["must_have_skills"], gold["nice_to_have_skills"]
    m = prf(must, gm, gm + gn)
    a = prf(must + nice, gm + gn)
    out = {
        "must_p": m["p"],
        "must_r": m["r"],
        "must_f1": m["f1"],
        "all_p": a["p"],
        "all_r": a["r"],
        "all_f1": a["f1"],
    }
    pmin, gmin = pred.get("min_years"), gold.get("min_years")
    out["min_exact"] = float(
        (pmin is None and gmin is None)
        or (pmin is not None and gmin is not None and abs(float(pmin) - float(gmin)) < 0.01)
    )
    out["min_abs_err"] = abs(float(pmin or 0) - float(gmin or 0))
    pmax, gmax = pred.get("max_years"), gold.get("max_years")
    out["max_invented"] = float(pmax is not None and gmax is None)
    out["max_exact"] = float(
        (pmax is None and gmax is None)
        or (pmax is not None and gmax is not None and abs(float(pmax) - float(gmax)) < 0.01)
    )
    gz = taxonomy.gazetteer()

    def locset(xs: list[str]) -> set[str]:
        s = set()
        for x in xs or []:
            s.add(x.lower())
            cc = gz.city_country.get(x)
            if cc:
                s.add(cc.lower())
        return s

    pl, gl = locset(pred.get("locations") or []), locset(gold.get("locations") or [])
    out["loc_ok"] = float((not pl and not gl) or bool(pl & gl))
    pd = {d.lower() for d in pred.get("domains") or []}
    gd = {d.lower() for d in gold.get("domains") or []}
    out["domain_jaccard"] = len(pd & gd) / len(pd | gd) if (pd | gd) else 1.0
    out["domain_invented"] = float(bool(pd - gd))
    items = must + nice
    out["skill_halluc_rate"] = (
        (sum(1 for x in items if not supported(x, jd_text)) / len(items)) if items else 0.0
    )
    return out


# ---------------------------------------------------------------- ranking metrics
def dcg(grades: list[int]) -> float:
    return sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(grades))


def ranking_scores(ranked_ids: list[int], grades: dict[int, int]) -> dict[str, float]:
    top10 = [grades.get(i, 0) for i in ranked_ids[:10]]
    ideal = sorted(grades.values(), reverse=True)[:10]
    idcg = dcg(ideal)
    relevant = {i for i, g in grades.items() if g >= 2}
    best = 3 if any(g == 3 for g in grades.values()) else 2
    mrr = 0.0
    for r, i in enumerate(ranked_ids, start=1):
        if grades.get(i, 0) >= best:
            mrr = 1.0 / r
            break
    return {
        "ndcg10": dcg(top10) / idcg if idcg else 0.0,
        "p10": sum(1 for g in top10 if g >= 2) / 10,
        "r25": len(relevant & set(ranked_ids[:25])) / len(relevant) if relevant else 0.0,
        "mrr": mrr,
        "unjudged10": sum(1 for i in ranked_ids[:10] if i not in grades),
        "unjudged25": sum(1 for i in ranked_ids[:25] if i not in grades),
    }


def agreement(pred: dict[int, int], gold: dict[int, int]) -> dict[str, float]:
    """Exact accuracy, within-1 accuracy and quadratic weighted kappa on the shared ids."""
    ids = [i for i in pred if i in gold]
    if not ids:
        return {"acc": 0.0, "acc1": 0.0, "qwk": 0.0, "n": 0}
    acc = sum(pred[i] == gold[i] for i in ids) / len(ids)
    acc1 = sum(abs(pred[i] - gold[i]) <= 1 for i in ids) / len(ids)
    k = 4
    o = [[0.0] * k for _ in range(k)]
    for i in ids:
        o[gold[i]][pred[i]] += 1
    n = len(ids)
    ha = [sum(o[r][c] for c in range(k)) for r in range(k)]
    hb = [sum(o[r][c] for r in range(k)) for c in range(k)]
    num = den = 0.0
    for r in range(k):
        for c in range(k):
            w = (r - c) ** 2 / (k - 1) ** 2
            num += w * o[r][c]
            den += w * ha[r] * hb[c] / n
    return {"acc": acc, "acc1": acc1, "qwk": 1 - num / den if den else 0.0, "n": n}
