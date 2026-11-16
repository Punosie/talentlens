"""Trimmed, work-only profile cards for judging (no name, URL, email or phone).

uv run python -m scripts.bench.cards <id> [<id> ...]
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

from .env import ro_connect

_DROP = re.compile(r"(?im)^(?:location|industry|experience):.*$")


def _body(text: str, name: str | None) -> str:
    lines = (text or "").splitlines()
    if lines and name and lines[0].strip().lower() == name.strip().lower():
        lines = lines[1:]
    body = "\n".join(lines)
    body = re.sub(r"\S+@\S+", "[email]", body)
    body = re.sub(r"https?://\S+", "[url]", body)
    body = re.sub(r"\+?\d[\d\s\-()]{8,}\d", "[phone]", body)
    return re.sub(r"\n{3,}", "\n\n", body).strip()


def cards(ids: list[int], chars: int = 3500) -> list[dict[str, Any]]:
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    with ro_connect() as conn:
        rows = conn.execute(
            f"SELECT id, name, title, years_exp, city, country, skills, text "
            f"FROM cvs WHERE id IN ({marks})",
            ids,
        ).fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "title": r["title"],
                "years_exp": r["years_exp"],
                "location": ", ".join(x for x in (r["city"], r["country"]) if x),
                "skills": json.loads(r["skills"] or "[]")[:40],
                "profile": _body(r["text"], r["name"])[:chars],
            }
        )
    order = {i: n for n, i in enumerate(ids)}
    return sorted(out, key=lambda c: order[c["id"]])


def render(card: dict[str, Any]) -> str:
    return (
        f"### Candidate {card['id']}\n"
        f"Title: {card['title']} | Years: {card['years_exp']} | Location: {card['location']}\n"
        f"Skills: {', '.join(card['skills'])}\n{card['profile']}\n"
    )


def names(ids: list[int]) -> dict[int, str]:
    marks = ",".join("?" * len(ids))
    with ro_connect() as conn:
        return {
            r[0]: r[1] for r in conn.execute(f"SELECT id, name FROM cvs WHERE id IN ({marks})", ids)
        }


if __name__ == "__main__":
    for c in cards([int(x) for x in sys.argv[1:]]):
        print(render(c))
