"""Forced updates: compare this install with GitHub and run the one-click updater.

A release is a version bump on the update branch (pyproject.toml + talentlens/__init__.py). When
the branch carries a higher version than the running app, the UI blocks with "Update now". The
click starts scripts/update.ps1 (Windows) or scripts/macos/update.sh in a separate process: it
stops the server, pulls, syncs dependencies, builds the UI aside, swaps it in and restarts. Any
failure rolls the code back to the previous commit and restarts the old version.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from . import __version__
from .config import REPO_ROOT, Settings

log = logging.getLogger(__name__)

VERSION_FILE = "backend/talentlens/__init__.py"
_VERSION_RE = re.compile(r"""__version__\s*=\s*["']([^"']+)["']""")


def parse_version(v: str) -> tuple[int, ...]:
    """'0.10.2' -> (0, 10, 2). Non-numeric parts (rc1, dev) count as 0, so they never win."""
    out = []
    for part in v.strip().lstrip("v").split("."):
        m = re.match(r"\d+", part)
        out.append(int(m.group()) if m else 0)
    return tuple(out)


def is_newer(remote: str, local: str) -> bool:
    return parse_version(remote) > parse_version(local)


def _git() -> str | None:
    return shutil.which("git")


def is_git_checkout(root: Path = REPO_ROOT) -> bool:
    return (root / ".git").exists() and _git() is not None


def remote_version(settings: Settings, root: Path = REPO_ROOT) -> str:
    """The version on the update branch. A git checkout fetches with the user's own GitHub sign-in
    (works for a private repo); otherwise the public raw file is read."""
    errors = []
    if is_git_checkout(root):
        git = _git()
        assert git
        no_window = {"creationflags": 0x08000000} if os.name == "nt" else {}  # CREATE_NO_WINDOW
        try:
            subprocess.run(
                [git, "fetch", "--quiet", "origin", settings.update_branch],
                cwd=root,
                capture_output=True,
                timeout=60,
                check=True,
                **no_window,
            )
            text = subprocess.run(
                [git, "show", f"origin/{settings.update_branch}:{VERSION_FILE}"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=20,
                check=True,
                **no_window,
            ).stdout
            m = _VERSION_RE.search(text)
            if m:
                return m.group(1)
            errors.append("version not found in the fetched file")
        except (OSError, subprocess.SubprocessError) as e:
            errors.append(f"git: {e.__class__.__name__}")
    url = (
        f"https://raw.githubusercontent.com/{settings.update_repo}/"
        f"{settings.update_branch}/{VERSION_FILE}"
    )
    try:
        r = httpx.get(url, timeout=10, follow_redirects=True)
        r.raise_for_status()
        m = _VERSION_RE.search(r.text)
        if m:
            return m.group(1)
        errors.append("version not found online")
    except httpx.HTTPError as e:
        errors.append(f"https: {e.__class__.__name__}")
    raise RuntimeError("; ".join(errors))


@dataclass
class UpdateStatus:
    current: str = __version__
    latest: str | None = None
    update_required: bool = False
    checked_at: str | None = None
    error: str | None = None
    can_update: bool = False  # this install can update itself (a git checkout)
    # last run of the updater script (written by the script into <data_dir>/update/status.json)
    last_run: dict[str, Any] | None = field(default=None)


class Updater:
    def __init__(self, settings: Settings, root: Path = REPO_ROOT) -> None:
        self.settings = settings
        self.root = root
        self.status = UpdateStatus(can_update=is_git_checkout(root))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def run_file(self) -> Path:
        return self.settings.data_dir / "update" / "status.json"

    def check(self) -> UpdateStatus:
        try:
            latest = remote_version(self.settings, self.root)
            self.status.latest = latest
            self.status.update_required = is_newer(latest, __version__)
            self.status.error = None
        except RuntimeError as e:  # offline or GitHub unreachable: never block the app for it
            self.status.error = f"Couldn't check for updates ({e})"
            log.info("Update check failed: %s", e)
        self.status.checked_at = datetime.now(UTC).isoformat(timespec="seconds")
        return self.status

    def snapshot(self) -> dict[str, Any]:
        try:
            # utf-8-sig: tolerate a byte-order mark if a script ever writes one
            self.status.last_run = json.loads(self.run_file.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            self.status.last_run = None
        return asdict(self.status)

    def start(self) -> None:
        if not self.settings.update_check:
            return

        def loop() -> None:
            if self._stop.wait(5):  # let the app finish starting first
                return
            while True:
                self.check()
                if self._stop.wait(max(0.25, self.settings.update_check_hours) * 3600):
                    return

        self._thread = threading.Thread(target=loop, name="talentlens-updates", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def launch(self) -> None:
        """Start the updater script in its own process (it outlives this server)."""
        if not self.status.can_update:
            raise RuntimeError(
                "This copy of TalentLens wasn't installed with git, so it can't update itself. "
                "Download the latest version and run the setup again."
            )
        self.run_file.parent.mkdir(parents=True, exist_ok=True)
        started = {
            "state": "starting",
            "from": __version__,
            "to": self.status.latest,
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        self.run_file.write_text(json.dumps(started), encoding="utf-8")
        log_path = self.settings.log_dir / "update.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        args = [
            "--port",
            str(self.settings.port),
            "--status",
            str(self.run_file),
            "--branch",
            self.settings.update_branch,
        ]
        if os.name == "nt":
            script = self.root / "scripts" / "update.ps1"
            cmd = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-File",
                str(script),
                "-Port",
                args[1],
                "-StatusFile",
                args[3],
                "-Branch",
                args[5],
            ]
            flags = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED | NEW_GROUP | NO_WINDOW
            with log_path.open("ab") as out:
                subprocess.Popen(
                    cmd,
                    cwd=self.root,
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    creationflags=flags,
                    close_fds=True,
                )
        else:
            script = self.root / "scripts" / "macos" / "update.sh"
            with log_path.open("ab") as out:
                subprocess.Popen(
                    ["/bin/bash", str(script), *args],
                    cwd=self.root,
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                    close_fds=True,
                )
        log.info("Updater started: %s -> %s", __version__, self.status.latest)
