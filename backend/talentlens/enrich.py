"""The enrichment interface: turns resume text into structured fields and an embedding.

Extraction runs in two stages:
1. `extract(text, filename, llm_json=None)`: fast, rule-based, run for every file.
2. An optional LLM pass produces `llm_json`, which is stored and merged in by calling
   `extract` again with it. The merge is deterministic, so a re-index never needs the LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np


@dataclass
class CVFields:
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    city: str | None = None
    country: str | None = None
    years_exp: float | None = None
    title: str | None = None
    skills: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    education: list[str] = field(default_factory=list)
    summary: str | None = None
    extractor: str = "none"


class Enricher(Protocol):
    embed_model_name: str

    def extract(
        self, text: str, filename: str, llm_json: dict[str, Any] | None = None
    ) -> CVFields: ...

    def embed_documents(self, texts: list[str]) -> np.ndarray | None: ...

    def llm_available(self) -> bool: ...

    def llm_extract(self, text: str, filename: str) -> dict[str, Any]: ...


class NullEnricher:
    embed_model_name = "none"

    def extract(self, text: str, filename: str, llm_json: dict[str, Any] | None = None) -> CVFields:
        return CVFields(extractor="none")

    def embed_documents(self, texts: list[str]) -> np.ndarray | None:
        return None

    def llm_available(self) -> bool:
        return False

    def llm_extract(self, text: str, filename: str) -> dict[str, Any]:
        raise RuntimeError("No LLM configured")
