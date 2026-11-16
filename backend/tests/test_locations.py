"""Free-text locations: states and regions work in search filters, match scoring and the
filters on match results; the full written location is kept by the database itself."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from talentlens.ai.taxonomy import location_matches, location_term
from talentlens.db import Database
from talentlens.search import Filters
from talentlens.shortlist import location_score

from .conftest import make_pdf

NJ_FULL = "Jersey City, New Jersey, United States"

NINA = """Nina Jersey
Senior Data Engineer
Location: Hoboken, New Jersey, United States

Summary
Data engineer with 11 years of experience building Spark and Airflow pipelines on AWS for
banks. Python, SQL, Kafka, Databricks.
"""


def test_location_terms_cover_state_names_and_abbreviations() -> None:
    t = location_term("NJ")
    assert "%New Jersey%" in t.patterns and "%, NJ" in t.patterns
    assert set(location_term("new jersey").patterns) >= {"%New Jersey%", "%, NJ,%"}
    assert "Bengaluru" in location_term("Bangalore").exact  # city aliases still canonicalise
    assert location_term("  ").patterns == ()


@pytest.mark.parametrize(
    ("value", "city", "country", "full", "ok"),
    [
        ("New Jersey", "Jersey City", "United States", NJ_FULL, True),
        ("NJ", "Jersey City", "United States", NJ_FULL, True),
        ("NJ", "Austin", "United States", "Austin, TX", False),
        ("Princeton, NJ", "Princeton", "United States", "Princeton, NJ", True),
        ("Karnataka", "Bengaluru", "India", "Bangalore Urban, Karnataka, India", True),
        ("Bay Area", None, "United States", "San Francisco Bay Area", True),
        ("Bangalore", "Bengaluru", "India", None, True),  # alias -> canonical city column
        ("Texas", "Jersey City", "United States", NJ_FULL, False),
    ],
)
def test_location_matches(value: str, city: str, country: str, full: str, ok: bool) -> None:
    assert location_matches(value, city, country, full) is ok


def test_location_score_understands_states() -> None:
    assert location_score("Jersey City", "United States", ["New Jersey"], NJ_FULL) == 1.0
    assert location_score("Austin", "United States", ["New Jersey"], "Austin, Texas") == 0.7
    assert location_score("Pune", "India", ["New Jersey"], "Pune, India") == 0.0
    assert location_score("Pune", "India", ["Bengaluru"]) == 0.7  # old behaviour unchanged


def _insert(db: Database, rel: str, text: str, location: str | None = None) -> int:
    with db.connect() as c:
        cur = c.execute(
            "INSERT INTO cvs(rel_path, filename, ext, sha256, size, mtime, status, text, location) "
            "VALUES (?, ?, '.pdf', ?, 1, 0, 'indexed', ?, ?)",
            (rel, rel, rel, text, location),
        )
        return int(cur.lastrowid)


def test_database_keeps_the_full_location_by_itself(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.db")
    a = _insert(db, "a.pdf", "Ann\nLocation: Hoboken, New Jersey, United States\nmore")
    b = _insert(db, "b.pdf", "Bo resume without a location line", location="Pune, India")
    with db.connect() as c:
        full = dict(c.execute("SELECT id, location_full FROM cvs").fetchall())
        assert full[a] == "Hoboken, New Jersey, United States"
        assert full[b] == "Pune, India"
        # an update to the text keeps it current
        c.execute(
            "UPDATE cvs SET text = 'Ann\nLocation: Austin, Texas, United States' WHERE id=?", (a,)
        )
        assert c.execute("SELECT location_full FROM cvs WHERE id=?", (a,)).fetchone()[0] == (
            "Austin, Texas, United States"
        )
        # rows from before the column existed are filled once, when the database opens
        c.execute("UPDATE cvs SET location_full = NULL")
    Database(tmp_path / "t.db")
    with db.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM cvs WHERE location_full IS NULL").fetchone()[0] == 0

    def ids(*locations: str) -> set[int]:
        sql, args = Filters(locations=list(locations)).sql()
        with db.connect() as c:
            return {r[0] for r in c.execute(f"SELECT c.id FROM cvs c WHERE {sql}", args)}

    assert ids("Texas") == {a} and ids("TX") == {a}  # the abbreviation means the same state
    assert ids("NJ") == set()
    assert ids("Pune") == {b} and ids("India") == {b}
    assert ids("Texas", "Pune") == {a, b}  # several values: any of them


@pytest.fixture
def with_nina(client: TestClient, cv_dir: Path) -> TestClient:
    make_pdf(cv_dir / "Nina_Jersey.pdf", NINA)
    client.post("/api/index/refresh")
    assert client.app.state.tl.queue.wait_idle(120)
    return client


def test_search_filter_by_state(with_nina: TestClient) -> None:
    for value in ("New Jersey", "NJ", "new jersey"):
        r = with_nina.get("/api/search", params={"location": value}).json()
        assert [i["name"] for i in r["items"]] == ["Nina Jersey"], value
    r = with_nina.get("/api/search", params={"location": ["New Jersey", "Riyadh"]}).json()
    assert {i["name"] for i in r["items"]} == {"Nina Jersey", "Carol Placeholder"}
    facets = with_nina.get("/api/facets").json()
    assert any(f["value"] == "New Jersey" for f in facets["regions"]) or facets["regions"] == []


def test_match_results_filters(with_nina: TestClient) -> None:
    req = {"title": "Data Engineer", "must_have_skills": ["Python", "Spark"]}
    body = {"requirements": req, "jd_text": "Data engineer, Python and Spark", "rerank": False}
    everyone = with_nina.post("/api/shortlist", json=body).json()
    names = {i["name"] for i in everyone["items"]}
    assert {"Nina Jersey", "Alice Example"} <= names  # no filters: same pool as before

    nj = with_nina.post("/api/shortlist", json={**body, "filters": {"locations": ["NJ"]}}).json()
    assert [i["name"] for i in nj["items"]] == ["Nina Jersey"]

    senior = with_nina.post(
        "/api/shortlist", json={**body, "filters": {"years_min": 10, "domains": []}}
    ).json()
    assert senior["items"] and all((i["years_exp"] or 0) >= 10 for i in senior["items"])

    files_only = with_nina.post("/api/shortlist", json={**body, "sources": ["linkedin"]}).json()
    assert files_only["items"] == []  # the fixture library has resumes only
