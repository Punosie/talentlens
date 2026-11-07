from pathlib import Path

import pytest

from talentlens.parsing import (
    ParseError,
    decode_text_bytes,
    normalize_text,
    parse_bytes,
    parse_file,
)

from .conftest import ALICE, make_docx, make_image_pdf, make_pdf


def test_pdf_text_layer(tmp_path: Path) -> None:
    r = parse_file(make_pdf(tmp_path / "a.pdf", ALICE))
    assert "Senior Data Engineer" in r.text
    assert r.parser == "pymupdf"
    assert r.pages == 1
    assert not r.ocr_used


def test_docx_body_header_and_table(tmp_path: Path) -> None:
    p = make_docx(
        tmp_path / "b.docx",
        "Jane Doe\nProduct Manager",
        header="Jane Doe | jane@example.com",
        table=[["Skill", "Years"], ["Kubernetes", "4"]],
    )
    r = parse_file(p)
    assert "jane@example.com" in r.text  # from the header
    assert "Product Manager" in r.text
    assert "Kubernetes" in r.text  # from the table
    assert r.text.index("jane@example.com") < r.text.index("Product Manager")


def test_scanned_pdf_uses_ocr(tmp_path: Path) -> None:
    p = make_image_pdf(tmp_path / "scan.pdf", "Rahul Verma\nCloud Architect\nAzure and Terraform")
    r = parse_file(p)
    assert r.ocr_used
    assert "Architect" in r.text
    assert "Terraform" in r.text


def test_corrupt_files_raise_parse_error(tmp_path: Path) -> None:
    bad_pdf = tmp_path / "bad.pdf"
    bad_pdf.write_bytes(b"%PDF-1.4 garbage")
    bad_docx = tmp_path / "bad.docx"
    bad_docx.write_bytes(b"PK\x03\x04 not really a zip")
    for p in (bad_pdf, bad_docx):
        with pytest.raises(ParseError):
            parse_file(p)


def test_txt_and_bytes(tmp_path: Path) -> None:
    assert decode_text_bytes("Café".encode("cp1252")) == "Café"
    assert decode_text_bytes("naïve".encode("utf-16")) == "naïve"
    r = parse_bytes("jd.txt", b"Need a Python developer\r\n\r\n\r\n\r\nwith AWS")
    assert r.text == "Need a Python developer\n\nwith AWS"


def test_normalize_text() -> None:
    assert normalize_text("a \t\nb\x00c\n\n\n\nd") == "a\nb c\n\nd"
