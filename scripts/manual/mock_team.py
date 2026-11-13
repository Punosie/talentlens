# ruff: noqa: E501  (inline HTML for the mock invite page)
"""A stand-in "team server" for recording the setup manual.

Serves the invite page and the TalentLens team API (/api/tl/*) with FICTIONAL people only,
so the manual never shows real data and needs no database or credentials.

    uv run python scripts/manual/mock_team.py --port 8790
"""

from __future__ import annotations

import argparse
import random
from datetime import UTC, datetime, timedelta
from html import escape

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

INVITE = "DemoInviteCode0123456789Ab"
TOKEN = "demo-token-" + "x" * 32
TEAM_NAME = "Acme Talent Team"

FIRST = [
    "Aanya",
    "Rohan",
    "Meera",
    "Kabir",
    "Isha",
    "Vikram",
    "Sara",
    "Dev",
    "Nisha",
    "Arjun",
    "Leah",
    "Omar",
    "Tara",
    "Neil",
    "Zoya",
    "Ravi",
    "Ana",
    "Kiran",
    "Mila",
    "Yusuf",
    "Diya",
    "Farhan",
    "Ira",
    "Jonas",
]
LAST = [
    "Kapoor",
    "Desai",
    "Iyer",
    "Malhotra",
    "Fernandes",
    "Rao",
    "Thomas",
    "Sethi",
    "Bose",
    "Khan",
    "Mehra",
    "Pillai",
    "Varma",
    "Joshi",
    "Chatterjee",
    "Nair",
    "Gill",
    "Reddy",
    "Menon",
    "Shah",
    "Banerjee",
    "Dutta",
    "Kulkarni",
    "Agarwal",
]
ROLES = [
    (
        "Senior Data Engineer",
        ["Python", "SQL", "Apache Spark", "Apache Airflow", "Amazon Web Services", "dbt"],
    ),
    ("Data Engineer", ["Python", "SQL", "Apache Kafka", "Snowflake", "Azure"]),
    ("Backend Engineer", ["Java", "Spring Boot", "Kafka", "PostgreSQL", "Docker"]),
    ("Machine Learning Engineer", ["Python", "PyTorch", "MLOps", "Kubernetes", "SQL"]),
    (
        "Product Manager",
        ["Product Strategy", "Roadmapping", "Agile", "SQL", "Stakeholder Management"],
    ),
    ("DevOps Engineer", ["Kubernetes", "Terraform", "AWS", "CI/CD", "Linux"]),
    ("Analytics Manager", ["SQL", "Tableau", "Python", "A/B Testing", "Statistics"]),
    ("Frontend Engineer", ["React", "TypeScript", "Next.js", "CSS", "Testing"]),
]
COMPANIES = [
    "Example Payments",
    "Northwind Fintech",
    "Contoso Retail",
    "Fabrikam Health",
    "Tailspin Logistics",
    "Lumen Analytics",
    "Globex Telecom",
    "Initech Cloud",
]
CITIES = [
    ("Bengaluru", "Karnataka"),
    ("Pune", "Maharashtra"),
    ("Gurugram", "Haryana"),
    ("Hyderabad", "Telangana"),
    ("Mumbai", "Maharashtra"),
    ("Chennai", "Tamil Nadu"),
]
OWNERS = ["alex-recruiter", "sam-hiring"]


def fictional_people(n: int = 24) -> list[dict]:
    rnd = random.Random(7)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    out = []
    for i in range(n):
        first, last = FIRST[i % len(FIRST)], LAST[(i * 7) % len(LAST)]
        title, skills = ROLES[i % len(ROLES)]
        company = COMPANIES[(i * 3) % len(COMPANIES)]
        prev = COMPANIES[(i * 5 + 1) % len(COMPANIES)]
        city, state = CITIES[i % len(CITIES)]
        years = 3 + (i * 5) % 12
        start = now.year - min(years, 4)
        pid = f"{first}-{last}-{i:02d}".lower()
        owners = [
            {"account": OWNERS[i % 2], "connected_on": (now - timedelta(days=30 * i)).isoformat()}
        ]
        if i % 5 == 0:
            owners.append({"account": OWNERS[(i + 1) % 2], "connected_on": now.isoformat()})
        out.append(
            {
                "_id": pid,
                "full_name": f"{first} {last}",
                "headline": f"{title} at {company} | {', '.join(skills[:3])}",
                "about": f"{title} with {years} years of experience. I enjoy building reliable systems and mentoring teams.",
                "current": {"title": title, "company": company},
                "loc": {"city": city, "state": state, "country": "India"},
                "location": f"{city}, {state}, India",
                "years_exp": float(years),
                "industry": "Technology, Information and Internet",
                "skills": skills
                + rnd.sample(["Communication", "Leadership", "Git", "Jira", "Mentoring"], 2),
                "experiences": [
                    {
                        "title": title,
                        "company": company,
                        "location": f"{city}, India",
                        "start": {"year": start, "month": 4},
                        "end": None,
                        "is_current": True,
                        "description": f"Leading work on {skills[0]} and {skills[1]} for {company}'s core platform.",
                    },
                    {
                        "title": title.replace("Senior ", ""),
                        "company": prev,
                        "location": "India",
                        "start": {"year": start - 3, "month": 1},
                        "end": {"year": start, "month": 3},
                        "is_current": False,
                        "description": f"Built features with {skills[2]}.",
                    },
                ],
                "education": [
                    {
                        "school": "Example Institute of Technology",
                        "degree": "B.Tech",
                        "field": "Computer Science",
                        "start_year": start - 8,
                        "end_year": start - 4,
                    }
                ],
                "owners": owners,
                "profile_url": f"https://www.linkedin.com/in/{pid}/",
                "sources": ["linkedin"],
                "migrated_at": now.isoformat(),
            }
        )
    return out


PEOPLE = fictional_people()
app = FastAPI()
state = {"redeemed": False}

JOIN_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Join · Connections</title>
<style>
  *{box-sizing:border-box} body{margin:0;font-family:"Segoe UI Variable Text","Segoe UI",system-ui,sans-serif;
  background:#fafafa;color:#171717;display:flex;min-height:100vh;align-items:center;justify-content:center;padding:24px}
  .wrap{width:100%;max-width:520px} .c{text-align:center} .ic{width:44px;height:44px;margin:0 auto 10px;color:#171717}
  h1{font-size:28px;margin:6px 0;letter-spacing:-.02em} p.m{color:#737373;font-size:16px;line-height:1.5;margin:6px 0}
  ol{list-style:none;margin:26px 0;padding:24px;border:1px solid #e5e5e5;border-radius:14px;background:#fff}
  li{display:flex;gap:12px;font-size:15px;line-height:1.5} li+li{margin-top:16px}
  .n{flex:none;width:24px;height:24px;border-radius:50%;background:#171717;color:#fff;font-size:12px;font-weight:600;
  display:flex;align-items:center;justify-content:center}
  a.b{display:flex;height:48px;align-items:center;justify-content:center;border-radius:10px;background:#171717;
  color:#fff;text-decoration:none;font-size:16px;font-weight:500} a.b:hover{background:#262626}
  .s{font-size:13px;color:#737373;text-align:center;margin-top:16px}
</style></head><body><div class="wrap">
<div class="c"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"
stroke-linejoin="round"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M2 20h20"/></svg>
<h1>Connect TalentLens</h1>
<p class="m">You've been invited to search and match the team's LinkedIn connections in TalentLens on your computer.</p></div>
<ol><li><span class="n">1</span><span><b>Open TalentLens</b> on this computer (the desktop icon). Install it first if you haven't.</span></li>
<li><span class="n">2</span><span>Click the button below, then confirm in TalentLens.</span></li></ol>
<a class="b" id="connect" href="http://127.0.0.1:8765/connect?server=__SERVER__&amp;invite=__CODE__">Connect TalentLens</a>
<p class="s">This link works once and expires in 7 days.</p></div></body></html>"""


@app.get("/join/{code}", response_class=HTMLResponse)
def join_page(code: str, request: Request) -> str:
    origin = f"{request.url.scheme}://{request.url.netloc}"
    return JOIN_HTML.replace("__SERVER__", escape(origin)).replace("__CODE__", escape(code))


@app.post("/api/tl/redeem")
async def redeem(request: Request):
    body = await request.json()
    if body.get("code") != INVITE:
        return JSONResponse({"error": "This invite link has expired or was already used."}, 400)
    state["redeemed"] = True
    return {
        "token": TOKEN,
        "name": "Jordan",
        "server": f"{request.url.scheme}://{request.url.netloc}",
    }


def _authed(request: Request) -> bool:
    return request.headers.get("authorization") == f"Bearer {TOKEN}"


@app.get("/api/tl/me")
def me(request: Request):
    if not _authed(request):
        return JSONResponse({"error": "Access removed"}, 401)
    return {"name": "Jordan", "server": f"{request.url.scheme}://{request.url.netloc}"}


@app.get("/api/tl/people")
def people(request: Request, limit: int = 200, after: str | None = None, since: str | None = None):
    if not _authed(request):
        return JSONResponse({"error": "Access removed"}, 401)
    rows = sorted(PEOPLE, key=lambda d: d["_id"])
    if since:
        rows = [d for d in rows if d["migrated_at"] > since]
    page = [d for d in rows if after is None or d["_id"] > after][:limit]
    return {
        "items": page,
        "count": None if after else len(rows),
        "next": page[-1]["_id"] if len(page) == limit else None,
    }


@app.post("/api/tl/cv")
async def cv(request: Request):
    if not _authed(request):
        return JSONResponse({"error": "Access removed"}, 401)
    body = await request.json()
    return {"person_id": f"cv:{body['sha256'][:20].lower()}", "created": True}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8790)
    args = ap.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
