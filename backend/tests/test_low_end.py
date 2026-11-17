"""Low-end and older hardware (issue #8): GPU capability checks, hardware-aware model choice,
and AI answers that stay grounded in the text (no copied example industries)."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from talentlens.ai import device, embed, models
from talentlens.ai.extract import grounded_domains, merge
from talentlens.config import Settings
from talentlens.enrich import CVFields
from talentlens.jd import parse_rules, requirements_from_llm
from talentlens.settings_store import SettingsStore
from talentlens.state import AppState

from .conftest import ALICE, BOB, make_pdf

MX250 = {"name": "NVIDIA GeForce MX250", "compute_capability": "6.1", "vram_mb": 2048}
RTX = {"name": "NVIDIA GeForce RTX 4060 Laptop GPU", "compute_capability": "8.9", "vram_mb": 8188}

JD = (
    "We are hiring a Senior Backend Engineer in Bangalore or Pune. Must have: Python, Django or "
    "FastAPI, PostgreSQL, REST APIs, AWS. Nice to have: Kubernetes, Redis, Kafka. 5-8 years of "
    "experience. You will design scalable services, mentor juniors and work with product teams."
)


# --- GPU detection --------------------------------------------------------------------
def test_parse_gpu_line() -> None:
    assert device.parse_gpu_line("NVIDIA GeForce MX250, 6.1, 2048") == MX250
    old_driver = device.parse_gpu_line("Quadro K620, [N/A], 2000")
    assert old_driver == {"name": "Quadro K620", "compute_capability": None, "vram_mb": 2000}
    assert device.parse_gpu_line("") is None


@pytest.mark.parametrize(
    ("info", "ok"),
    [(MX250, False), (RTX, True), ({**MX250, "compute_capability": "7.5"}, True), (None, None)],
)
def test_cuda_supported(info: dict[str, Any] | None, ok: bool | None) -> None:
    assert device.cuda_supported(info) is ok


@pytest.fixture
def fake_cuda_ort(monkeypatch: pytest.MonkeyPatch) -> None:
    """An ONNX Runtime whose CUDA libraries load (as the CUDA 13 wheels do on any NVIDIA card)."""
    ort = types.SimpleNamespace(
        get_available_providers=lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"],
        preload_dlls=lambda: None,
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", ort)
    monkeypatch.setattr(embed, "_GPU", None)
    monkeypatch.delenv("TALENTLENS_DEVICE", raising=False)


@pytest.mark.usefixtures("fake_cuda_ort")
def test_old_gpu_is_not_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(device, "gpu_info", lambda: MX250)
    assert embed.gpu_available() is False
    assert device.resolve(None) == "cpu"  # so the CPU profile (small model, short text) is used


@pytest.mark.usefixtures("fake_cuda_ort")
def test_new_gpu_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(device, "gpu_info", lambda: RTX)
    assert embed.gpu_available() is True
    assert device.resolve(None) == "cuda"


@pytest.mark.usefixtures("fake_cuda_ort")
def test_failed_gpu_load_switches_the_process_to_cpu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(device, "gpu_info", lambda: None)  # unknown card: try it

    class Model:
        def __init__(self, name: str, cache_dir: str, **kw: Any) -> None:
            if kw.get("cuda"):
                raise RuntimeError("CUBLAS failure 8")
            self.kw = kw

    assert embed.gpu_available() is True
    m = embed.load_cached_first(Model, "m", tmp_path)
    assert m.kw["cuda"] is False
    assert embed.gpu_available() is False  # reported as the CPU from now on


def test_needs_benchmark(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embed, "gpu_available", lambda: False)
    assert device.needs_benchmark(None) is True  # updated in-app, never measured
    assert device.needs_benchmark({"choice": "cpu"}) is False
    assert device.needs_benchmark({"choice": "cuda"}) is True  # the GPU stopped working
    monkeypatch.setattr(embed, "gpu_available", lambda: True)
    assert device.needs_benchmark({"choice": "cuda"}) is False


def test_benchmark_if_needed(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    from talentlens import __main__ as cli

    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    runs: list[int] = []

    def fake_benchmark(cache_dir: Path) -> dict[str, Any]:
        runs.append(1)
        return {"cpu_per_s": 15.1, "cuda_per_s": None, "choice": "cpu", **MX250}

    monkeypatch.setattr(device, "benchmark", fake_benchmark)
    with pytest.raises(SystemExit):
        cli.main(["benchmark", "--if-needed"])
    assert runs == [1]
    assert SettingsStore(settings.settings_path).get("device") == "cpu"
    with pytest.raises(SystemExit):
        cli.main(["benchmark", "--if-needed"])
    assert runs == [1]  # already measured: skipped
    assert "already measured" in capsys.readouterr().out


# --- local LLM choice -------------------------------------------------------------------
def test_memory_budget() -> None:
    assert device.ai_memory_budget(MX250, 15.8, apple_silicon=False) == 2.0
    assert device.ai_memory_budget(None, 16.0, apple_silicon=True) == 8.0
    assert device.ai_memory_budget(None, 16.0, apple_silicon=False) == 0.0


@pytest.mark.parametrize(
    ("budget", "ram", "model"),
    [
        # accuracy first: the 3B even when it runs partly on the processor
        (0.0, 16.0, "qwen2.5:3b-instruct"),  # CPU only
        (2.0, 15.8, "qwen2.5:3b-instruct"),  # 2 GB MX250 laptop
        (4.0, None, "qwen2.5:3b-instruct"),
        # the thinking 4B only where it runs on the graphics card
        (6.0, 16.0, "qwen3.5:4b-q4_K_M"),
        (12.0, 32.0, "qwen3.5:4b-q4_K_M"),
        # the 1.5B only when memory is too short for the 3B
        (0.0, 4.0, "qwen2.5:1.5b-instruct"),
        (2.0, 6.0, "qwen2.5:1.5b-instruct"),
    ],
)
def test_recommend(budget: float, ram: float | None, model: str) -> None:
    assert models.recommend(budget, ram) == model
    assert model in models.BY_ID


def test_catalog_marks_fit_and_one_recommendation() -> None:
    cat = {m["id"]: m for m in models.catalog(2.0, 15.8)}
    assert cat["qwen2.5:1.5b-instruct"]["fits"] is True
    assert cat["qwen2.5:3b-instruct"]["fits"] is False
    assert cat["qwen3.5:4b-q4_K_M"]["fits"] is False
    # accuracy first: the 3B is recommended although it doesn't fit the 2 GB card
    assert [m for m in cat if cat[m]["recommended"]] == ["qwen2.5:3b-instruct"]
    # CPU only: nothing fits on a graphics card, so fit isn't flagged on every model
    assert {m["fits"] for m in models.catalog(0.0)} == {None}


def test_recommend_model_cli(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from talentlens import __main__ as cli

    monkeypatch.setattr(device, "hardware", lambda: {"budget_gb": 2.0, "ram_gb": 15.8})
    with pytest.raises(SystemExit):
        cli.main(["recommend-model"])
    assert capsys.readouterr().out.strip() == "qwen2.5:3b-instruct"


# --- grounded AI answers ------------------------------------------------------------------
def test_grounded_domains_drop_unsupported_industries() -> None:
    copied = ["Telecommunications", "Retail"]  # the old prompt examples
    assert grounded_domains(copied, "Backend engineer, Python and AWS.", 3) == []
    assert grounded_domains(copied, "5G RAN rollout for a telecom operator.", 3) == [
        "Telecommunications"
    ]
    assert grounded_domains(["banking"], None, 3) == ["Banking & Financial Services"]


def test_merge_with_text_drops_copied_industries() -> None:
    rule = CVFields(name="Alice Example", domains=[], extractor="rules")
    llm = {"name": "Alice Example", "domains": ["Telecommunications", "Retail", "Banking"]}
    assert merge(rule, llm, ALICE).domains == ["Banking & Financial Services"]


def test_prompts_have_no_example_industries() -> None:
    from talentlens.ai import extract
    from talentlens.jd import JD_SYSTEM

    for prompt in (JD_SYSTEM, extract.CV_SYSTEM, extract.CV_SYSTEM_COMPACT):
        assert "Telecommunications" not in prompt and "Retail" not in prompt


def test_rules_split_inline_nice_to_have_and_skip_hiring() -> None:
    r = parse_rules(JD)
    assert {"Python", "Django", "FastAPI", "PostgreSQL"} <= set(r.must_have_skills)
    assert {"Kubernetes", "Redis", "Kafka"} <= set(r.nice_to_have_skills)
    assert not {"Kubernetes", "Redis", "Kafka"} & set(r.must_have_skills)
    assert "Talent Acquisition" not in r.must_have_skills  # "We are hiring"
    assert r.locations == ["Bengaluru", "Pune"]
    assert (r.min_years, r.max_years) == (5.0, 8.0)


def test_llm_requirements_keep_labels_locations_and_grounding() -> None:
    # what qwen2.5:3b returned for this JD on a 2 GB laptop
    data = {
        "title": "Senior Backend Engineer",
        "must_have_skills": [
            "Python",
            "Django",
            "FastAPI",
            "PostgreSQL",
            "REST APIs",
            "AWS",
            "Kubernetes",
            "Redis",
            "Kafka",
        ],
        "nice_to_have_skills": [],
        "min_years": 5,
        "max_years": 8,
        "city": "Bangalore",
        "country": "India",
        "domains": ["Telecommunications", "Retail"],
        "summary": "Backend engineer.",
    }
    r = requirements_from_llm(data, JD, parse_rules(JD))
    assert {"Kubernetes", "Redis", "Kafka"} <= set(r.nice_to_have_skills)
    assert not {"Kubernetes", "Redis", "Kafka"} & set(r.must_have_skills)
    assert "Python" in r.must_have_skills
    assert r.locations == ["Bengaluru", "Pune"]
    assert r.domains == []


def test_stored_industries_are_rechecked_once(settings: Settings) -> None:
    make_pdf(settings.cv_dir / "resume-1.pdf", ALICE)
    make_pdf(settings.cv_dir / "resume-2.pdf", BOB)
    st = AppState.build(settings)
    st.indexer.run()
    st.indexer.refine_pending(should_stop=lambda: False)
    # simulate a library read by the old prompt: copied example industries everywhere
    with st.db.write() as conn:
        for row in conn.execute("SELECT id, llm_json FROM cvs").fetchall():
            data = json.loads(row["llm_json"] or "{}")
            data["domains"] = ["Telecommunications", "Retail"]
            conn.execute(
                "UPDATE cvs SET llm_json=?, llm_sha=sha256, domains=? WHERE id=?",
                (json.dumps(data), json.dumps(["Telecommunications", "Retail"]), row["id"]),
            )
    st.db.set_meta("domains_v", "1")
    assert st.indexer.reground_domains() >= 2  # plus the fixture folder's own resumes
    with st.db.connect() as conn:
        doms = {
            r["filename"]: json.loads(r["domains"])
            for r in conn.execute("SELECT filename, domains FROM cvs")
        }
        alice_facet = {
            r[0]
            for r in conn.execute(
                "SELECT domain FROM cv_domains JOIN cvs ON cvs.id = cv_id "
                "WHERE filename='resume-1.pdf'"
            )
        }
    assert "Telecommunications" not in doms["resume-1.pdf"]  # Alice: banking/fintech
    assert "Retail" in doms["resume-2.pdf"]  # Bob really is retail
    assert "Telecommunications" not in alice_facet  # the search filter is updated too
    assert st.indexer.reground_domains() == 0  # one-time
