import io

import pytest
from docx import Document
from fastapi.testclient import TestClient

from talentlens.config import Settings
from talentlens.jd import Requirements, parse_rules
from talentlens.shortlist import experience_score, location_score

from .conftest import ALICE, make_pdf

DATA_JD = """Senior Data Engineer - Bengaluru, India

About the role
We are a fintech company building lending and payments products.

Requirements
- 5-10 years of experience in data engineering
- Strong Python and SQL
- Apache Spark and Airflow
- AWS

Nice to have
- Kubernetes
- Terraform
"""

TELECOM_JD = """RAN Engineer, Riyadh, Saudi Arabia
Must have: 4G/LTE and 5G RAN optimisation on Ericsson or Nokia, NOC operations.
Minimum 4 years of experience in telecommunications.
"""


@pytest.fixture
def indexed(client: TestClient) -> TestClient:
    client.post("/api/index/refresh")
    assert client.app.state.tl.queue.wait_idle(120)
    return client


def test_parse_rules_sections_years_location() -> None:
    r = parse_rules(DATA_JD)
    assert {"Python", "SQL", "Apache Spark", "Apache Airflow", "Amazon Web Services"} <= set(
        r.must_have_skills
    )
    assert {"Kubernetes", "Terraform"} <= set(r.nice_to_have_skills)
    assert not set(r.must_have_skills) & set(r.nice_to_have_skills)
    assert (r.min_years, r.max_years) == (5, 10)
    assert r.locations == ["Bengaluru"]
    assert "Senior Data Engineer" in (r.title or "")


def test_score_helpers() -> None:
    assert experience_score(7, 5, 10) == 1.0
    assert experience_score(3, 5, None) == pytest.approx(0.6)
    assert experience_score(None, 5, None) == 0.4
    assert experience_score(15, 5, 10) == 0.5
    assert experience_score(4, None, None) == 1.0
    assert location_score("Pune", "India", ["Bengaluru"]) == 0.7
    assert location_score("Bengaluru", "India", ["Bengaluru"]) == 1.0
    assert location_score("Dubai", "United Arab Emirates", ["India"]) == 0.0
    assert location_score(None, None, []) == 1.0


def test_parse_endpoint_text_and_ai_mode(indexed: TestClient) -> None:
    r = indexed.post("/api/jd/parse", data={"text": DATA_JD}).json()
    assert r["requirements"]["source"] == "rules"
    r = indexed.post("/api/jd/parse", data={"text": DATA_JD, "mode": "ai"}).json()
    assert r["requirements"]["source"] == "llm" and r["warning"] is None


def test_parse_endpoint_files(indexed: TestClient) -> None:
    d = Document()
    for line in TELECOM_JD.splitlines():
        d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    r = indexed.post(
        "/api/jd/parse", files={"file": ("jd.docx", buf.getvalue(), "application/octet-stream")}
    )
    assert r.status_code == 200
    req = r.json()["requirements"]
    assert "RAN" in req["must_have_skills"]
    assert req["locations"] == ["Riyadh"]

    r = indexed.post("/api/jd/parse", files={"file": ("jd.txt", DATA_JD.encode(), "text/plain")})
    assert r.status_code == 200
    bad = indexed.post("/api/jd/parse", files={"file": ("jd.exe", b"MZ", "x")})
    assert bad.status_code == 400
    fake = indexed.post("/api/jd/parse", files={"file": ("jd.pdf", b"not a pdf", "x")})
    assert fake.status_code == 400
    empty = indexed.post("/api/jd/parse", data={"text": "hi"})
    assert empty.status_code == 400


def _shortlist(client: TestClient, jd: str) -> dict:
    req = client.post("/api/jd/parse", data={"text": jd}).json()
    r = client.post(
        "/api/shortlist", json={"requirements": req["requirements"], "jd_text": req["jd_text"]}
    )
    assert r.status_code == 200
    return r.json()


def test_shortlist_ranks_the_right_people(indexed: TestClient) -> None:
    data = _shortlist(indexed, DATA_JD)
    top = data["items"][0]
    assert top["name"] == "Alice Example"
    assert top["rank"] == 1
    assert set(top["breakdown"]) == {"semantic", "must", "nice", "experience", "domain", "location"}
    assert abs(sum(top["breakdown"].values()) - top["score"]) < 0.5
    assert "Python" in top["matched_must"]
    assert data["items"][0]["score"] > data["items"][-1]["score"]

    tel = _shortlist(indexed, TELECOM_JD)
    assert tel["items"][0]["name"] == "Carol Placeholder"


def test_explain_with_mock_llm(indexed: TestClient) -> None:
    data = _shortlist(indexed, DATA_JD)
    req = indexed.post("/api/jd/parse", data={"text": DATA_JD}).json()["requirements"]
    r = indexed.post(
        "/api/shortlist/explain", json={"cv_id": data["items"][0]["id"], "requirements": req}
    )
    assert r.status_code == 200 and r.json()["reason"]
    missing = indexed.post("/api/shortlist/explain", json={"cv_id": 9999, "requirements": req})
    assert missing.status_code == 404


def test_saved_shortlists_and_csv(indexed: TestClient) -> None:
    data = _shortlist(indexed, DATA_JD)
    req = Requirements(title="DE", must_have_skills=["Python"]).as_dict()
    rows = data["items"][:2]
    rows[0]["title"] = "=HYPERLINK(evil)"  # formula injection attempt
    created = indexed.post(
        "/api/shortlists",
        json={"name": "Data Eng / Nov", "jd_text": DATA_JD, "requirements": req, "results": rows},
    )
    assert created.status_code == 201
    sid = created.json()["id"]
    listing = indexed.get("/api/shortlists").json()
    assert listing[0]["id"] == sid and listing[0]["count"] == 2
    full = indexed.get(f"/api/shortlists/{sid}").json()
    assert full["results"][0]["name"] == rows[0]["name"]

    csv_resp = indexed.get(f"/api/shortlists/{sid}/export.csv")
    assert csv_resp.status_code == 200
    body = csv_resp.content.decode("utf-8-sig")
    assert body.splitlines()[0].startswith("rank,score,name")
    assert "'=HYPERLINK(evil)" in body
    assert "attachment" in csv_resp.headers["content-disposition"]

    assert indexed.delete(f"/api/shortlists/{sid}").status_code == 204
    assert indexed.get(f"/api/shortlists/{sid}").status_code == 404


def test_same_person_collapses(indexed: TestClient, settings: Settings) -> None:
    # a second, different file for the same person (e.g. an older version)
    make_pdf(settings.cv_dir / "Alice_Example_Resume_old.pdf", ALICE + "\nReferences on request")
    indexed.post("/api/index/refresh")
    assert indexed.app.state.tl.queue.wait_idle(120)
    data = _shortlist(indexed, DATA_JD)
    alices = [i for i in data["items"] if i["name"] == "Alice Example"]
    assert len(alices) == 1
    assert alices[0]["other_files"][0]["filename"].startswith("Alice_Example_Resume")


def test_shortlist_requires_something(indexed: TestClient) -> None:
    r = indexed.post("/api/shortlist", json={"requirements": {}, "jd_text": ""})
    assert r.status_code == 400
