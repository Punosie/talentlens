import pytest
from fastapi.testclient import TestClient

from talentlens.search import fts_query


@pytest.fixture
def indexed(client: TestClient) -> TestClient:
    client.post("/api/index/refresh")
    assert client.app.state.tl.queue.wait_idle(120)
    return client


def _names(r: dict) -> list[str]:
    return [i["name"] for i in r["items"]]


def test_text_search_ranks_relevant_first(indexed: TestClient) -> None:
    r = indexed.get("/api/search", params={"q": "airflow spark data engineer"}).json()
    assert _names(r)[0] == "Alice Example"
    assert r["items"][0]["score"] == 1.0
    assert "[[" in (r["items"][0]["snippet"] or "")


def test_skill_filters_all_vs_any(indexed: TestClient) -> None:
    both = indexed.get("/api/search", params={"skills": ["Python", "Ericsson"]}).json()
    assert _names(both) == ["Carol Placeholder"]  # Carol has both
    none = indexed.get("/api/search", params={"skills": ["Python", "SAP Retail"]}).json()
    assert _names(none) == []
    anyof = indexed.get(
        "/api/search", params={"skills": ["Python", "SAP Retail"], "skills_mode": "any"}
    ).json()
    assert set(_names(anyof)) == {"Alice Example", "Bob Sample", "Carol Placeholder"}
    assert anyof["items"][0]["matched_skills"]


def test_years_location_domain_filters(indexed: TestClient) -> None:
    r = indexed.get("/api/search", params={"years_min": 6}).json()
    assert set(_names(r)) == {"Alice Example", "Bob Sample"}
    r = indexed.get("/api/search", params={"years_min": 6, "years_max": 10}).json()
    assert _names(r) == ["Alice Example"]
    r = indexed.get("/api/search", params={"location": ["United Arab Emirates"]}).json()
    assert _names(r) == ["Bob Sample"]
    r = indexed.get("/api/search", params={"location": ["riyadh"]}).json()
    assert _names(r) == ["Carol Placeholder"]
    r = indexed.get("/api/search", params={"domain": ["Telecommunications"]}).json()
    assert _names(r) == ["Carol Placeholder"]


def test_sorting(indexed: TestClient) -> None:
    r = indexed.get("/api/search", params={"sort": "experience"}).json()
    assert _names(r) == ["Bob Sample", "Alice Example", "Carol Placeholder"]
    r = indexed.get("/api/search", params={"sort": "name"}).json()
    assert _names(r) == ["Alice Example", "Bob Sample", "Carol Placeholder"]


def test_facets(indexed: TestClient) -> None:
    f = indexed.get("/api/facets").json()
    skills = {s["value"] for s in f["skills"]}
    assert {"Python", "Ericsson", "SAP Retail"} <= skills
    assert {c["value"] for c in f["countries"]} == {"India", "United Arab Emirates", "Saudi Arabia"}
    assert f["years"]["min"] == 5 and f["years"]["max"] == 12


def test_weird_queries_are_safe(indexed: TestClient) -> None:
    for q in ['"', "AND OR NOT", "c++ c#", "*", "NEAR(", "'; DROP TABLE cvs; --"]:
        assert indexed.get("/api/search", params={"q": q}).status_code == 200
    assert indexed.get("/api/cvs").json()["total"] == 3


def test_fts_query_builder() -> None:
    assert fts_query("python aws") == '"python" AND "aws"*'
    assert fts_query("c++ c#", "or") == '"c++" OR "c#"'
    assert fts_query("   ") is None


def test_llm_stage_refines_and_survives_reindex(indexed: TestClient) -> None:
    st = indexed.app.state.tl
    with st.db.connect() as conn:
        rows = conn.execute("SELECT extractor, llm_sha, sha256, confident FROM cvs").fetchall()
    # every CV is either read by the AI, or confidently read by the rules (AI not needed)
    assert all(
        (r["extractor"] == "llm" and r["llm_sha"] == r["sha256"]) or r["confident"] for r in rows
    )
    before = {tuple(r) for r in rows}
    calls = st.llm.calls
    indexed.post("/api/index/refresh", params={"full": "true"})
    assert st.queue.wait_idle(120)
    assert st.llm.calls == calls  # nothing recomputed by the LLM
    with st.db.connect() as conn:
        after = {
            tuple(r) for r in conn.execute("SELECT extractor, llm_sha, sha256, confident FROM cvs")
        }
    assert after == before


def test_ai_pause(indexed: TestClient) -> None:
    s = indexed.post("/api/index/ai", params={"paused": "true"}).json()
    assert s["ai_paused"] is True
    s = indexed.post("/api/index/ai", params={"paused": "false"}).json()
    assert s["ai_paused"] is False
