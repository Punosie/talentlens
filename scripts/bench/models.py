"""Model roster for the local-LLM benchmark (exact Ollama tags, checked against ollama.com).

    uv run python -m scripts.bench.models            # sizes from the registry, installed status

Only models that load on an RTX 3050 6 GB + 16 GB RAM laptop (partial CPU offload allowed).
MoE models of 18 GB+ (qwen3.5:35b-a3b, nemotron-3-nano:30b, gemma4:26b) cannot load and are skipped.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass

import httpx

OLLAMA = "http://127.0.0.1:11434"


@dataclass(frozen=True)
class Model:
    tag: str
    family: str
    params_b: float
    think: bool | None = None  # None: no thinking switch; False/True: send think=...
    note: str = ""


ROSTER: list[Model] = [
    Model("qwen2.5:3b-instruct", "qwen2.5", 3.1, note="current app default (Q4_K_M)"),
    Model("qwen2.5:7b-instruct-q4_K_M", "qwen2.5", 7.6),
    Model("qwen2.5:14b-instruct-q4_K_M", "qwen2.5", 14.8),
    Model("qwen3:4b-instruct-2507-q4_K_M", "qwen3", 4.0),
    Model("qwen3:8b-q4_K_M", "qwen3", 8.2, think=False),
    Model("qwen3:14b-q4_K_M", "qwen3", 14.8, think=False),
    Model("qwen3.5:4b-q4_K_M", "qwen3.5", 4.0, think=False),
    Model("qwen3.5:9b-q4_K_M", "qwen3.5", 9.0, think=False),
    Model("llama3.2:3b-instruct-q4_K_M", "llama3.2", 3.2),
    Model("llama3.1:8b-instruct-q4_K_M", "llama3.1", 8.0),
    Model("gemma3:4b-it-q4_K_M", "gemma3", 4.3),
    Model("gemma3:12b-it-q4_K_M", "gemma3", 12.2),
    Model("gemma4:e4b-it-q4_K_M", "gemma4", 8.0, note="effective 4B"),
    Model("gemma4:12b-it-q4_K_M", "gemma4", 12.0),
    Model("phi4-mini:3.8b-q4_K_M", "phi4", 3.8),
    Model("phi4:14b-q4_K_M", "phi4", 14.7),
    Model("mistral-nemo:12b-instruct-2407-q4_K_M", "mistral", 12.2),
    Model("ministral-3:8b-instruct-2512-q4_K_M", "mistral", 8.0),
    Model("ministral-3:14b-instruct-2512-q4_K_M", "mistral", 14.0),
    Model("granite3.3:8b", "granite", 8.2),
    Model("granite4.2:8b-q4_K_M", "granite", 8.0, think=False),
    Model("deepseek-r1:8b", "deepseek-r1", 8.2, think=True, note="reasoning distill"),
    Model("nemotron-3-nano:4b-q4_K_M", "nemotron", 4.0, think=False),
    Model("gpt-oss:20b", "gpt-oss", 21.0, think=True, note="MoE 3.6B active, MXFP4"),
]
# The user cut the sweep to 5 small + 5 large models (newest generations, strongest on JSON and
# judging); qwen2.5:3b-instruct stays as the app baseline. `--models shortlist` runs these.
SHORTLIST_SMALL = [
    "qwen3.5:4b-q4_K_M",
    "qwen3:4b-instruct-2507-q4_K_M",
    "gemma4:e4b-it-q4_K_M",
    "phi4-mini:3.8b-q4_K_M",
    "nemotron-3-nano:4b-q4_K_M",
]
SHORTLIST_LARGE = [
    "qwen3.5:9b-q4_K_M",
    "granite4.2:8b-q4_K_M",
    "gemma4:12b-it-q4_K_M",
    "qwen3:14b-q4_K_M",
    "phi4:14b-q4_K_M",
]
SHORTLIST = SHORTLIST_SMALL + SHORTLIST_LARGE
# thinking variants measured separately for the best hybrid models
THINKING_VARIANTS = ["qwen3:8b-q4_K_M", "qwen3.5:9b-q4_K_M", "granite4.2:8b-q4_K_M"]


def by_tag(tag: str) -> Model:
    for m in ROSTER:
        if m.tag == tag:
            return m
    return Model(tag, tag.split(":")[0], 0.0)


def registry_size(tag: str) -> dict:
    """Download size and quantisation from the registry manifest + config (no pull)."""
    name, _, ver = tag.partition(":")
    ns = name if "/" in name else f"library/{name}"
    url = f"https://registry.ollama.ai/v2/{ns}/manifests/{ver or 'latest'}"
    h = {"Accept": "application/vnd.docker.distribution.manifest.v2+json"}
    r = httpx.get(url, headers=h, timeout=30, follow_redirects=True)
    if r.status_code != 200:
        return {"exists": False, "status": r.status_code}
    man = r.json()
    size = sum(layer.get("size", 0) for layer in man.get("layers", []))
    info = {"exists": True, "bytes": size}
    cfg = man.get("config", {}).get("digest")
    if cfg:
        c = httpx.get(
            f"https://registry.ollama.ai/v2/{ns}/blobs/{cfg}", timeout=30, follow_redirects=True
        )
        if c.status_code == 200:
            try:
                j = c.json()
                info["file_type"] = j.get("file_type")
                info["model_family"] = j.get("model_family")
            except ValueError:
                pass
    return info


def installed() -> set[str]:
    tags = httpx.get(f"{OLLAMA}/api/tags", timeout=10).json().get("models", [])
    return {t["name"] for t in tags}


def pull(tag: str) -> bool:
    return subprocess.run(["ollama", "pull", tag]).returncode == 0


def remove(tag: str) -> None:
    subprocess.run(["ollama", "rm", tag], capture_output=True)


if __name__ == "__main__":
    have = installed()
    rows = []
    for m in ROSTER:
        info = registry_size(m.tag)
        rows.append({"tag": m.tag, **info, "installed": m.tag in have})
        gb = info.get("bytes", 0) / 1e9
        print(
            f"{m.tag:42s} exists={info['exists']!s:5} {gb:5.1f} GB {info.get('file_type')}",
            flush=True,
        )
    if "--json" in sys.argv:
        print(json.dumps(rows, indent=1))
