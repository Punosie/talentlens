"""Shared fixtures. All resumes here are synthetic, generated at test time."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pymupdf
import pytest
from docx import Document
from fastapi.testclient import TestClient

from talentlens.config import Settings

ALICE = """Alice Example
Senior Data Engineer | Bengaluru, India | alice@example.com | +91 98765 43210

Summary
Data engineer with 7 years of experience building pipelines in Python, Spark and Airflow
for banking and fintech clients. Strong SQL, AWS and Kubernetes skills.

Experience
Senior Data Engineer, Fintech Corp (Jan 2020 - Present)
Data Engineer, Big Bank Ltd (Jun 2017 - Dec 2019)

Education
B.Tech Computer Science, 2017
"""

BOB = """Bob Sample
Retail Store Manager | Dubai, UAE | bob@example.org

Over 12 years of experience in retail operations, merchandising, P&L ownership and
team leadership across supermarkets and FMCG brands. Skilled in SAP Retail and Excel.

Experience
Store Manager, MegaMart (2014 - 2025)
Assistant Manager, ShopCo (2012 - 2014)
"""

CAROL = """Carol Placeholder
Telecom Network Engineer, Riyadh, Saudi Arabia
5 years of experience with 4G/5G RAN, Ericsson and Nokia equipment, NOC operations,
Python scripting and Linux. Telecommunications domain specialist.
"""


def make_pdf(path: Path, text: str) -> Path:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(50, 50, 550, 800), text, fontsize=10)
    doc.save(path)
    doc.close()
    return path


def make_image_pdf(path: Path, text: str) -> Path:
    """A 'scanned' PDF: the page is only an image of the text, with no text layer."""
    src = pymupdf.open()
    page = src.new_page()
    page.insert_textbox(pymupdf.Rect(50, 50, 550, 800), text, fontsize=14)
    pix = page.get_pixmap(dpi=150)
    src.close()
    out = pymupdf.open()
    p = out.new_page(width=pix.width, height=pix.height)
    p.insert_image(p.rect, stream=pix.tobytes("png"))
    out.save(path)
    out.close()
    return path


def make_docx(
    path: Path, text: str, *, header: str | None = None, table: list[list[str]] | None = None
) -> Path:
    d = Document()
    if header:
        d.sections[0].header.paragraphs[0].text = header
    for line in text.splitlines():
        d.add_paragraph(line)
    if table:
        t = d.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, val in enumerate(row):
                t.cell(r, c).text = val
    d.save(path)
    return path


@pytest.fixture
def cv_dir(tmp_path: Path) -> Path:
    d = tmp_path / "cvs" / "files"
    d.mkdir(parents=True)
    make_pdf(d / "Alice_Example_Resume.pdf", ALICE)
    make_docx(d / "Bob Sample CV.docx", BOB, header="Bob Sample - Curriculum Vitae")
    make_pdf(d / "Carol_Placeholder.pdf", CAROL)
    return d


@pytest.fixture
def settings(tmp_path: Path, cv_dir: Path) -> Settings:
    return Settings(
        cv_dir=cv_dir,
        data_dir=tmp_path / "appdata",
        llm="mock",
        embeddings="mock",
        watch=False,
        scan_on_startup=False,
        update_check=False,  # never call GitHub from tests
        _env_file=None,  # never read the developer's .env in tests
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    from talentlens.main import create_app

    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def snapshot(folder: Path) -> dict[str, tuple[int, float, bytes]]:
    """Byte-level snapshot used to prove that source files are never modified."""
    return {
        p.name: (p.stat().st_size, p.stat().st_mtime, p.read_bytes())
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }
