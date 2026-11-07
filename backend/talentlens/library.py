"""A Library = one resume folder plus everything indexed from it (its own SQLite database).

Switching folders swaps the Library; AI models are shared and stay loaded.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .ai.embed import Embedder
from .config import CV_EXTENSIONS, Settings
from .db import Database
from .enrich import Enricher
from .indexer import Indexer
from .jobs import IndexQueue
from .provenance import Provenance
from .search import SearchEngine
from .storage import CVStore
from .watcher import FolderWatcher

log = logging.getLogger(__name__)


class FolderProblem(ValueError):
    """The chosen folder can't be used. The message is user-facing."""


def library_key(folder: Path) -> str:
    norm = os.path.normcase(str(folder.resolve()))
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:12]


def count_resumes(folder: Path, limit: int = 100_000) -> int:
    n = 0
    for _dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if not d.startswith((".", "~"))]
        for fn in filenames:
            if not fn.startswith(("~$", ".")) and Path(fn).suffix.lower() in CV_EXTENSIONS:
                n += 1
                if n >= limit:
                    return n
    return n


def validate_folder(path: Path, settings: Settings) -> Path:
    try:
        p = path.expanduser().resolve()
    except OSError as e:
        raise FolderProblem(f"That path can't be used: {e}") from e
    if not p.exists():
        raise FolderProblem("That folder doesn't exist. Check the path or create the folder first.")
    if not p.is_dir():
        raise FolderProblem(
            "That's a file, not a folder. Choose the folder that holds the resumes."
        )
    if not os.access(p, os.R_OK):
        raise FolderProblem("TalentLens can't read that folder (permission denied).")
    data = settings.data_dir.resolve()
    if p == data or data in p.parents:
        raise FolderProblem("Choose a resume folder, not TalentLens's own data folder.")
    return p


@dataclass
class Library:
    folder: Path
    db: Database
    store: CVStore
    indexer: Indexer
    queue: IndexQueue
    search: SearchEngine
    provenance: Provenance
    watcher: FolderWatcher | None = None

    @classmethod
    def open(
        cls,
        folder: Path,
        settings: Settings,
        enricher: Enricher,
        embedder: Embedder,
        *,
        ai_paused: bool = False,
    ) -> Library:
        lib_dir = settings.libraries_dir / library_key(folder)
        lib_dir.mkdir(parents=True, exist_ok=True)
        (lib_dir / "folder.txt").write_text(str(folder), encoding="utf-8")  # for humans
        db_path = lib_dir / "talentlens.db"
        _adopt_legacy_db(settings.legacy_db_path, db_path, folder)
        db = Database(db_path)
        store = CVStore(folder)
        indexer = Indexer(
            db, store, enricher, ocr_min_chars_per_page=settings.ocr_min_chars_per_page
        )
        search = SearchEngine(db, embedder)
        indexer.listeners.append(search.on_index_changed)
        queue = IndexQueue(indexer)
        queue.ai_paused = ai_paused
        return cls(
            folder=folder,
            db=db,
            store=store,
            indexer=indexer,
            queue=queue,
            search=search,
            provenance=Provenance(settings.provenance_csv_for(folder)),
        )

    def start(self, *, watch: bool, scan: bool) -> None:
        self.queue.start()
        if watch:
            self.watcher = FolderWatcher(self.folder, self.queue)
            self.watcher.start()
        if scan:
            self.queue.request(reason="startup")

    def stop(self) -> None:
        if self.watcher:
            self.watcher.stop()
            self.watcher = None
        self.queue.stop()


def _adopt_legacy_db(legacy: Path, target: Path, folder: Path) -> None:
    """v0.1 → v0.2: copy the single old database into this folder's library, if it belongs here.

    The old file is copied with SQLite's online backup (consistent even in WAL mode) and left
    in place, so nothing is lost if anything goes wrong.
    """
    if target.exists() or not legacy.exists():
        return
    try:
        src = sqlite3.connect(f"file:{legacy}?mode=ro", uri=True)
        try:
            rows = [r[0] for r in src.execute("SELECT rel_path FROM cvs LIMIT 25")]
        except sqlite3.DatabaseError:
            src.close()
            return
        if not rows or sum((folder / r).exists() for r in rows) < max(1, len(rows) // 2):
            src.close()
            return  # the old database was for a different folder
        dst = sqlite3.connect(target)
        with dst:
            src.backup(dst)
        dst.close()
        src.close()
        log.info("Copied the previous library (%s) into %s", legacy, target)
    except sqlite3.Error:
        log.exception("Could not copy the previous library; starting fresh")
        target.unlink(missing_ok=True)
