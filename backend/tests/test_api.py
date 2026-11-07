from pathlib import Path

from fastapi.testclient import TestClient

from talentlens.config import Settings

from .conftest import ALICE, make_pdf, snapshot


def _wait(client: TestClient) -> None:
    assert client.app.state.tl.queue.wait_idle(60)


def test_health(client: TestClient, settings: Settings) -> None:
    r = client.get("/api/health").json()
    assert r["status"] == "ok"
    assert r["cv_dir_exists"] is True


def test_refresh_then_list_and_detail(client: TestClient) -> None:
    assert client.post("/api/index/refresh").status_code == 202
    _wait(client)
    data = client.get("/api/cvs").json()
    assert data["total"] == 3
    cv = next(i for i in data["items"] if i["filename"] == "Alice_Example_Resume.pdf")
    detail = client.get(f"/api/cvs/{cv['id']}").json()
    assert "Airflow" in detail["text"]
    f = client.get(f"/api/cvs/{cv['id']}/file")
    assert f.status_code == 200 and f.content.startswith(b"%PDF")
    assert "inline" in f.headers["content-disposition"]
    d = client.get(f"/api/cvs/{cv['id']}/file?download=true")
    assert "attachment" in d.headers["content-disposition"]
    assert client.get("/api/cvs/99999").status_code == 404


def test_upload_flow(client: TestClient, settings: Settings, tmp_path: Path) -> None:
    client.post("/api/index/refresh")
    _wait(client)
    before = snapshot(settings.cv_dir)

    new_pdf = make_pdf(tmp_path / "Eve.pdf", ALICE.replace("Alice Example", "Eve Newcomer"))
    dup = settings.cv_dir / "Alice_Example_Resume.pdf"
    files = [
        ("files", ("Eve.pdf", new_pdf.read_bytes(), "application/pdf")),
        ("files", ("copy.pdf", dup.read_bytes(), "application/pdf")),
        ("files", ("virus.exe", b"MZ", "application/octet-stream")),
    ]
    r = client.post("/api/cvs", files=files).json()
    statuses = {x["filename"]: x["status"] for x in r["results"]}
    assert statuses == {"Eve.pdf": "added", "copy.pdf": "duplicate", "virus.exe": "rejected"}
    assert r["added"] == 1

    _wait(client)  # the upload queued an index job automatically
    items = client.get("/api/cvs").json()["items"]
    assert any(i["filename"] == "Eve.pdf" and i["status"] == "indexed" for i in items)

    after = snapshot(settings.cv_dir)
    for name, snap in before.items():
        assert after[name] == snap  # existing files untouched
    assert set(after) - set(before) == {"Eve.pdf"}


def test_index_status_counts(client: TestClient) -> None:
    client.post("/api/index/refresh")
    _wait(client)
    s = client.get("/api/index/status").json()
    assert s["state"] == "idle"
    assert s["counts"]["indexed"] == 3
    assert s["last_report"]["added"] == 3
