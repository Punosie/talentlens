"""Application container: shared AI models plus the current Library (resume folder)."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .ai import AIEnricher, build_embedder, build_llm, build_reranker
from .ai.device import resolve as resolve_device
from .ai.embed import Embedder
from .ai.llm import LLM, NoLLM
from .ai.rerank import Reranker
from .config import Settings, discover_cv_dirs
from .db import Database
from .enrich import Enricher
from .jobs import IndexQueue
from .library import FolderProblem, Library, validate_folder
from .provenance import Provenance
from .search import SearchEngine
from .settings_store import SettingsStore
from .storage import CVStore

log = logging.getLogger(__name__)


class NoLibrary(RuntimeError):
    """No resume folder chosen yet (first run)."""


@dataclass
class AppState:
    settings: Settings
    prefs: SettingsStore
    llm: LLM
    embedder: Embedder
    reranker: Reranker
    enricher: Enricher
    library: Library | None = None
    cv_dir_source: str = "none"  # config | app | auto | none
    extras: dict[str, Any] = field(default_factory=dict)
    _switch_lock: threading.Lock = field(default_factory=threading.Lock)
    _started: bool = False

    # ------------------------------------------------------------------
    @classmethod
    def build(cls, settings: Settings, enricher: Enricher | None = None) -> AppState:
        settings.ensure_dirs()
        prefs = SettingsStore(settings.settings_path)
        llm = cls._make_llm(settings, prefs)
        device = "cpu" if settings.embeddings == "mock" else resolve_device(prefs.get("device"))
        embedder = build_embedder(settings, device)
        enricher = enricher or AIEnricher(llm, embedder)
        state = cls(
            settings=settings,
            prefs=prefs,
            llm=llm,
            embedder=embedder,
            reranker=build_reranker(settings, device),
            enricher=enricher,
        )
        state.extras["device"] = device
        folder, source = state._resolve_folder()
        if folder is not None:
            state.library = state._open(folder)
            state.cv_dir_source = source
        return state

    @staticmethod
    def _make_llm(settings: Settings, prefs: SettingsStore) -> LLM:
        if not settings.llm_locked and not prefs.get("ai_enabled"):
            return NoLLM()
        model = prefs.get("ollama_model")
        if model and not settings.llm_locked and settings.llm == "ollama":
            settings = settings.model_copy(update={"ollama_model": model})
        return build_llm(settings)

    def _resolve_folder(self) -> tuple[Path | None, str]:
        s = self.settings
        if s.cv_dir_locked:
            return s.cv_dir, "config"
        chosen = self.prefs.get("cv_dir")
        if chosen:
            return Path(chosen), "app"
        for cand in discover_cv_dirs() if s.discover else []:
            log.info("Using discovered resume folder %s", cand)
            self.prefs.update(cv_dir=str(cand))
            return cand, "auto"
        return None, "none"

    def _open(self, folder: Path) -> Library:
        return Library.open(
            folder,
            self.settings,
            self.enricher,
            self.embedder,
            ai_paused=bool(self.prefs.get("ai_paused")),
            mongodb_uri=self.mongodb_uri(),
        )

    # --- lifecycle --------------------------------------------------------
    def start(self) -> None:
        self._started = True
        if self.library:
            self.library.start(watch=self.settings.watch, scan=self.settings.scan_on_startup)

    def stop(self) -> None:
        self._started = False
        if self.library:
            self.library.stop()

    def mongodb_uri(self) -> str | None:
        return self.settings.mongodb_uri or self.prefs.get("mongodb_uri") or None

    def set_mongodb_uri(self, uri: str | None) -> None:
        """Save (or clear) the connections database and reopen the current library with it."""
        if self.settings.mongodb_locked:
            raise FolderProblem(
                "The connections database is set in the configuration file (.env) "
                "and can't be changed here."
            )
        uri = (uri or "").strip() or None
        if uri and not uri.startswith(("mongodb://", "mongodb+srv://")):
            raise FolderProblem("That doesn't look like a MongoDB connection string.")
        self.prefs.update(mongodb_uri=uri)
        with self._switch_lock:
            old = self.library
            if not old:
                return
            new = self._open(old.folder)
            old.stop()
            self.library = new
            if self._started:
                new.start(watch=self.settings.watch, scan=True)
            self.extras.pop("shortlister", None)

    def switch_folder(self, path: Path) -> Library:
        """Point the app at another resume folder (validated). Its library opens immediately."""
        if self.settings.cv_dir_locked:
            raise FolderProblem(
                "The resume folder is set in the configuration file (.env) "
                "and can't be changed here."
            )
        folder = validate_folder(path, self.settings)
        with self._switch_lock:
            old = self.library
            if old and old.folder.resolve() == folder:
                return old
            new = self._open(folder)
            if old:
                old.stop()
            self.library = new
            self.cv_dir_source = "app"
            self.prefs.update(cv_dir=str(folder))
            if self._started:
                new.start(watch=self.settings.watch, scan=True)
            self.extras.pop("shortlister", None)
            return new

    def set_ai(self, *, enabled: bool | None = None, model: str | None = None) -> None:
        changes: dict[str, Any] = {}
        if enabled is not None:
            changes["ai_enabled"] = enabled
        if model is not None:
            changes["ollama_model"] = model
        if changes:
            self.prefs.update(**changes)
        if not self.settings.llm_locked:
            self.llm = self._make_llm(self.settings, self.prefs)
            if isinstance(self.enricher, AIEnricher):
                self.enricher.llm = self.llm

    # --- current-library shortcuts (keep API code simple) -------------------
    def lib(self) -> Library:
        if self.library is None:
            raise NoLibrary("Choose your resume folder first")
        return self.library

    @property
    def db(self) -> Database:
        return self.lib().db

    @property
    def store(self) -> CVStore:
        return self.lib().store

    @property
    def queue(self) -> IndexQueue:
        return self.lib().queue

    @property
    def search(self) -> SearchEngine:
        return self.lib().search

    @property
    def provenance(self) -> Provenance:
        return self.lib().provenance

    @property
    def indexer(self):
        return self.lib().indexer
