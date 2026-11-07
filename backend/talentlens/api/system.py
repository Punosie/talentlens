"""Settings people change in the app, plus small OS helpers (native folder picker, reveal)."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from .. import __version__
from ..library import FolderProblem, count_resumes, validate_folder
from ..state import AppState
from . import get_state

router = APIRouter(prefix="/api", tags=["settings"])
State = Annotated[AppState, Depends(get_state)]

AI_MODELS = [
    {"id": "qwen2.5:1.5b-instruct", "label": "Faster", "hint": "Quick, good for most resumes"},
    {
        "id": "qwen2.5:3b-instruct",
        "label": "Better",
        "hint": "More accurate, slower on older laptops",
    },
]


class SettingsUpdate(BaseModel):
    cv_dir: str | None = Field(default=None, max_length=1000)
    ai_enabled: bool | None = None
    ollama_model: str | None = Field(default=None, max_length=100)
    onboarded: bool | None = None


class FolderCheck(BaseModel):
    path: str = Field(min_length=1, max_length=1000)


def settings_payload(st: AppState) -> dict[str, Any]:
    lib = st.library
    folder = lib.folder if lib else None
    return {
        "version": __version__,
        "platform": "mac"
        if sys.platform == "darwin"
        else "windows"
        if os.name == "nt"
        else "linux",
        "cv_dir": str(folder) if folder else None,
        "cv_dir_source": st.cv_dir_source,
        "cv_dir_locked": st.settings.cv_dir_locked,
        "cv_dir_exists": bool(folder and folder.is_dir()),
        "provenance_csv": str(lib.provenance.csv_path) if lib and lib.provenance.csv_path else None,
        "data_dir": str(st.settings.data_dir),
        "onboarded": bool(st.prefs.get("onboarded")),
        "ai": {
            "enabled": bool(st.prefs.get("ai_enabled")),
            "locked": st.settings.llm_locked,
            "paused": bool(st.prefs.get("ai_paused")),
            "model": getattr(st.llm, "model", None),
            "models": AI_MODELS,
            **st.llm.status(),
        },
    }


@router.get("/settings")
def get_settings(st: State) -> dict[str, Any]:
    return settings_payload(st)


@router.put("/settings")
async def update_settings(st: State, body: SettingsUpdate) -> dict[str, Any]:
    if body.cv_dir is not None:
        try:
            await run_in_threadpool(st.switch_folder, Path(body.cv_dir))
        except FolderProblem as e:
            raise HTTPException(400, str(e)) from e
    if body.ai_enabled is not None or body.ollama_model is not None:
        if body.ollama_model and body.ollama_model not in {m["id"] for m in AI_MODELS}:
            raise HTTPException(400, "Unknown AI model")
        st.set_ai(enabled=body.ai_enabled, model=body.ollama_model)
    if body.onboarded is not None:
        st.prefs.update(onboarded=body.onboarded)
    return settings_payload(st)


@router.post("/settings/check-folder")
async def check_folder(st: State, body: FolderCheck) -> dict[str, Any]:
    """Live check for the folder picker: does it exist and how many resumes are inside?"""
    try:
        folder = validate_folder(Path(body.path), st.settings)
    except FolderProblem as e:
        return {"ok": False, "message": str(e), "count": 0}
    n = await run_in_threadpool(count_resumes, folder)
    msg = (
        f"Found {n} resume{'s' if n != 1 else ''} (PDF, Word)."
        if n
        else "No resumes here yet. That's fine: you can add them after choosing this folder."
    )
    return {"ok": True, "path": str(folder), "count": n, "message": msg}


# --- OS helpers ----------------------------------------------------------------
_WIN_PICKER = r"""
Add-Type -AssemblyName System.Windows.Forms
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$owner = New-Object System.Windows.Forms.Form -Property @{TopMost = $true; ShowInTaskbar = $false}
$d = New-Object System.Windows.Forms.FolderBrowserDialog
$d.Description = 'Choose the folder that holds your resumes'
$d.ShowNewFolderButton = $true
if ($d.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {
    [Console]::Out.Write($d.SelectedPath)
}
"""


def _pick_folder() -> str | None:
    if os.name == "nt":
        cmd = ["powershell.exe", "-NoProfile", "-STA", "-NonInteractive", "-Command", _WIN_PICKER]
    elif sys.platform == "darwin":
        cmd = [
            "osascript",
            "-e",
            'POSIX path of (choose folder with prompt "Choose the folder that holds your resumes")',
        ]
    else:
        cmd = ["zenity", "--file-selection", "--directory", "--title=Choose your resume folder"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=600, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise HTTPException(
            501, f"The folder picker isn't available here ({e}). Type the path instead."
        ) from e
    out = r.stdout.decode("utf-8", errors="replace").strip()
    if r.returncode != 0 or not out:
        return None  # cancelled
    return out


@router.post("/system/pick-folder")
async def pick_folder() -> dict[str, Any]:
    """Open the operating system's own folder dialog on this computer."""
    path = await run_in_threadpool(_pick_folder)
    return {"path": path, "cancelled": path is None}


@router.post("/system/reveal")
def reveal(st: State) -> dict[str, Any]:
    """Show the resume folder in Explorer / Finder."""
    folder = st.lib().folder
    if os.name == "nt":
        subprocess.Popen(["explorer.exe", str(folder)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])
    return {"ok": True, "os": platform.system()}
