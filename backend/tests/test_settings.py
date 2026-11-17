import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from talentlens.config import REPO_ROOT, Settings
from talentlens.db import Database
from talentlens.library import FolderProblem, library_key
from talentlens.state import AppState

from .conftest import ALICE, BOB, make_pdf


def _settings(tmp_path: Path, **kw) -> Settings:
    base = dict(
        data_dir=tmp_path / "appdata",
        llm="mock",
        embeddings="mock",
        watch=False,
        scan_on_startup=False,
        _env_file=None,
    )
    base.update(kw)
    return Settings(**base)


@pytest.fixture
def no_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("talentlens.state.discover_cv_dirs", lambda: [])


def _client(settings: Settings) -> TestClient:
    from talentlens.main import create_app

    return TestClient(create_app(settings))


def _folder(tmp_path: Path, name: str, people: dict[str, str]) -> Path:
    d = tmp_path / name
    d.mkdir()
    for fn, text in people.items():
        make_pdf(d / fn, text)
    return d


def test_first_run_without_folder_asks_for_setup(tmp_path: Path, no_discovery: None) -> None:
    with _client(_settings(tmp_path)) as c:
        h = c.get("/api/health").json()
        assert h["needs_setup"] is True and h["cv_dir"] is None
        assert c.get("/api/index/status").json()["state"] == "no_folder"
        r = c.get("/api/cvs")
        assert r.status_code == 409 and r.json()["code"] == "no_folder"
        s = c.get("/api/settings").json()
        assert s["cv_dir"] is None and s["cv_dir_source"] == "none" and s["onboarded"] is False


def test_choose_switch_and_return_keeps_each_library(tmp_path: Path, no_discovery: None) -> None:
    a = _folder(tmp_path, "A", {"Alice.pdf": ALICE})
    b = _folder(tmp_path, "B", {"Bob.pdf": BOB})
    with _client(_settings(tmp_path)) as c:
        st = c.app.state.tl
        s = c.put("/api/settings", json={"cv_dir": str(a)}).json()
        assert s["cv_dir"] == str(a.resolve()) and s["cv_dir_source"] == "app"
        assert st.queue.wait_idle(60)
        assert [i["name"] for i in c.get("/api/cvs").json()["items"]] == ["Alice Example"]

        c.put("/api/settings", json={"cv_dir": str(b)})
        assert st.queue.wait_idle(60)
        assert [i["name"] for i in c.get("/api/cvs").json()["items"]] == ["Bob Sample"]

        c.put("/api/settings", json={"cv_dir": str(a)})
        assert st.queue.wait_idle(60)
        report = st.queue.status().last_report
        assert report["unchanged"] == 1 and report["added"] == 0  # library A was kept
        assert (st.settings.libraries_dir / library_key(a) / "talentlens.db").exists()
        assert (st.settings.libraries_dir / library_key(b) / "talentlens.db").exists()

    # remembered in settings.json, not .env
    saved = json.loads((tmp_path / "appdata" / "settings.json").read_text())
    assert saved["cv_dir"] == str(a.resolve())
    st2 = AppState.build(_settings(tmp_path))
    assert st2.cv_dir_source == "app" and st2.library.folder == a.resolve()


def test_config_folder_is_locked(tmp_path: Path) -> None:
    a = _folder(tmp_path, "A", {"Alice.pdf": ALICE})
    b = _folder(tmp_path, "B", {})
    with _client(_settings(tmp_path, cv_dir=a)) as c:
        s = c.get("/api/settings").json()
        assert s["cv_dir_locked"] is True and s["cv_dir_source"] == "config"
        r = c.put("/api/settings", json={"cv_dir": str(b)})
        assert r.status_code == 400 and "configuration" in r.json()["detail"]


def test_folder_validation_messages(tmp_path: Path, no_discovery: None) -> None:
    f = tmp_path / "file.pdf"
    f.write_bytes(b"%PDF")
    with _client(_settings(tmp_path)) as c:
        for path, words in [
            (tmp_path / "missing", "doesn't exist"),
            (f, "not a folder"),
            (tmp_path / "appdata", "data folder"),
        ]:
            r = c.put("/api/settings", json={"cv_dir": str(path)})
            assert r.status_code == 400 and words in r.json()["detail"], r.json()
            chk = c.post("/api/settings/check-folder", json={"path": str(path)}).json()
            assert chk["ok"] is False


def test_check_folder_counts(tmp_path: Path, no_discovery: None) -> None:
    a = _folder(tmp_path, "A", {"Alice.pdf": ALICE, "Bob.pdf": BOB})
    (a / "notes.txt").write_text("x")
    (a / "~$lock.docx").write_bytes(b"x")
    with _client(_settings(tmp_path)) as c:
        r = c.post("/api/settings/check-folder", json={"path": str(a)}).json()
        assert r["ok"] and r["count"] == 2 and "Found 2 resumes" in r["message"]


def test_auto_discovery_is_used_and_remembered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = _folder(tmp_path, "A", {"Alice.pdf": ALICE})
    monkeypatch.setattr("talentlens.state.discover_cv_dirs", lambda: [a])
    st = AppState.build(_settings(tmp_path))
    assert st.cv_dir_source == "auto" and st.library.folder == a
    assert json.loads((tmp_path / "appdata" / "settings.json").read_text())["cv_dir"] == str(a)


def test_native_picker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_discovery: None) -> None:
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=b"C:\\Hiring\\CVs\r\n", stderr=b"")

    monkeypatch.setattr("talentlens.api.system.subprocess.run", fake_run)
    with _client(_settings(tmp_path)) as c:
        assert c.post("/api/system/pick-folder").json() == {
            "path": "C:\\Hiring\\CVs",
            "cancelled": False,
        }
        monkeypatch.setattr(
            "talentlens.api.system.subprocess.run",
            lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b""),
        )
        assert c.post("/api/system/pick-folder").json()["cancelled"] is True
    assert calls


def test_legacy_database_is_copied_not_moved(tmp_path: Path, no_discovery: None) -> None:
    a = _folder(tmp_path, "A", {"Alice.pdf": ALICE})
    s = _settings(tmp_path, cv_dir=a)
    s.ensure_dirs()
    legacy = Database(s.legacy_db_path)
    with legacy.write() as conn:
        conn.execute(
            "INSERT INTO cvs(rel_path, filename, ext, sha256, size, mtime, status, name) "
            "VALUES ('Alice.pdf','Alice.pdf','.pdf','X',1,1,'indexed','Old Alice')"
        )
    st = AppState.build(s)
    with st.db.connect() as conn:
        assert conn.execute("SELECT name FROM cvs").fetchone()[0] == "Old Alice"
    assert s.legacy_db_path.exists()  # original kept
    other = _folder(tmp_path, "Other", {"Bob.pdf": BOB})
    st2 = AppState.build(_settings(tmp_path, cv_dir=other))  # legacy rows don't fit this folder
    with st2.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM cvs").fetchone()[0] == 0


def test_ai_toggle_and_model(tmp_path: Path, no_discovery: None) -> None:
    s = Settings(
        data_dir=tmp_path / "appdata",
        embeddings="mock",
        watch=False,
        scan_on_startup=False,
        ollama_url="http://127.0.0.1:9",  # nothing listens: no real LLM in tests
        _env_file=None,
    )
    with _client(s) as c:
        off = c.put("/api/settings", json={"ai_enabled": False}).json()
        assert off["ai"]["mode"] == "off" and off["ai"]["enabled"] is False
        on = c.put(
            "/api/settings", json={"ai_enabled": True, "ollama_model": "qwen3.5:4b-q4_K_M"}
        ).json()
        assert on["ai"]["mode"] == "ollama" and on["ai"]["model"] == "qwen3.5:4b-q4_K_M"
        # the dropdown's catalog: one recommended entry; Ollama unreachable -> installed unknown
        ids = [m["id"] for m in on["ai"]["models"]]
        assert "qwen3.5:4b-q4_K_M" in ids and "qwen2.5:3b-instruct" in ids
        assert sum(m["recommended"] for m in on["ai"]["models"]) == 1
        assert on["ai"]["installed"] is None
        assert on["ai"]["recommended_model"] in ids
        assert set(on["ai"]["hardware"]) >= {"gpu", "vram_gb", "ram_gb", "budget_gb"}
        assert all("fits" in m for m in on["ai"]["models"])
        assert c.put("/api/settings", json={"ollama_model": "evil"}).status_code == 400
        # the 1.5B is back as the low-memory choice (2 GB graphics cards, CPU-only laptops)
        assert (
            c.put("/api/settings", json={"ollama_model": "qwen2.5:1.5b-instruct"}).status_code
            == 200
        )


def test_catalog_models_get_their_own_llm_settings() -> None:
    from talentlens.ai import build_llm
    from talentlens.ai.models import MODELS

    for m in MODELS:
        llm = build_llm(Settings(llm="ollama", ollama_model=m.id, _env_file=None))
        assert llm.model == m.id and llm.num_ctx == m.num_ctx and llm.think == m.think
    # a model set by hand in .env keeps the old defaults
    other = build_llm(Settings(llm="ollama", ollama_model="llama3.1:8b", _env_file=None))
    assert other.think is None and other.num_ctx == 2048


def test_thinking_models_send_think_and_a_bigger_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from talentlens.ai.llm import OllamaLLM

    sent: list[dict] = []

    class Resp:
        def raise_for_status(self) -> None: ...

        def json(self) -> dict:
            return {"message": {"content": '{"ok": true}', "thinking": "..."}}

    def fake_post(url: str, json: dict, timeout: float) -> Resp:
        sent.append(json)
        return Resp()

    monkeypatch.setattr(httpx, "post", fake_post)
    thinking = OllamaLLM("http://x", "qwen3.5:4b-q4_K_M", num_ctx=8192, think=True)
    assert thinking.json_chat("s", "u", {"type": "object"}, max_tokens=400) == {"ok": True}
    plain = OllamaLLM("http://x", "gemma4:e4b-it-q4_K_M", think=None)
    plain.json_chat("s", "u", {"type": "object"}, max_tokens=400)
    assert sent[0]["think"] is True
    assert sent[0]["options"]["num_predict"] == 400 + OllamaLLM.THINK_BUDGET
    assert "think" not in sent[1] and sent[1]["options"]["num_predict"] == 400


def test_app_never_creates_env_file(tmp_path: Path, no_discovery: None) -> None:
    env = REPO_ROOT / ".env"
    existed = env.exists()
    before = env.read_bytes() if existed else None
    a = _folder(tmp_path, "A", {"Alice.pdf": ALICE})
    with _client(_settings(tmp_path)) as c:
        c.put("/api/settings", json={"cv_dir": str(a), "onboarded": True})
    assert env.exists() == existed
    if existed:
        assert env.read_bytes() == before


def test_switch_folder_rejects_locked_in_code(tmp_path: Path) -> None:
    a = _folder(tmp_path, "A", {})
    st = AppState.build(_settings(tmp_path, cv_dir=a))
    with pytest.raises(FolderProblem):
        st.switch_folder(tmp_path)
