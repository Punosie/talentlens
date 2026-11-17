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
    """True when an NVIDIA GPU can run the models: the CUDA build of ONNX Runtime is installed,
    its libraries load, and the card is new enough for it (see device.MIN_COMPUTE_CAPABILITY).
    TALENTLENS_DEVICE=cpu turns it off. Checked once per process; a failed GPU load later turns
    it off too (mark_gpu_unusable)."""
    global _GPU
    if _GPU is None:
        _GPU = False
        if os.environ.get("TALENTLENS_DEVICE", "auto").strip().lower() != "cpu":
            try:
                import onnxruntime as ort

                if "CUDAExecutionProvider" in ort.get_available_providers():
                    from .device import cuda_supported, gpu_info

                    info = gpu_info()
                    if cuda_supported(info) is False:
                        log.info(
                            "GPU %s (compute capability %s) is too old for this ONNX Runtime "
                            "build; running models on the CPU",
                            info and info.get("name"),
                            info and info.get("compute_capability"),
                        )
                        return False
                    if hasattr(ort, "preload_dlls"):
                        ort.preload_dlls()  # CUDA/cuDNN from the nvidia-* wheels
                    _GPU = True
            except Exception:
                log.info("GPU not usable; running models on the CPU", exc_info=True)
    return _GPU


def mark_gpu_unusable() -> None:
    """A model failed to load on the GPU: use the CPU for the rest of this process, and say so."""
    global _GPU
    _GPU = False


def _load(cls: Any, model_name: str, cache_dir: Path, extra: dict[str, Any]) -> Any:
    """Load from the local cache without touching the network (works offline). Only if it is
    not cached yet, download it."""
    try:
        return cls(model_name, cache_dir=str(cache_dir), local_files_only=True, **extra)
    except Exception:
        log.info("Model %s not cached yet (or failed to load); trying a download", model_name)
        return cls(model_name, cache_dir=str(cache_dir), **extra)


def load_cached_first(cls: Any, model_name: str, cache_dir: Path, device: str | None = None) -> Any:
    """Load a fastembed model, on the GPU when one is available, otherwise (or if the GPU
    load fails for any reason) on the CPU. Never fails just because of the GPU."""
    if device != "cpu" and gpu_available():
        try:
            model = _load(cls, model_name, cache_dir, {"cuda": True})
            log.info("Model %s running on the GPU", model_name)
            return model
        except Exception:
            log.warning("Could not load %s on the GPU; using the CPU", model_name, exc_info=True)
            mark_gpu_unusable()
    # explicit CPU: fastembed's default (cuda=AUTO) would pick CUDA whenever the CUDA build of
    # ONNX Runtime is installed, even when its libraries were not loaded or the user chose CPU
    return _load(cls, model_name, cache_dir, {"cuda": False, "providers": ["CPUExecutionProvider"]})


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
    def __init__(
        self, model_name: str, cache_dir: Path, *, device: str = "auto", text_chars: int = 6000
    ) -> None:
        self.hf_model = model_name
        self.text_chars = text_chars
        # stored with every vector: a different model OR text size means "re-embed"
        self.model_name = model_name if text_chars >= 6000 else f"{model_name}@{text_chars}"
        self.cache_dir = cache_dir
        self.device = device
        self.dim = 768 if any(k in model_name.lower() for k in ("base", "large")) else 384
        self._model = None
        self._lock = threading.Lock()

    def _get(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from fastembed import TextEmbedding

                    self._model = load_cached_first(
                        TextEmbedding, self.hf_model, self.cache_dir, self.device
                    )
        return self._model

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        model = self._get()
        with self._lock:
            on_gpu = self.device != "cpu" and gpu_available()
            vecs = list(model.embed(texts, batch_size=64 if on_gpu else 16))
        return _l2(np.vstack(vecs))

    def embed_query(self, text: str) -> np.ndarray:
        name = self.hf_model.lower()
        prefix = BGE_QUERY_PREFIX if ("bge" in name or "arctic-embed" in name) else ""
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
