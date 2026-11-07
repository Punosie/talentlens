"""Cross-encoder reranking (fastembed) with a lexical-overlap mock for tests."""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Protocol

import numpy as np


class Reranker(Protocol):
    model_name: str

    def scores(self, query: str, docs: list[str]) -> np.ndarray:
        """Relevance in [0, 1] per doc."""
        ...


class FastReranker:
    def __init__(self, model_name: str, cache_dir: Path) -> None:
        self.model_name = model_name
        self.cache_dir = cache_dir
        self._model = None
        self._lock = threading.Lock()

    def _get(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from fastembed.rerank.cross_encoder import TextCrossEncoder

                    self._model = TextCrossEncoder(self.model_name, cache_dir=str(self.cache_dir))
        return self._model

    def scores(self, query: str, docs: list[str]) -> np.ndarray:
        if not docs:
            return np.zeros(0, dtype=np.float32)
        model = self._get()
        with self._lock:
            logits = np.array(list(model.rerank(query, docs, batch_size=8)), dtype=np.float32)
        return 1.0 / (1.0 + np.exp(-logits))  # sigmoid -> [0, 1]


class MockReranker:
    model_name = "mock-overlap"

    def scores(self, query: str, docs: list[str]) -> np.ndarray:
        q = set(re.findall(r"[a-z0-9+#]+", query.lower()))
        out = []
        for d in docs:
            t = set(re.findall(r"[a-z0-9+#]+", d.lower()))
            out.append(len(q & t) / (len(q) or 1))
        return np.array(out, dtype=np.float32)
