import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from talentlens import bulk
from talentlens.config import Settings

from .conftest import ALICE, make_docx, make_pdf, snapshot

DAVE = "Dave Zipped\nCloud Engineer | Pune, India\n9 years of experience with Kubernetes and AWS."
ERIN = "Erin Zipped\nProduct Manager | Dubai, UAE\n8 years of experience in fintech payments."


def _zip(entries: dict[str, bytes], *, level: int = zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=level) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


def _pdf_bytes(tmp_path: Path, name: str, text: str) -> bytes:
    return make_pdf(tmp_path / name, text).read_bytes()


def _wait(client: TestClient) -> None:
    assert client.app.state.tl.queue.wait_idle(60)


def test_zip_import_mixed_contents(client: TestClient, settings: Settings, tmp_path: Path) -> None:
    client.post("/api/index/refresh")
    _wait(client)
    before = snapshot(settings.cv_dir)
    docx = make_docx(tmp_path / "erin.docx", ERIN).read_bytes()
    archive = _zip(
        {
            "Hiring Q3/Dave Zipped.pdf": _pdf_bytes(tmp_path, "d.pdf", DAVE),
            "Hiring Q3/sub/Erin Zipped.docx": docx,
            "Hiring Q3/../../escape.pdf": _pdf_bytes(tmp_path, "e.pdf", "Evil Escape\nHacker"),
            "Hiring Q3/notes.txt": b"just notes",
            "__MACOSX/._Dave Zipped.pdf": b"junk",
            "Hiring Q3/.DS_Store": b"junk",
            "Hiring Q3/inner.zip": _zip({"x.pdf": b"%PDF-1.4"}),
            "Hiring Q3/alice-again.pdf": (
                settings.cv_dir / "Alice_Example_Resume.pdf"
            ).read_bytes(),
        }
    )
    r = client.post("/api/cvs", files=[("files", ("q3.zip", archive, "application/zip"))]).json()
    by = {x["filename"].split(" › ")[-1]: x for x in r["results"]}
    assert by["Dave Zipped.pdf"]["status"] == "added"
    assert by["Erin Zipped.docx"]["status"] == "added"
    assert by["escape.pdf"]["status"] == "skipped"  # "../" entries are refused, never written
    assert "Unsafe path" in by["escape.pdf"]["message"]
    assert by["notes.txt"]["status"] == "skipped"
    assert by["inner.zip"]["status"] == "skipped"
    assert by["alice-again.pdf"]["status"] == "duplicate"
    assert "._Dave Zipped.pdf" not in by and ".DS_Store" not in by
    assert r["summary"] == {"added": 2, "duplicate": 1, "rejected": 0, "skipped": 3}
    assert not (settings.cv_dir.parent / "escape.pdf").exists()
    assert not (settings.cv_dir.parent.parent / "escape.pdf").exists()

    after = snapshot(settings.cv_dir)
    for name, snap in before.items():
        assert after[name] == snap  # existing files untouched

    _wait(client)
    paths = [x["rel_path"] for x in r["results"] if x["status"] == "added"]
    status = client.get("/api/cvs/status", params={"paths": paths}).json()
    assert {s["state"] for s in status.values()} == {"ready"}
    assert client.get("/api/search", params={"q": "Kubernetes"}).json()["items"][0]["name"] == (
        "Dave Zipped"
    )


def test_zip_bomb_and_limits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bomb = _zip({"big.pdf": b"%PDF" + b"0" * 5_000_000})  # ~5 MB of zeros compresses ~1000x
    with pytest.raises(bulk.ArchiveRejected, match="unsafe"):
        list(bulk.iter_zip(io.BytesIO(bomb), max_file_bytes=20 * 1024 * 1024))

    monkeypatch.setattr(bulk, "MAX_ENTRIES", 3)
    many = _zip({f"{i}.pdf": b"%PDF" for i in range(5)}, level=zipfile.ZIP_STORED)
    with pytest.raises(bulk.ArchiveRejected, match="at most 3"):
        list(bulk.iter_zip(io.BytesIO(many), max_file_bytes=1024))

    with pytest.raises(bulk.ArchiveRejected, match="valid ZIP"):
        list(bulk.iter_zip(io.BytesIO(b"PK\x03\x04 broken"), max_file_bytes=1024))

    big = _zip({"huge.pdf": b"%PDF" + bytes(range(256)) * 9000}, level=zipfile.ZIP_STORED)
    items = list(bulk.iter_zip(io.BytesIO(big), max_file_bytes=1024))
    assert items[0].data is None and "Larger than" in (items[0].skipped or "")


def test_bad_zip_is_reported_not_crashing(client: TestClient) -> None:
    r = client.post("/api/cvs", files=[("files", ("broken.zip", b"PK\x03\x04no", "x"))]).json()
    assert r["results"][0]["status"] == "rejected" and r["added"] == 0


def test_batch_of_many_files(client: TestClient, tmp_path: Path) -> None:
    files = [
        (
            "files",
            (
                f"Person{i}.pdf",
                _pdf_bytes(tmp_path, f"p{i}.pdf", f"Person Number{i}\n" + ALICE),
                "application/pdf",
            ),
        )
        for i in range(12)
    ]
    r = client.post("/api/cvs", files=files).json()
    assert r["summary"]["added"] == 12
    too_many = [files[0]] * 51
    assert client.post("/api/cvs", files=too_many).status_code == 400
