from pathlib import Path

import pytest

from talentlens.storage import (
    CVStore,
    DuplicateUpload,
    UploadRejected,
    safe_filename,
    sha256_file,
)

from .conftest import snapshot

MB = 1024 * 1024


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd.pdf", "passwd.pdf"),
        ("..\\..\\Windows\\evil.DOCX", "evil.docx"),
        ("C:\\Users\\x\\cv.pdf", "cv.pdf"),
        ('we<ird>:na"me?.pdf', "we_ird__na_me_.pdf"),
        ("CON.pdf", "_CON.pdf"),
        ("   .pdf", "resume.pdf"),
    ],
)
def test_safe_filename(raw: str, expected: str) -> None:
    assert safe_filename(raw) == expected


def _pdf_bytes(cv_dir: Path) -> bytes:
    return (cv_dir / "Alice_Example_Resume.pdf").read_bytes()


def test_upload_rejects_duplicate_even_when_unindexed(cv_dir: Path) -> None:
    store = CVStore(cv_dir)
    with pytest.raises(DuplicateUpload) as e:
        store.save_upload("other-name.pdf", _pdf_bytes(cv_dir), max_bytes=20 * MB, known_hashes={})
    assert e.value.existing_rel_path == "Alice_Example_Resume.pdf"


def test_upload_never_overwrites_on_name_collision(cv_dir: Path) -> None:
    before = snapshot(cv_dir)
    data = b"%PDF-1.4\n" + b"different content" * 10
    store = CVStore(cv_dir)
    path, _ = store.save_upload(
        "Alice_Example_Resume.pdf", data, max_bytes=20 * MB, known_hashes={}
    )
    assert path.name == "Alice_Example_Resume (2).pdf"
    after = snapshot(cv_dir)
    for name, snap in before.items():
        assert after[name] == snap  # untouched, byte for byte


def test_upload_validations(cv_dir: Path) -> None:
    store = CVStore(cv_dir)
    with pytest.raises(UploadRejected, match="Unsupported"):
        store.save_upload("x.exe", b"MZ....", max_bytes=MB, known_hashes={})
    with pytest.raises(UploadRejected, match="not a valid PDF"):
        store.save_upload("x.pdf", b"PK\x03\x04zip", max_bytes=MB, known_hashes={})
    with pytest.raises(UploadRejected, match="larger than"):
        store.save_upload("x.pdf", b"%PDF" + b"0" * MB, max_bytes=MB, known_hashes={})
    with pytest.raises(UploadRejected, match="empty"):
        store.save_upload("x.pdf", b"", max_bytes=MB, known_hashes={})


def test_upload_traversal_lands_inside_root(cv_dir: Path) -> None:
    store = CVStore(cv_dir)
    path, _ = store.save_upload("../../escape.pdf", b"%PDF-1.4 new", max_bytes=MB, known_hashes={})
    assert path.parent == cv_dir
    assert not (cv_dir.parent.parent / "escape.pdf").exists()


def test_resolve_rel_refuses_escape(cv_dir: Path) -> None:
    store = CVStore(cv_dir)
    with pytest.raises(UploadRejected):
        store.resolve_rel("../outside.pdf")


def test_iter_files_skips_temp_and_other_types(cv_dir: Path) -> None:
    (cv_dir / "~$lock.docx").write_bytes(b"x")
    (cv_dir / "notes.txt").write_text("hi")
    names = [f.rel_path for f in CVStore(cv_dir).iter_files()]
    assert names == ["Alice_Example_Resume.pdf", "Bob Sample CV.docx", "Carol_Placeholder.pdf"]


def test_sha256_is_uppercase_hex(cv_dir: Path) -> None:
    h = sha256_file(cv_dir / "Carol_Placeholder.pdf")
    assert len(h) == 64 and h == h.upper()
