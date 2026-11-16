"""Raw Ollama chat calls with timing, token and memory statistics."""

from __future__ import annotations

import contextlib
import json
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import psutil

OLLAMA = "http://127.0.0.1:11434"


@dataclass
class CallResult:
    ok: bool
    data: dict[str, Any] | None
    raw: str
    wall_s: float
    prompt_tokens: int = 0
    eval_tokens: int = 0
    eval_s: float = 0.0
    prompt_s: float = 0.0
    load_s: float = 0.0
    error: str = ""
    thinking_chars: int = 0

    @property
    def tok_per_s(self) -> float:
        return self.eval_tokens / self.eval_s if self.eval_s else 0.0


def chat_json(
    model: str,
    system: str,
    user: str,
    schema: dict[str, Any],
    *,
    num_ctx: int = 8192,
    max_tokens: int = 1200,
    think: bool | None = None,
    timeout: float = 900.0,
    keep_alive: str = "30m",
) -> CallResult:
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "format": schema,
        "stream": False,
        "keep_alive": keep_alive,
        "options": {"temperature": 0, "num_ctx": num_ctx, "num_predict": max_tokens, "seed": 7},
    }
    if think is not None:
        body["think"] = think
    t0 = time.perf_counter()
    try:
        r = httpx.post(f"{OLLAMA}/api/chat", json=body, timeout=timeout)
        r.raise_for_status()
        j = r.json()
    except (httpx.HTTPError, ValueError) as e:
        return CallResult(False, None, "", time.perf_counter() - t0, error=str(e)[:300])
    wall = time.perf_counter() - t0
    msg = j.get("message", {})
    content = msg.get("content", "") or ""
    res = CallResult(
        ok=False,
        data=None,
        raw=content,
        wall_s=wall,
        prompt_tokens=j.get("prompt_eval_count", 0) or 0,
        eval_tokens=j.get("eval_count", 0) or 0,
        eval_s=(j.get("eval_duration", 0) or 0) / 1e9,
        prompt_s=(j.get("prompt_eval_duration", 0) or 0) / 1e9,
        load_s=(j.get("load_duration", 0) or 0) / 1e9,
        thinking_chars=len(msg.get("thinking", "") or ""),
    )
    try:
        d = json.loads(content)
        if isinstance(d, dict):
            res.ok, res.data = True, d
        else:
            res.error = "json not an object"
    except ValueError as e:
        res.error = f"invalid json: {e}"[:200]
    return res


def unload(model: str) -> None:
    with contextlib.suppress(httpx.HTTPError):
        httpx.post(f"{OLLAMA}/api/generate", json={"model": model, "keep_alive": 0}, timeout=60)


def ps() -> list[dict[str, Any]]:
    try:
        return httpx.get(f"{OLLAMA}/api/ps", timeout=10).json().get("models", [])
    except httpx.HTTPError:
        return []


@dataclass
class MemSampler:
    """Peak GPU memory (nvidia-smi) and peak RSS of Ollama processes while running."""

    interval: float = 0.5
    peak_vram_mb: float = 0.0
    peak_ram_mb: float = 0.0
    _stop: threading.Event = field(default_factory=threading.Event)
    _t: threading.Thread | None = None

    def _vram(self) -> float:
        try:
            out = (
                subprocess.run(
                    ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                .stdout.strip()
                .splitlines()
            )
            return float(out[0]) if out else 0.0
        except (OSError, ValueError, subprocess.SubprocessError):
            return 0.0

    def _ram(self) -> float:
        tot = 0
        for p in psutil.process_iter(["name", "memory_info"]):
            try:
                if "ollama" in (p.info["name"] or "").lower():
                    tot += p.info["memory_info"].rss
            except (psutil.Error, TypeError):
                pass
        return tot / 1e6

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            self.peak_vram_mb = max(self.peak_vram_mb, self._vram())
            self.peak_ram_mb = max(self.peak_ram_mb, self._ram())

    def __enter__(self) -> MemSampler:
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._t:
            self._t.join(timeout=5)
