import os
import time
from pathlib import Path

from talentlens.config import Settings
from talentlens.state import AppState

from .conftest import ALICE, make_pdf, snapshot


def _state(settings: Settings) -> AppState:
    return AppState.build(settings)


def test_full_scan_indexes_everything_and_never_touches_sources(settings: Settings) -> None:
    before = snapshot(settings.cv_dir)
    st = _state(settings)
    r = st.indexer.run()
    assert (r.scanned, r.added, r.failed) == (3, 3, 0)
    r2 = st.indexer.run(full=True)
    assert r2.updated == 3
    assert snapshot(settings.cv_dir) == before  # bytes and mtimes unchanged
    assert sorted(p.name for p in settings.cv_dir.iterdir()) == sorted(before)  # no stray files


def test_incremental_skips_unchanged_and_detects_new(settings: Settings) -> None:
    st = _state(settings)
    st.indexer.run()
    assert st.indexer.run().unchanged == 3

    make_pdf(settings.cv_dir / "Dave_New.pdf", ALICE.replace("Alice", "Dave"))
    r = st.indexer.run()
    assert (r.added, r.unchanged) == (1, 3)


def test_touch_without_content_change_is_cheap(settings: Settings) -> None:
    st = _state(settings)
    st.indexer.run()
    p = settings.cv_dir / "Carol_Placeholder.pdf"
    os.utime(p, (time.time() + 10, time.time() + 10))
    r = st.indexer.run()
    assert r.unchanged == 3 and r.updated == 0


def test_removed_file_is_dropped_from_db(settings: Settings, tmp_path: Path) -> None:
    st = _state(settings)
    st.indexer.run()
    (settings.cv_dir / "Carol_Placeholder.pdf").unlink()  # the user deletes it outside the app
    r = st.indexer.run()
    assert r.removed == 1
    with st.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM cvs").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM cv_fts").fetchone()[0] == 2


def test_unreadable_file_is_flagged_not_fatal(settings: Settings) -> None:
    (settings.cv_dir / "broken.pdf").write_bytes(b"%PDF-1.4 broken")
    st = _state(settings)
    r = st.indexer.run()
    assert r.added == 3 and r.unreadable == 1
    with st.db.connect() as conn:
        row = conn.execute("SELECT status FROM cvs WHERE filename='broken.pdf'").fetchone()
    assert row["status"] == "unreadable"


def test_fts_finds_body_text(settings: Settings) -> None:
    st = _state(settings)
    st.indexer.run()
    with st.db.connect() as conn:
        hits = conn.execute(
            "SELECT c.filename FROM cv_fts JOIN cvs c ON c.id = cv_fts.rowid "
            "WHERE cv_fts MATCH 'airflow'"
        ).fetchall()
    assert [h["filename"] for h in hits] == ["Alice_Example_Resume.pdf"]


def test_queue_coalesces_and_reports(settings: Settings) -> None:
    st = _state(settings)
    st.queue.start()
    try:
        for _ in range(5):
            st.queue.request()
        assert st.queue.wait_idle(60)
        s = st.queue.status()
        assert s.state == "idle"
        assert s.last_report and s.last_report["added"] == 3
    finally:
        st.queue.stop()
