"""Connections database (MongoDB) sync: LinkedIn profiles in, resumes out.

Uses an in-memory fake of the few MongoDB operations the sync needs; no network, no real data.
"""

from __future__ import annotations

import copy
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from talentlens.connections import (
    ConnectionsSync,
    linkedin_id_in,
    profile_fields,
    profile_text,
)

from .conftest import make_pdf

T0 = datetime(2026, 1, 1, tzinfo=UTC)


# ----------------------------------------------------------------------------- fake MongoDB


def _get(doc: dict[str, Any], path: str) -> Any:
    cur: Any = doc
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _match(doc: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, cond in query.items():
        val = _get(doc, key)
        if isinstance(cond, dict) and "$regex" in cond:
            flags = re.I if "i" in cond.get("$options", "") else 0
            if not (isinstance(val, str) and re.search(cond["$regex"], val, flags)):
                return False
        elif isinstance(cond, dict) and "$gt" in cond:
            if val is None or not val > cond["$gt"]:
                return False
        elif isinstance(val, list):
            if cond not in val:
                return False
        elif val != cond:
            return False
    return True


class FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self.docs = docs

    def sort(self, key: str, direction: int) -> FakeCursor:
        self.docs.sort(key=lambda d: str(d.get(key)), reverse=direction < 0)
        return self

    def limit(self, n: int) -> FakeCursor:
        self.docs = self.docs[:n]
        return self

    def __iter__(self):
        return iter(self.docs)


class FakeCollection:
    def __init__(self, docs: list[dict[str, Any]] | None = None) -> None:
        self.docs = {d["_id"]: copy.deepcopy(d) for d in docs or []}
        self.updates: list[tuple[dict, dict]] = []

    def count_documents(self, query: dict[str, Any]) -> int:
        return sum(_match(d, query) for d in self.docs.values())

    def find(self, query: dict[str, Any], projection: Any = None) -> FakeCursor:
        return FakeCursor([copy.deepcopy(d) for d in self.docs.values() if _match(d, query)])

    def find_one(self, query: dict[str, Any], projection: Any = None) -> dict | None:
        return next((copy.deepcopy(d) for d in self.docs.values() if _match(d, query)), None)

    def update_one(self, flt: dict[str, Any], update: dict[str, Any], upsert: bool = False) -> None:
        self.updates.append((flt, update))
        doc = self.docs.get(flt["_id"])
        if doc is None:
            assert upsert
            doc = {"_id": flt["_id"], **update.get("$setOnInsert", {})}
            self.docs[flt["_id"]] = doc
        doc.update(update.get("$set", {}))
        for k, v in update.get("$addToSet", {}).items():
            doc.setdefault(k, [])
            if v not in doc[k]:
                doc[k].append(v)


class FakeClient:
    def __init__(self, col: FakeCollection) -> None:
        self.col = col

    def __getitem__(self, name: str) -> Any:
        return {"connections": self.col} if name == "linkedin" else {}

    def close(self) -> None:
        pass


def person(pid: str, **kw: Any) -> dict[str, Any]:
    doc = {
        "_id": pid,
        "full_name": kw.get("name", "Priya Sharma"),
        "headline": kw.get("headline", "Senior Data Engineer at Acme Fintech"),
        "about": "I build data platforms with Python, Spark and Airflow.",
        "current": {"title": kw.get("title", "Senior Data Engineer"), "company": "Acme Fintech"},
        "loc": {"city": kw.get("city", "Bengaluru"), "state": "Karnataka", "country": "India"},
        "location": "Bengaluru, Karnataka, India",
        "years_exp": kw.get("years", 7.5),
        "industry": "Financial Services",
        "skills": kw.get("skills", ["Python (Programming Language)", "Apache Spark", "SQL"]),
        "experiences": [
            {
                "title": "Senior Data Engineer",
                "company": "Acme Fintech",
                "start": {"year": 2022, "month": 3},
                "end": None,
                "is_current": True,
                "description": "Lending data pipelines on AWS with Airflow.",
            }
        ],
        "education": [{"school": "IIT Delhi", "degree": "B.Tech", "field": "Computer Science"}],
        "owners": [{"account": kw.get("owner", "me"), "connected_on": T0}],
        "profile_url": f"https://www.linkedin.com/in/{pid}/",
        "sources": ["linkedin"],
        "migrated_at": kw.get("migrated_at", T0),
    }
    return doc


def attach(client: TestClient, col: FakeCollection) -> ConnectionsSync:
    lib = client.app.state.tl.library
    sync = ConnectionsSync(
        lib.db, lib.indexer, "mongodb://fake", client_factory=lambda _u: FakeClient(col)
    )
    lib.connections = sync
    lib.queue.after_scan.append(sync.run)
    return sync


def scan(client: TestClient) -> None:
    client.post("/api/index/refresh")
    assert client.app.state.tl.queue.wait_idle(120)


# ----------------------------------------------------------------------------- pure functions


def test_profile_text_and_fields() -> None:
    doc = person("priya-s")
    text = profile_text(doc)
    assert "Senior Data Engineer at Acme Fintech" in text
    assert "Lending data pipelines" in text and "IIT Delhi" in text
    f = profile_fields(doc, text)
    assert f.name == "Priya Sharma" and f.title == "Senior Data Engineer"
    assert f.city == "Bengaluru" and f.country == "India"
    assert f.years_exp == 7.5
    assert "Python" in f.skills  # LinkedIn's "Python (Programming Language)" canonicalised
    assert f.extractor == "linkedin" and f.confident and f.email is None


def test_pull_pages_through_many_profiles(client: TestClient, monkeypatch) -> None:
    import talentlens.connections as conn_mod

    monkeypatch.setattr(conn_mod, "PAGE_SIZE", 3)  # force several pages
    col = FakeCollection([person(f"p-{i:02d}", name=f"Person {i}") for i in range(10)])
    sync = attach(client, col)
    scan(client)
    assert sync.status.pulled == 10


def test_linkedin_id_in() -> None:
    assert linkedin_id_in("Profile: https://www.linkedin.com/in/Priya-S/ ") == "priya-s"
    assert linkedin_id_in("linkedin.com/in/abc_123") == "abc_123"
    assert linkedin_id_in("no profile here") is None


# ----------------------------------------------------------------------------- pull


def test_pull_makes_profiles_searchable_and_matchable(client: TestClient) -> None:
    col = FakeCollection([person("priya-s"), person("rahul-k", name="Rahul Kumar", city="Pune")])
    sync = attach(client, col)
    scan(client)

    assert sync.status.pulled == 2
    r = client.get("/api/search", params={"q": "spark", "source": "linkedin"}).json()
    assert {i["name"] for i in r["items"]} == {"Priya Sharma", "Rahul Kumar"}
    item = r["items"][0]
    assert item["source"] == "linkedin" and item["owners"] == ["me"]
    assert item["profile_url"].startswith("https://www.linkedin.com/in/")

    # resumes from the folder are still there and filterable separately
    files = client.get("/api/search", params={"source": "file"}).json()
    assert files["total"] == 3 and all(i["source"] == "file" for i in files["items"])

    # JD matching ranks LinkedIn profiles too, and can be scoped
    body = {
        "requirements": {"title": "Data Engineer", "must_have_skills": ["Python", "Apache Spark"]},
        "rerank": False,
        "sources": ["linkedin"],
    }
    ranked = client.post("/api/shortlist", json=body).json()
    assert ranked["items"] and all(i["source"] == "linkedin" for i in ranked["items"])
    assert "Python" in ranked["items"][0]["matched_must"]

    # facets report sources and owners
    facets = client.get("/api/facets").json()
    assert {"value": "me", "count": 2} in facets["owners"]


def test_linkedin_rows_survive_folder_scans_and_skip_background_ai(client: TestClient) -> None:
    attach(client, FakeCollection([person("priya-s")]))
    scan(client)
    scan(client)  # a second scan must not delete rows that have no file
    st = client.app.state.tl
    with st.db.connect() as conn:
        n = conn.execute("SELECT COUNT(*) FROM cvs WHERE source='linkedin'").fetchone()[0]
    assert n == 1
    with st.db.connect() as conn:
        pending = conn.execute(
            f"SELECT COUNT(*) FROM cvs WHERE {st.indexer._PENDING} AND source='linkedin'"
        ).fetchone()[0]
    assert pending == 0


def test_pull_is_incremental_and_tracks_owner_changes(client: TestClient) -> None:
    col = FakeCollection([person("priya-s")])
    sync = attach(client, col)
    scan(client)
    first = sync.status.last_changes
    assert first["added"] == 1

    # nothing new: incremental cursor skips everything
    scan(client)
    assert sync.status.last_changes == {"added": 0, "updated": 0, "removed": 0, "unchanged": 0}

    # a second LinkedIn account also knows Priya: owners change, profile text doesn't
    later = T0 + timedelta(days=1)
    col.docs["priya-s"]["owners"].append({"account": "friend", "connected_on": later})
    col.docs["priya-s"]["migrated_at"] = later
    scan(client)
    assert sync.status.last_changes["updated"] == 1
    r = client.get("/api/search", params={"owner": "friend"}).json()
    assert r["total"] == 1 and set(r["items"][0]["owners"]) == {"me", "friend"}


def test_full_pull_removes_profiles_deleted_from_mongo(client: TestClient) -> None:
    col = FakeCollection([person("priya-s"), person("rahul-k", name="Rahul Kumar")])
    sync = attach(client, col)
    scan(client)
    del col.docs["rahul-k"]
    client.post("/api/connections/sync", params={"full": "true"})
    assert client.app.state.tl.queue.wait_idle(120)
    assert sync.status.last_changes["removed"] == 1
    assert sync.status.pulled == 1


def test_linkedin_record_has_no_file(client: TestClient) -> None:
    attach(client, FakeCollection([person("priya-s")]))
    scan(client)
    item = client.get("/api/search", params={"source": "linkedin"}).json()["items"][0]
    r = client.get(f"/api/cvs/{item['id']}/file")
    assert r.status_code == 404 and "LinkedIn" in r.json()["detail"]
    detail = client.get(f"/api/cvs/{item['id']}").json()
    assert "Acme Fintech" in detail["text"]


# ----------------------------------------------------------------------------- push


def test_push_links_cv_to_linkedin_person_or_creates_new(client: TestClient, cv_dir) -> None:
    make_pdf(
        cv_dir / "Priya_Sharma_CV.pdf",
        "Priya Sharma\nSenior Data Engineer\nBengaluru, India\n"
        "linkedin.com/in/Priya-S\npriya@example.com\n8 years of experience\nPython, Spark, SQL\n",
    )
    col = FakeCollection([person("priya-s")])
    sync = attach(client, col)
    scan(client)

    # Priya's CV contains her LinkedIn URL: linked to the existing person, profile untouched
    priya = col.docs["priya-s"]
    assert "cv" in priya["sources"] and "linkedin" in priya["sources"]
    assert priya["cv"]["filename"] == "Priya_Sharma_CV.pdf"
    assert priya["cv"]["email"] == "priya@example.com"
    assert priya["headline"] == "Senior Data Engineer at Acme Fintech"

    # the three fixture CVs have no LinkedIn URL: each becomes a new CV-only person
    new = [d for d in col.docs.values() if d["_id"].startswith("cv:")]
    assert len(new) == 3
    assert all(d["sources"] == ["cv"] and d["owners"] == [] for d in new)
    assert {d["full_name"] for d in new} >= {"Alice Example"}

    # pushing again does nothing (already up to date)
    pushes = len(col.updates)
    sync.push()
    assert len(col.updates) == pushes

    # the CV and the LinkedIn profile are one person in JD matching
    body = {
        "requirements": {"title": "Data Engineer", "must_have_skills": ["Python"]},
        "rerank": False,
    }
    items = client.post("/api/shortlist", json=body).json()["items"]
    priya_rows = [i for i in items if i.get("person_id") == "priya-s"]
    assert len(priya_rows) == 1
    assert priya_rows[0]["other_files"]


def test_sync_errors_never_break_indexing(client: TestClient) -> None:
    lib = client.app.state.tl.library

    def boom(_u: str) -> Any:
        raise RuntimeError("Authentication failed.")

    sync = ConnectionsSync(lib.db, lib.indexer, "mongodb://fake", client_factory=boom)
    lib.connections = sync
    lib.queue.after_scan.append(sync.run)
    scan(client)
    assert sync.status.state == "error"
    assert "username or password" in (sync.status.error or "")
    assert client.get("/api/search").json()["total"] == 3  # resumes still indexed


# ----------------------------------------------------------------------------- settings


def test_settings_never_echo_the_connection_string(client: TestClient) -> None:
    bad = client.put("/api/settings", json={"mongodb_uri": "not-a-uri"})
    assert bad.status_code == 400
    uri = "mongodb+srv://user:secret@cluster0.example.mongodb.net/?retryWrites=true"
    st = client.app.state.tl
    st.prefs.update(mongodb_uri=uri)  # set directly: reopening would try to reach the host
    s = client.get("/api/settings").json()
    assert s["connections"]["configured"] is True
    assert s["connections"]["host"] == "cluster0.example.mongodb.net"
    assert "secret" not in str(s)


@pytest.mark.parametrize("status", ["/api/connections/status"])
def test_status_off_without_database(client: TestClient, status: str) -> None:
    assert client.get(status).json()["state"] == "off"
