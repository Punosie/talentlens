"""Forced updates: version comparison, the GitHub check and the one-click launcher (no real
update is ever run; network and processes are faked)."""

import json
import subprocess
import tomllib
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from talentlens import __version__, updates
from talentlens.config import REPO_ROOT, Settings
from talentlens.updates import Updater, is_newer, parse_version


def test_version_numbers_agree() -> None:
    """A release is a version bump: pyproject and talentlens.__version__ must move together."""
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == __version__


def test_version_comparison() -> None:
    assert parse_version("0.10.2") == (0, 10, 2)
    assert is_newer("0.2.0", "0.1.9")
    assert is_newer("0.10.0", "0.9.9")  # numeric, not alphabetical
    assert is_newer("1.0", "0.99.99")
    assert not is_newer("0.2.0", "0.2.0")
    assert not is_newer("0.1.0", "0.2.0")
    assert not is_newer("0.2.0rc1", "0.2.0")


def _settings(tmp_path: Path, **kw: object) -> Settings:
    return Settings(data_dir=tmp_path / "appdata", update_check=False, _env_file=None, **kw)


class _Resp:
    def __init__(self, text: str, status: int = 200) -> None:
        self.text = text
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad", request=None, response=None)  # type: ignore[arg-type]


def test_check_reads_the_version_online_when_not_a_git_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    def fake_get(url: str, **_: object) -> _Resp:
        seen.append(url)
        return _Resp('"""x"""\n\n__version__ = "99.0.0"\n')

    monkeypatch.setattr(httpx, "get", fake_get)
    up = Updater(_settings(tmp_path, update_repo="acme/tl", update_branch="main"), root=tmp_path)
    st = up.check()
    assert seen == ["https://raw.githubusercontent.com/acme/tl/main/backend/talentlens/__init__.py"]
    assert st.latest == "99.0.0" and st.update_required and st.error is None
    assert st.can_update is False  # not a git checkout: the UI shows manual instructions


def test_check_never_blocks_when_offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_: object, **__: object) -> _Resp:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "get", boom)
    st = Updater(_settings(tmp_path), root=tmp_path).check()
    assert st.update_required is False and st.latest is None
    assert st.error and "Couldn't check" in st.error


def test_check_uses_git_in_a_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".git").mkdir()
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess:
        calls.append(cmd)
        out = '__version__ = "0.0.1"\n' if cmd[1] == "show" else ""
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

    monkeypatch.setattr(updates, "_git", lambda: "git")
    monkeypatch.setattr(subprocess, "run", fake_run)
    st = Updater(_settings(tmp_path), root=tmp_path).check()
    assert [c[1] for c in calls] == ["fetch", "show"]
    assert calls[1][2] == "origin/main:backend/talentlens/__init__.py"
    assert st.latest == "0.0.1" and st.update_required is False and st.can_update is True


def test_launch_starts_the_platform_script_detached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(updates, "_git", lambda: "git")
    started: list[dict] = []

    class FakePopen:
        def __init__(self, cmd: list[str], **kw: object) -> None:
            started.append({"cmd": cmd, **kw})

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    s = _settings(tmp_path, port=8799)
    up = Updater(s, root=tmp_path)
    up.status.latest = "9.9.9"
    up.launch()
    cmd = " ".join(started[0]["cmd"])
    assert ("update.ps1" in cmd) or ("update.sh" in cmd)
    assert "8799" in cmd and str(up.run_file) in cmd
    run = json.loads(up.run_file.read_text(encoding="utf-8"))
    assert run["state"] == "starting" and run["to"] == "9.9.9" and run["from"] == __version__
    assert up.snapshot()["last_run"]["state"] == "starting"


def test_launch_refuses_without_git(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="wasn't installed with git"):
        Updater(_settings(tmp_path), root=tmp_path).launch()


def test_update_api(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    st = client.get("/api/update").json()
    assert st["current"] == __version__ and st["update_required"] is False
    # an install that can't update itself gets a clear 400, never a crash
    up: Updater = client.app.state.updater  # type: ignore[attr-defined]
    monkeypatch.setattr(up.status, "can_update", False)
    r = client.post("/api/update")
    assert r.status_code == 400 and "git" in r.json()["detail"]


def test_update_scripts_exist_and_roll_back() -> None:
    ps1 = (REPO_ROOT / "scripts" / "update.ps1").read_text(encoding="utf-8")
    sh = (REPO_ROOT / "scripts" / "macos" / "update.sh").read_text(encoding="utf-8")
    for text in (ps1, sh):
        assert "--ff-only" in text  # never rewrites the user's history
        assert "reset --keep" in text  # rollback keeps any local edits
        assert "dist-next" in text  # UI is built aside, so a failed build leaves the old one
        assert "start" in text  # the app always comes back
