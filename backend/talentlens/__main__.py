"""TalentLens command line.

uv run talentlens                 start the server (what the desktop shortcut / app does)
uv run talentlens open            start it if needed, then open the browser
uv run talentlens set-folder PATH remember the resume folder (same as choosing it in the app)
uv run talentlens set-model ID    choose the local AI model (e.g. qwen2.5:1.5b-instruct)
uv run talentlens set-ai on|off   turn the local AI on or off
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import httpx

from .config import get_settings


def _serve() -> None:
    import uvicorn

    s = get_settings()
    uvicorn.run(
        "talentlens.main:create_app",
        factory=True,
        host=s.host,
        port=s.port,
        log_level="info",
        access_log=False,
    )


def _url() -> str:
    s = get_settings()
    return f"http://127.0.0.1:{s.port}"


def _up(url: str) -> bool:
    try:
        return httpx.get(f"{url}/api/health", timeout=2).json().get("status") == "ok"
    except (httpx.HTTPError, ValueError):
        return False


def _open() -> int:
    url = _url()
    if not _up(url):
        log_dir = get_settings().log_dir
        log_dir.mkdir(parents=True, exist_ok=True)
        out = open(log_dir / "server.out.log", "ab")  # noqa: SIM115
        flags = {}
        if sys.platform == "win32":
            flags["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
        else:
            flags["start_new_session"] = True
        subprocess.Popen([sys.executable, "-m", "talentlens"], stdout=out, stderr=out, **flags)
        deadline = time.monotonic() + 120
        while not _up(url):
            if time.monotonic() > deadline:
                print(f"TalentLens did not start; see logs in {log_dir}", file=sys.stderr)
                return 1
            time.sleep(0.7)
    webbrowser.open(url)
    return 0


def _set_folder(path: str) -> int:
    from .library import FolderProblem, validate_folder
    from .settings_store import SettingsStore

    s = get_settings()
    s.ensure_dirs()
    try:
        folder = validate_folder(Path(path), s)
    except FolderProblem as e:
        print(e, file=sys.stderr)
        return 1
    SettingsStore(s.settings_path).update(cv_dir=str(folder))
    print(f"Resume folder set to {folder}")
    if s.cv_dir_locked:
        print("Note: TALENTLENS_CV_DIR in .env overrides this until it is removed there.")
    return 0


def _set_model(model: str) -> int:
    from .settings_store import SettingsStore

    s = get_settings()
    s.ensure_dirs()
    SettingsStore(s.settings_path).update(ollama_model=model)
    print(f"AI model set to {model}")
    return 0


def _set_ai(value: str) -> int:
    from .settings_store import SettingsStore

    s = get_settings()
    s.ensure_dirs()
    on = value.lower() in {"on", "true", "1", "yes"}
    SettingsStore(s.settings_path).update(ai_enabled=on)
    print(f"Local AI {'enabled' if on else 'disabled (rules only)'}")
    return 0


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="talentlens", description="Local resume library")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("serve", help="start the server (default)")
    sub.add_parser("open", help="start if needed and open the browser")
    f = sub.add_parser("set-folder", help="remember the resume folder")
    f.add_argument("path")
    m = sub.add_parser("set-model", help="choose the local AI model")
    m.add_argument("model")
    a = sub.add_parser("set-ai", help="turn the local AI on or off")
    a.add_argument("value", choices=["on", "off"])
    args = ap.parse_args(argv)
    if args.cmd == "set-ai":
        sys.exit(_set_ai(args.value))
    if args.cmd == "open":
        sys.exit(_open())
    if args.cmd == "set-folder":
        sys.exit(_set_folder(args.path))
    if args.cmd == "set-model":
        sys.exit(_set_model(args.model))
    _serve()


if __name__ == "__main__":
    main()
