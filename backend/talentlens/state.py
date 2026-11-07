"""Application container: one instance per running app, attached to app.state.tl."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .ai import AIEnricher, build_embedder, build_llm, build_reranker
from .ai.embed import Embedder
from .ai.llm import LLM
from .ai.rerank import Reranker
from .config import Settings
from .db import Database
from .enrich import Enricher
from .indexer import Indexer
from .jobs import IndexQueue
from .provenance import Provenance
from .search import SearchEngine
from .storage import CVStore
from .watcher import FolderWatcher

log = logging.getLogger(__name__)


@dataclass
class AppState:
    settings: Settings
    db: Database
    store: CVStore
    llm: LLM
    embedder: Embedder
    reranker: Reranker
    enricher: Enricher
    indexer: Indexer
    queue: IndexQueue
    search: SearchEngine
    provenance: Provenance
    watcher: FolderWatcher | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def build(cls, settings: Settings, enricher: Enricher | None = None) -> AppState:
        settings.ensure_dirs()
        db = Database(settings.db_path)
        store = CVStore(settings.cv_dir)
        llm = build_llm(settings)
        embedder = build_embedder(settings)
        enricher = enricher or AIEnricher(llm, embedder)
        indexer = Indexer(
            db, store, enricher, ocr_min_chars_per_page=settings.ocr_min_chars_per_page
        )
        search = SearchEngine(db, embedder)
        indexer.listeners.append(search.on_index_changed)
        return cls(
            settings=settings,
            db=db,
            store=store,
            llm=llm,
            embedder=embedder,
            reranker=build_reranker(settings),
            enricher=enricher,
            indexer=indexer,
            queue=IndexQueue(indexer),
            search=search,
            provenance=Provenance(settings.resolved_cv_index_csv()),
        )

    def start(self) -> None:
        self.queue.start()
        if self.settings.watch:
            self.watcher = FolderWatcher(self.settings.cv_dir, self.queue)
            self.watcher.start()
        if self.settings.scan_on_startup:
            self.queue.request(reason="startup")

    def stop(self) -> None:
        if self.watcher:
            self.watcher.stop()
        self.queue.stop()
