"""Local AI: rules + Ollama LLM extraction, fastembed embeddings and reranking."""

from __future__ import annotations

from typing import Any

import numpy as np

from ..config import Settings
from ..enrich import CVFields
from . import extract as _extract
from . import rules
from .embed import Embedder, FastEmbedder, MockEmbedder
from .llm import LLM, MockLLM, NoLLM, OllamaLLM
from .rerank import FastReranker, MockReranker, Reranker


class AIEnricher:
    def __init__(self, llm: LLM, embedder: Embedder) -> None:
        self.llm = llm
        self.embedder = embedder
        self.embed_model_name = embedder.model_name

    def extract(self, text: str, filename: str, llm_json: dict[str, Any] | None = None) -> CVFields:
        return _extract.merge(rules.extract(text, filename), llm_json)

    def embed_documents(self, texts: list[str]) -> np.ndarray | None:
        return self.embedder.embed_documents(texts)

    def llm_available(self) -> bool:
        return self.llm.available()

    def llm_extract(self, text: str, filename: str) -> dict[str, Any]:
        return _extract.llm_extract(self.llm, text, filename)


def build_llm(settings: Settings) -> LLM:
    if settings.llm == "mock":
        return MockLLM()
    if settings.llm == "off":
        return NoLLM()
    return OllamaLLM(settings.ollama_url, settings.ollama_model, settings.ollama_timeout_s)


def build_embedder(settings: Settings) -> Embedder:
    if settings.embeddings == "mock":
        return MockEmbedder()
    return FastEmbedder(settings.embed_model, settings.model_cache_dir)


def build_reranker(settings: Settings) -> Reranker:
    if settings.embeddings == "mock":
        return MockReranker()
    return FastReranker(settings.rerank_model, settings.model_cache_dir)


__all__ = ["AIEnricher", "build_embedder", "build_llm", "build_reranker"]
