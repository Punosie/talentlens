"""Download and load the local models once, so the first search or index is fast.

uv run python -m talentlens.warmup
"""

from __future__ import annotations

import sys
import time

from .ai import build_embedder, build_llm, build_reranker
from .config import get_settings


def main() -> int:
    s = get_settings()
    s.ensure_dirs()
    print(f"Model cache: {s.model_cache_dir}")
    t = time.perf_counter()
    build_embedder(s).embed_documents(["warm up"])
    print(f"  embeddings ready: {s.embed_model} ({time.perf_counter() - t:.0f}s)")
    t = time.perf_counter()
    build_reranker(s).scores("warm up", ["warm up"])
    print(f"  reranker ready:   {s.rerank_model} ({time.perf_counter() - t:.0f}s)")
    from .parsing.ocr import _get_engine

    _get_engine()
    print("  OCR ready:        RapidOCR")
    st = build_llm(s).status()
    if st.get("available"):
        print(f"  local LLM ready:  {st.get('model')}")
    else:
        print(f"  local LLM NOT ready: {st.get('error')} (the app still works with rules)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
