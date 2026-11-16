"""Curated local models offered in Settings (only ones that suit JD reading and candidate judging).

Picked for structured JSON + reasoning on a laptop GPU (about 6 GB VRAM), short prompts. Sources:
- Artificial Analysis (Qwen3.5 release, 2026-03): Qwen3.5 9B (Reasoning) is the most intelligent
  model under 10B parameters and Qwen3.5 4B (Reasoning) the most intelligent under 5B.
- BenchLM small-model ranking (2026-11): Gemma 4 12B 34.0, Granite 4.2 8B 25.8, Gemma 4 E4B 24.5.
- TalentLens benchmark (scripts/bench_llm.py, Opus gold, 10 JDs): qwen3.5:4b reads JDs best so far
  (skill F1 0.61 vs 0.47 for qwen2.5:3b, years 10/10, no invented max years).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class LocalModel:
    id: str  # exact Ollama tag
    label: str
    hint: str
    size_gb: float  # download size
    think: bool | None  # True/False: send Ollama's `think`; None: model has no thinking switch
    num_ctx: int = 8192
    recommended: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


MODELS: list[LocalModel] = [
    LocalModel(
        "qwen3.5:4b-q4_K_M",
        "Qwen 3.5 4B (thinking)",
        "Recommended. Strongest reasoning under 5B and the best JD reading in our tests; "
        "fits a 6 GB graphics card.",
        3.3,
        think=True,
        recommended=True,
    ),
    LocalModel(
        "qwen3.5:9b-q4_K_M",
        "Qwen 3.5 9B (thinking)",
        "Strongest reasoning under 10B. Slower: on a 6 GB card part of it runs on the CPU.",
        6.6,
        think=True,
    ),
    LocalModel(
        "granite4.2:8b-q4_K_M",
        "Granite 4.2 8B (thinking)",
        "IBM's enterprise model: very consistent structured answers. Partly on the CPU on 6 GB.",
        5.3,
        think=True,
    ),
    LocalModel(
        "gemma4:12b-it-q4_K_M",
        "Gemma 4 12B",
        "Top small-model score on BenchLM; no thinking step. Slowest here (about 8 GB).",
        8.0,
        think=None,
    ),
    LocalModel(
        "gemma4:e4b-it-q4_K_M",
        "Gemma 4 E4B (fast)",
        "Quick answers without a thinking step; good for large batches.",
        6.6,
        think=None,
    ),
    LocalModel(
        "qwen2.5:3b-instruct",
        "Qwen 2.5 3B (previous default)",
        "Fastest, but least accurate: tends to invent industries and experience limits.",
        1.9,
        think=None,
        num_ctx=2048,
    ),
]

BY_ID = {m.id: m for m in MODELS}


def get(model_id: str | None) -> LocalModel | None:
    return BY_ID.get(model_id or "")
