"""Curated local models offered in Settings (only ones that suit JD reading and candidate judging).

Picked for structured JSON + reasoning on a laptop GPU (about 6 GB VRAM), short prompts. Sources:
- Artificial Analysis (Qwen3.5 release, 2026-03): Qwen3.5 9B (Reasoning) is the most intelligent
  model under 10B parameters and Qwen3.5 4B (Reasoning) the most intelligent under 5B.
- BenchLM small-model ranking (2026-11): Gemma 4 12B 34.0, Granite 4.2 8B 25.8, Gemma 4 E4B 24.5.
- TalentLens benchmark (scripts/bench_llm.py, Opus gold, 10 JDs): qwen3.5:4b reads JDs best so far
  (skill F1 0.61 vs 0.47 for qwen2.5:3b, years 10/10, no invented max years).

Not every computer has 6 GB: on a 2 GB GeForce MX250 laptop qwen2.5:3b ran 74% on the CPU at about
2 tokens/s, while qwen2.5:1.5b fit the card at about 14 tokens/s. So each model states the memory it
needs to run fully on the graphics card (`min_vram_gb`), and `recommend()` picks per computer.
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
    recommended: bool = False  # best choice on the reference 6 GB laptop
    min_vram_gb: float = 0.0  # graphics memory to run fully on the GPU (weights + context)

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
        min_vram_gb=4.5,
    ),
    LocalModel(
        "qwen3.5:9b-q4_K_M",
        "Qwen 3.5 9B (thinking)",
        "Strongest reasoning under 10B. Slower: on a 6 GB card part of it runs on the CPU.",
        6.6,
        think=True,
        min_vram_gb=8.0,
    ),
    LocalModel(
        "granite4.2:8b-q4_K_M",
        "Granite 4.2 8B (thinking)",
        "IBM's enterprise model: very consistent structured answers. Partly on the CPU on 6 GB.",
        5.3,
        think=True,
        min_vram_gb=6.5,
    ),
    LocalModel(
        "gemma4:12b-it-q4_K_M",
        "Gemma 4 12B",
        "Top small-model score on BenchLM; no thinking step. Slowest here (about 8 GB).",
        8.0,
        think=None,
        min_vram_gb=10.0,
    ),
    LocalModel(
        "gemma4:e4b-it-q4_K_M",
        "Gemma 4 E4B (fast)",
        "Quick answers without a thinking step; good for large batches.",
        6.6,
        think=None,
        min_vram_gb=8.0,
    ),
    LocalModel(
        "qwen2.5:3b-instruct",
        "Qwen 2.5 3B (previous default)",
        "Quick and small; less accurate than the 4B: may invent industries and experience limits.",
        1.9,
        think=None,
        num_ctx=2048,
        min_vram_gb=2.6,
    ),
    LocalModel(
        "qwen2.5:1.5b-instruct",
        "Qwen 2.5 1.5B (low memory)",
        "For laptops with a small graphics card (2 GB) or none: several times faster there than "
        "the larger models, with simpler answers.",
        1.0,
        think=None,
        num_ctx=2048,
        min_vram_gb=1.5,
    ),
]

# What each kind of computer gets, best first: (memory budget in GB, model)
_TIERS: list[tuple[float, str]] = [
    (4.5, "qwen3.5:4b-q4_K_M"),
    (2.6, "qwen2.5:3b-instruct"),
    (0.0, "qwen2.5:1.5b-instruct"),
]

BY_ID = {m.id: m for m in MODELS}


def get(model_id: str | None) -> LocalModel | None:
    return BY_ID.get(model_id or "")


def recommend(budget_gb: float | None) -> str:
    """The model for a computer whose AI memory budget is `budget_gb` (graphics memory, or the
    usable share of unified memory on Apple silicon; 0 or None = CPU only)."""
    budget = budget_gb or 0.0
    for need, model_id in _TIERS:
        if budget >= need:
            return model_id
    return _TIERS[-1][1]


def fits(model: LocalModel, budget_gb: float | None) -> bool | None:
    """Does the model run fully on this computer's graphics memory? None when unknown or when
    there is no graphics memory to fit (CPU only: every model runs on the processor)."""
    if not budget_gb:
        return None
    return model.min_vram_gb <= budget_gb


def catalog(budget_gb: float | None) -> list[dict[str, Any]]:
    """The model list for Settings, marked for this computer: `recommended` is the pick for this
    hardware (not the reference laptop) and `fits` says whether it runs fully on the GPU."""
    pick = recommend(budget_gb)
    return [
        {**m.as_dict(), "recommended": m.id == pick, "fits": fits(m, budget_gb)} for m in MODELS
    ]
