"""CPU or GPU: which device runs the search models, and which model fits each.

- GPU (NVIDIA, Windows): bge-small on the full resume text. Fast enough that size doesn't matter.
- CPU: snowflake-arctic-embed-xs on a focused ~1200-character text. About 4x faster than
  bge-small on full text, with nearly the same retrieval quality (MTEB retrieval 50.2 vs 51.7).

The choice comes from, in order: TALENTLENS_DEVICE (env/.env), the benchmark saved at install
time (`talentlens benchmark`, stored in settings.json), else "use the GPU if one works".
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

Device = Literal["cpu", "cuda"]


@dataclass(frozen=True)
class Profile:
    device: Device
    model: str
    text_chars: int  # how much of a resume/profile is embedded


PROFILES: dict[Device, Profile] = {
    "cuda": Profile("cuda", "BAAI/bge-small-en-v1.5", 6000),
    "cpu": Profile("cpu", "snowflake/snowflake-arctic-embed-xs", 1200),
}

SAMPLE = (
    "Senior Backend Engineer at Example Payments. Built high-throughput APIs in Java and Spring "
    "Boot with Kafka, PostgreSQL, Docker and Kubernetes on AWS. Led a team of five engineers. "
)


def resolve(saved: str | None) -> Device:
    """Device for this run: env override > saved benchmark choice > GPU if usable."""
    from .embed import gpu_available

    env = os.environ.get("TALENTLENS_DEVICE", "auto").strip().lower()
    want = env if env in ("cpu", "cuda") else (saved if saved in ("cpu", "cuda") else "auto")
    if want == "cpu":
        return "cpu"
    return "cuda" if gpu_available() else "cpu"


def benchmark(cache_dir: Path, docs: int = 192) -> dict[str, Any]:
    """Time real embedding on each available device (same work each would do in the app) and
    pick the faster. Returns {"choice", "cpu_per_s", "cuda_per_s"|None, "gpu_name"|None}."""
    from fastembed import TextEmbedding

    from .embed import _load, gpu_available

    results: dict[str, Any] = {"cpu_per_s": None, "cuda_per_s": None, "gpu_name": None}
    candidates: list[Device] = ["cpu"] + (["cuda"] if gpu_available() else [])
    for dev in candidates:
        prof = PROFILES[dev]
        text = (SAMPLE * 80)[: prof.text_chars]
        extra: dict[str, Any] = (
            {"cuda": True}
            if dev == "cuda"
            else {"cuda": False, "providers": ["CPUExecutionProvider"]}
        )
        try:
            model = _load(TextEmbedding, prof.model, cache_dir, extra)
            list(model.embed([text] * 16, batch_size=16))  # warm up
            t = time.perf_counter()
            list(model.embed([text] * docs, batch_size=64 if dev == "cuda" else 16))
            results[f"{dev}_per_s"] = round(docs / (time.perf_counter() - t), 1)
        except Exception as e:  # a broken GPU setup just loses the benchmark
            results[f"{dev}_error"] = str(e)[:200]
    if results["cuda_per_s"]:
        results["gpu_name"] = _gpu_name()
    cpu, gpu = results["cpu_per_s"] or 0, results["cuda_per_s"] or 0
    results["choice"] = "cuda" if gpu > cpu * 1.2 else "cpu"
    results["at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return results


def _gpu_name() -> str | None:
    try:
        import subprocess

        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return out.stdout.strip().splitlines()[0] or None
    except Exception:
        return None
