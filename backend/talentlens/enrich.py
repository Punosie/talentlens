"""The enrichment interface: turns resume text into structured fields and an embedding.

Phase 1 ships NullEnricher. The AI implementation lives in talentlens.ai.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

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

    def extract(self, text: str, filename: str) -> CVFields: ...

    def embed_documents(self, texts: list[str]) -> np.ndarray | None: ...


class NullEnricher:
    embed_model_name = "none"

    def extract(self, text: str, filename: str) -> CVFields:
        return CVFields(extractor="none")

    def embed_documents(self, texts: list[str]) -> np.ndarray | None:
        return None
