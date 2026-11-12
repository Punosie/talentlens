"""Local text embeddings (fastembed / ONNX on CPU) and a deterministic mock for tests."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any, Protocol

import numpy as np

# Windows without Developer Mode cannot symlink; the HF cache copes, so silence the warning.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
log = logging.getLogger(__name__)


_GPU: bool | None = None


def gpu_available() -> bool:
    """True when an NVIDIA GPU can run the models (CUDA build of ONNX Runtime installed and its
    libraries load). TALENTLENS_DEVICE=cpu turns it off. Checked once per process."""
    global _GPU
    if _GPU is None:
        _GPU = False
        if os.environ.get("TALENTLENS_DEVICE", "auto").strip().lower() != "cpu":
            try:
                import onnxruntime as ort

                if "CUDAExecutionProvider" in ort.get_available_providers():
                    if hasattr(ort, "preload_dlls"):
                        ort.preload_dlls()  # CUDA/cuDNN from the nvidia-* wheels
                    _GPU = True
            except Exception:
                log.info("GPU not usable; running models on the CPU", exc_info=True)
    return _GPU


def _load(cls: Any, model_name: str, cache_dir: Path, extra: dict[str, Any]) -> Any:
    """Load from the local cache without touching the network (works offline). Only if it is
    not cached yet, download it."""
    try:
        return cls(model_name, cache_dir=str(cache_dir), local_files_only=True, **extra)
    except Exception:
        log.info("Model %s not cached yet (or failed to load); trying a download", model_name)
        return cls(model_name, cache_dir=str(cache_dir), **extra)


def load_cached_first(cls: Any, model_name: str, cache_dir: Path) -> Any:
    """Load a fastembed model, on the GPU when one is available, otherwise (or if the GPU
    load fails for any reason) on the CPU. Never fails just because of the GPU."""
    if gpu_available():
        try:
            model = _load(cls, model_name, cache_dir, {"cuda": True})
            log.info("Model %s running on the GPU", model_name)
            return model
        except Exception:
            log.warning("Could not load %s on the GPU; using the CPU", model_name, exc_info=True)
    return _load(cls, model_name, cache_dir, {})


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

                    self._model = load_cached_first(TextEmbedding, self.model_name, self.cache_dir)
        return self._model

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        model = self._get()
        with self._lock:
            vecs = list(model.embed(texts, batch_size=64 if gpu_available() else 16))
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
