"""Start TalentLens against a throwaway fixture folder for Playwright end-to-end tests.

    uv run python backend/tests/e2e_server.py --root <tmp dir> --port 8799

Creates:
  <root>/cvs/files/     three synthetic resumes (the "library")
  <root>/samples/       files the tests upload or drop in (new, duplicate, invalid, a JD)
  <root>/appdata/       app state
Real resumes are never used.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # .../backend

import uvicorn

from talentlens.config import Settings
from talentlens.main import create_app
from tests.conftest import ALICE, BOB, CAROL, make_docx, make_pdf

DAVE = """Dave Fixture
Cloud DevOps Engineer | Pune, India | dave@example.net
9 years of experience with Kubernetes, Terraform, AWS, Jenkins and Python automation.
Built CI/CD pipelines for retail e-commerce platforms.
"""

JD = """Senior Data Engineer - Bengaluru, India
Requirements
- 5-10 years of experience in data engineering
- Python, SQL, Apache Spark and Airflow
- AWS
Nice to have
- Kubernetes
"""


def build(root: Path) -> None:
    if root.exists():
        shutil.rmtree(root)
    lib = root / "cvs" / "files"
    samples = root / "samples"
    lib.mkdir(parents=True)
    samples.mkdir(parents=True)
    make_pdf(lib / "Alice_Example_Resume.pdf", ALICE)
    make_docx(lib / "Bob Sample CV.docx", BOB, header="Bob Sample - Curriculum Vitae")
    make_pdf(lib / "Carol_Placeholder.pdf", CAROL)

    make_pdf(samples / "Dave_Fixture_Resume.pdf", DAVE)
    make_pdf(
        samples / "Erin_Dropin.pdf",
        "Erin Dropin\nProduct Manager | Dubai, UAE\n8 years of experience in fintech payments, "
        "product strategy, Agile and Jira.",
    )
    shutil.copyfile(lib / "Alice_Example_Resume.pdf", samples / "alice-copy.pdf")
    (samples / "not-really.pdf").write_bytes(b"this is plain text pretending to be a PDF")
    (samples / "jd.txt").write_text(JD, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument(
        "--demo", action="store_true", help="fictional demo library + real embeddings (screenshots)"
    )
    args = ap.parse_args()
    root = Path(args.root)
    build(root)
    if args.demo:
        from tests.demo_data import DEMO_RESUMES

        for name, text in DEMO_RESUMES.items():
            make_pdf(root / "cvs" / "files" / name, text)
        # reuse already-downloaded models instead of fetching them again
        cached = Settings(_env_file=None).model_cache_dir
        if cached.is_dir():
            shutil.copytree(cached, root / "appdata" / "models", dirs_exist_ok=True)
    settings = Settings(
        cv_dir=root / "cvs" / "files",
        data_dir=root / "appdata",
        port=args.port,
        llm="mock",
        embeddings="fastembed" if args.demo else "mock",
        watch=True,
        scan_on_startup=True,
        _env_file=None,
    )
    uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
