"""Minimal Ollama client: health check plus JSON-schema-constrained chat."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Protocol

import httpx

log = logging.getLogger(__name__)


class LLMUnavailable(RuntimeError):
    pass


class LLM(Protocol):
    name: str

    def available(self) -> bool: ...

    def status(self) -> dict[str, Any]: ...

    def json_chat(
        self, system: str, user: str, schema: dict[str, Any], *, max_tokens: int = 512
    ) -> dict[str, Any]: ...


class OllamaLLM:
    def __init__(self, base_url: str, model: str, timeout_s: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.name = f"ollama:{model}"
        self.timeout_s = timeout_s
        self._last_check = 0.0
        self._last_ok = False
        self._last_error: str | None = None

    def _check(self) -> bool:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=3)
            r.raise_for_status()
            models = {m.get("name") for m in r.json().get("models", [])}
            base = self.model if ":" in self.model else f"{self.model}:latest"
            if base not in models and self.model not in models:
                self._last_error = (
                    f"Model '{self.model}' is not pulled (run: ollama pull {self.model})"
                )
                return False
            self._last_error = None
            return True
        except (httpx.HTTPError, ValueError) as e:
            self._last_error = f"Ollama is not reachable at {self.base_url}: {e.__class__.__name__}"
            return False

    def available(self) -> bool:
        now = time.monotonic()
        if now - self._last_check > 15:
            self._last_ok = self._check()
            self._last_check = now
        return self._last_ok

    def status(self) -> dict[str, Any]:
        ok = self.available()
        return {"mode": "ollama", "model": self.model, "available": ok, "error": self._last_error}

    def json_chat(
        self, system: str, user: str, schema: dict[str, Any], *, max_tokens: int = 512
    ) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "format": schema,
            "stream": False,
            "keep_alive": "15m",
            "options": {"temperature": 0, "num_ctx": 6144, "num_predict": max_tokens},
        }
        last: Exception | None = None
        for attempt in range(2):
            try:
                r = httpx.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout_s)
                r.raise_for_status()
                content = r.json()["message"]["content"]
                data = json.loads(content)
                if not isinstance(data, dict):
                    raise ValueError("LLM returned non-object JSON")
                return data
            except (httpx.HTTPError, KeyError, ValueError) as e:
                last = e
                log.warning("Ollama call failed (attempt %d): %s", attempt + 1, e)
                self._last_check = 0  # force a fresh health check
        raise LLMUnavailable(str(last))


class NoLLM:
    name = "off"

    def available(self) -> bool:
        return False

    def status(self) -> dict[str, Any]:
        return {"mode": "off", "available": False, "error": "Disabled (TALENTLENS_LLM=off)"}

    def json_chat(self, *a: Any, **k: Any) -> dict[str, Any]:
        raise LLMUnavailable("LLM disabled")


class MockLLM:
    """Deterministic stand-in for tests: echoes rule-based extraction in the LLM's schema."""

    name = "mock"

    def __init__(self) -> None:
        self.calls = 0

    def available(self) -> bool:
        return True

    def status(self) -> dict[str, Any]:
        return {"mode": "mock", "model": "mock", "available": True, "error": None}

    def json_chat(
        self, system: str, user: str, schema: dict[str, Any], *, max_tokens: int = 512
    ) -> dict[str, Any]:
        from . import rules

        self.calls += 1
        text = user.split("<<<", 1)[-1].rsplit(">>>", 1)[0]
        props = schema.get("properties", {})
        if "must_have_skills" in props:  # JD schema
            skills = rules.extract_skills(text, limit=12)
            city, country = rules.extract_location(text)
            return {
                "title": rules.extract_title(text, None) or "",
                "must_have_skills": skills[:6],
                "nice_to_have_skills": skills[6:12],
                "min_years": rules.explicit_years(text) or 0,
                "max_years": 0,
                "city": city or "",
                "country": country or "",
                "domains": rules.extract_domains(text),
                "summary": text[:120],
            }
        if "reason" in props:  # match explanation schema
            return {"reason": "Mock explanation.", "strengths": ["mock"], "gaps": []}
        f = rules.extract(text, "mock.pdf")
        return {
            "name": f.name or "",
            "current_title": f.title or "",
            "city": f.city or "",
            "country": f.country or "",
            "total_years_experience": f.years_exp or 0,
            "skills": f.skills[:25],
            "domains": f.domains,
            "education": f.education,
            "summary": (f.summary or "")[:200],
        }
