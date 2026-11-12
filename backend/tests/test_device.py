"""Models load on the GPU when available and always fall back to the CPU."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import pytest

from talentlens.ai import embed


class FakeModel:
    calls: ClassVar[list[dict[str, Any]]] = []
    fail_on_cuda = False

    def __init__(self, name: str, cache_dir: str, **kw: Any) -> None:
        FakeModel.calls.append(kw)
        if kw.get("cuda") and FakeModel.fail_on_cuda:
            raise RuntimeError("CUDA failure")
        self.kw = kw


@pytest.fixture(autouse=True)
def reset(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeModel.calls = []
    FakeModel.fail_on_cuda = False
    monkeypatch.setattr(embed, "_GPU", None)


def test_uses_gpu_when_available(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(embed, "gpu_available", lambda: True)
    m = embed.load_cached_first(FakeModel, "m", tmp_path)
    assert m.kw.get("cuda") is True


def test_falls_back_to_cpu_when_gpu_load_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(embed, "gpu_available", lambda: True)
    FakeModel.fail_on_cuda = True
    m = embed.load_cached_first(FakeModel, "m", tmp_path)
    assert "cuda" not in m.kw
    assert any(c.get("cuda") for c in FakeModel.calls)


def test_cpu_only_when_disabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TALENTLENS_DEVICE", "cpu")
    assert embed.gpu_available() is False
    m = embed.load_cached_first(FakeModel, "m", tmp_path)
    assert "cuda" not in m.kw
