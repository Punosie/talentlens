"""Background smart reading: confidence gate, priority order, duplicate reuse, migrations."""

import json
from pathlib import Path

from talentlens.ai import rules
from talentlens.ai.extract import compact_input
from talentlens.config import Settings
from talentlens.db import Database
from talentlens.state import AppState

from .conftest import ALICE, BOB, make_pdf

CONFIDENT = """Ravi Kumar
Senior Data Engineer | Bengaluru, India | ravi@example.com
I have 9 years of experience building data platforms with Python and Spark.
"""


def test_confidence_gate() -> None:
    f = rules.extract(CONFIDENT, "Ravi_Kumar_Resume.pdf")
    assert f.confident is True
    # file name disagrees with the name in the text -> not confident
    assert rules.extract(CONFIDENT, "CV-2024-final.pdf").confident is False
    # no stated total years -> not confident
    assert (
        rules.extract(CONFIDENT.replace("I have 9 years of", "Lots of"), "Ravi_Kumar.pdf").confident
        is False
    )


def test_confident_cvs_skip_the_llm(settings: Settings) -> None:
    make_pdf(settings.cv_dir / "Ravi_Kumar_Resume.pdf", CONFIDENT)
    st = AppState.build(settings)
    st.indexer.run()
    with st.db.connect() as conn:
        conf = dict(conn.execute("SELECT filename, confident FROM cvs").fetchall())
    assert conf["Ravi_Kumar_Resume.pdf"] == 1
    pending_before = st.indexer.pending_llm_count()
    assert pending_before == len(conf) - sum(conf.values())
    calls = st.llm.calls
    st.indexer.refine_pending(should_stop=lambda: False)
    assert st.llm.calls - calls == pending_before  # the confident one was never sent
    assert st.indexer.pending_llm_count() == 0


def _generic_names(settings: Settings) -> None:
    """Rename-free setup: copies under generic file names, so the rules aren't confident."""
    for i, text in enumerate([ALICE, BOB], start=1):
        make_pdf(settings.cv_dir / f"resume-{i}.pdf", text)


def test_priority_order_is_respected_mid_pass(settings: Settings) -> None:
    _generic_names(settings)
    st = AppState.build(settings)
    st.indexer.run()
    with st.db.connect() as conn:
        ids = {r["filename"]: r["id"] for r in conn.execute("SELECT id, filename FROM cvs")}
    st.indexer.prioritize([ids["resume-1.pdf"]])
    seen: list[str] = []
    st.indexer.refine_pending(
        should_stop=lambda: len(seen) >= 1, progress=lambda d, t, cur: cur and seen.append(cur)
    )
    assert seen[0] == "resume-1.pdf"


def test_duplicate_reuses_twin_result(settings: Settings) -> None:
    _generic_names(settings)
    make_pdf(settings.cv_dir / "resume-3.pdf", ALICE + "\nReferences on request.")  # Alice again
    st = AppState.build(settings)
    st.indexer.run()
    calls = st.llm.calls
    report = st.indexer.refine_pending(should_stop=lambda: False)
    assert report["reused"] == 1  # same email as the other Alice file
    assert st.llm.calls - calls == report["refined"] - 1


def test_compact_input_keeps_header_and_dates() -> None:
    long_cv = ALICE + ("\nFiller line about projects." * 200) + "\nAnalyst, Old Co (2010 - 2012)\n"
    out = compact_input(long_cv)
    assert out.startswith("Alice Example") and "2010 - 2012" in out
    assert len(out) < 3500


def test_old_database_is_migrated_in_place(tmp_path: Path) -> None:
    import sqlite3

    p = tmp_path / "old.db"
    Database(p)  # create, then turn it back into a v0.1 database (no v0.2 columns)
    with sqlite3.connect(p) as c:
        c.execute("DROP INDEX ix_cvs_ai_queue")
        c.execute("ALTER TABLE cvs DROP COLUMN confident")
        c.execute("ALTER TABLE cvs DROP COLUMN ai_priority")
        c.execute("UPDATE meta SET value='1' WHERE key='schema_version'")
        c.execute(
            "INSERT INTO cvs(rel_path, filename, ext, sha256, size, mtime) "
            "VALUES ('a.pdf','a.pdf','.pdf','X',1,1)"
        )
    db = Database(p)
    with db.connect() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(cvs)")}
        assert {"confident", "ai_priority"} <= cols
        assert conn.execute("SELECT filename FROM cvs").fetchone()[0] == "a.pdf"  # data kept
    assert db.get_meta("schema_version") == "2"


def test_overall_ai_progress_in_status(client) -> None:
    client.post("/api/index/refresh")
    assert client.app.state.tl.queue.wait_idle(60)
    s = client.get("/api/index/status").json()
    assert s["ai_total"] == 3 and s["ai_done"] == 3
    assert json.dumps(s)  # serialisable
