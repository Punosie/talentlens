"""CPU or GPU: which device runs the search models, and which model fits each.

- GPU (NVIDIA, Windows): bge-small on the full resume text. Fast enough that size doesn't matter.
- CPU: snowflake-arctic-embed-xs on a focused ~1200-character text. About 4x faster than
  bge-small on full text, with nearly the same retrieval quality (MTEB retrieval 50.2 vs 51.7).

The choice comes from, in order: TALENTLENS_DEVICE (env/.env), the benchmark saved at install
time (`talentlens benchmark`, stored in settings.json), else "use the GPU if one works".

"Works" is checked, not assumed: the CUDA 13 build of ONNX Runtime loads its libraries on any
NVIDIA card, but its kernels need compute capability 7.5+ (Turing, 2018, or newer). Older cards
(Pascal MX/GTX 10xx, Maxwell, Volta) fail when a model loads, so they count as "no GPU" here.
"""

from __future__ import annotations

import functools
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

Device = Literal["cpu", "cuda"]
log = logging.getLogger(__name__)

# Oldest NVIDIA architecture the bundled CUDA 13 ONNX Runtime runs on (Turing)
MIN_COMPUTE_CAPABILITY = (7, 5)


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
    pick the faster. Returns {"choice", "cpu_per_s", "cuda_per_s"|None, "gpu_name"|None, and,
    when an NVIDIA card is present, "compute_capability", "vram_mb" and maybe "cuda_error"}."""
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
    gpu = gpu_info()  # recorded even when CUDA fails: that is when the name matters most
    if gpu:
        results.update(
            gpu_name=gpu["name"],
            compute_capability=gpu["compute_capability"],
            vram_mb=gpu["vram_mb"],
        )
        if cuda_supported(gpu) is False and not results.get("cuda_error"):
            need = ".".join(map(str, MIN_COMPUTE_CAPABILITY))
            results["cuda_error"] = (
                f"{gpu['name']} (compute capability {gpu['compute_capability']}) is too old "
                f"for the GPU build; it needs {need} or newer"
            )
    cpu_s, gpu_s = results["cpu_per_s"] or 0, results["cuda_per_s"] or 0
    results["choice"] = "cuda" if gpu_s > cpu_s * 1.2 else "cpu"
    results["at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return results


def needs_benchmark(saved: dict[str, Any] | None) -> bool:
    """Should an install/update (re)measure CPU vs GPU? Yes when nothing was measured yet (an
    install updated in-app from before the benchmark existed), or when the saved choice is the
    GPU but the GPU can't be used any more (driver or ONNX Runtime changed)."""
    from .embed import gpu_available

    if not saved or saved.get("choice") not in ("cpu", "cuda"):
        return True
    return saved.get("choice") == "cuda" and not gpu_available()


def parse_compute_capability(value: str) -> tuple[int, int] | None:
    """'6.1' -> (6, 1); anything unreadable -> None."""
    try:
        major, minor = value.strip().split(".", 1)
        return int(major), int(minor)
    except (ValueError, AttributeError):
        return None


def cuda_supported(info: dict[str, Any] | None) -> bool | None:
    """Can the bundled CUDA build run on this card? None when unknown (no nvidia-smi output)."""
    if not info:
        return None
    cc = parse_compute_capability(info.get("compute_capability") or "")
    if cc is None:
        return None
    return cc >= MIN_COMPUTE_CAPABILITY


@functools.cache
def gpu_info() -> dict[str, Any] | None:
    """First NVIDIA GPU as {name, compute_capability, vram_mb}, or None (no card / no driver)."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [
                exe,
                "--query-gpu=name,compute_cap,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            **({"creationflags": 0x08000000} if os.name == "nt" else {}),  # no console window
        )
        line = out.stdout.strip().splitlines()[0]
    except (OSError, subprocess.SubprocessError, IndexError):
        return None
    return parse_gpu_line(line)


def parse_gpu_line(line: str) -> dict[str, Any] | None:
    """'NVIDIA GeForce MX250, 6.1, 2048' -> {'name': ..., 'compute_capability': '6.1',
    'vram_mb': 2048}. Older drivers print '[N/A]' or an error for compute_cap."""
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 3 or not parts[0]:
        return None
    try:
        vram = int(float(parts[-1]))
    except ValueError:
        vram = None
    cc = parts[-2] if parse_compute_capability(parts[-2]) else None
    return {"name": ", ".join(parts[:-2]), "compute_capability": cc, "vram_mb": vram}


def system_ram_gb() -> float | None:
    """Installed memory in GB, or None if it can't be read."""
    try:
        if os.name == "nt":
            import ctypes

            class _Mem(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            m = _Mem()
            m.dwLength = ctypes.sizeof(_Mem)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):  # type: ignore[attr-defined]
                return None
            total = m.ullTotalPhys
        else:
            total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        return round(total / 1024**3, 1)
    except (OSError, ValueError, AttributeError):
        return None


def ai_memory_budget(
    gpu: dict[str, Any] | None, ram_gb: float | None, apple_silicon: bool
) -> float:
    """Memory (GB) a local LLM can use on the graphics side: an NVIDIA card's own memory (Ollama
    runs older cards too, unlike the CUDA 13 ONNX build), half the unified memory on Apple
    silicon, else 0 (CPU only)."""
    if gpu and gpu.get("vram_mb"):
        return round(gpu["vram_mb"] / 1024, 1)
    if apple_silicon and ram_gb:
        return round(ram_gb / 2, 1)
    return 0.0


@functools.cache
def hardware() -> dict[str, Any]:
    """This computer, as far as choosing a local model goes."""
    import platform
    import sys

    gpu = gpu_info()
    ram = system_ram_gb()
    apple = sys.platform == "darwin" and platform.machine() == "arm64"
    return {
        "gpu": gpu["name"] if gpu else ("Apple silicon" if apple else None),
        "vram_gb": round(gpu["vram_mb"] / 1024, 1) if gpu and gpu.get("vram_mb") else None,
        "ram_gb": ram,
        "budget_gb": ai_memory_budget(gpu, ram, apple),
    }
