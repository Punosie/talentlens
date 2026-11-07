"""Local text embeddings (fastembed / ONNX on CPU) and a deterministic mock for tests."""

from __future__ import annotations

import hashlib
import re
import threading
from pathlib import Path
from typing import Protocol

import numpy as np

# bge-*-v1.5 retrieval works best with this instruction on the QUERY side only
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class Embedder(Protocol):
    model_name: str
    dim: int

    def embed_documents(self, texts: list[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...


def _l2(x: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(x, axis=-1, keepdims=True)
    n[n == 0] = 1.0
    return (x / n).astype(np.float32)


class FastEmbedder:
    def __init__(self, model_name: str, cache_dir: Path) -> None:
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.dim = 384 if "small" in model_name else 768
        self._model = None
        self._lock = threading.Lock()

    def _get(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from fastembed import TextEmbedding

                    self._model = TextEmbedding(self.model_name, cache_dir=str(self.cache_dir))
        return self._model

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        model = self._get()
        with self._lock:
            vecs = list(model.embed(texts, batch_size=16))
        return _l2(np.vstack(vecs))

    def embed_query(self, text: str) -> np.ndarray:
        prefix = BGE_QUERY_PREFIX if "bge" in self.model_name.lower() else ""
        return self.embed_documents([prefix + text])[0]


class MockEmbedder:
    """Hashing bag-of-words: fast and deterministic, with real (if crude) semantic overlap."""

    model_name = "mock-hash-256"
    dim = 256

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for tok in re.findall(r"[a-z0-9+#]+", text.lower()):
            h = int.from_bytes(hashlib.md5(tok.encode()).digest()[:4], "little")
            v[h % self.dim] += 1.0
        return v

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return _l2(np.vstack([self._vec(t) for t in texts]))

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_documents([text])[0]
