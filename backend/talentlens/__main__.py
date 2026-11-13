"""TalentLens command line.

uv run talentlens                 start the server (what the desktop shortcut / app does)
uv run talentlens open            start it if needed, then open the browser
uv run talentlens set-folder PATH remember the resume folder (same as choosing it in the app)
uv run talentlens set-model ID    choose the local AI model (e.g. qwen2.5:1.5b-instruct)
uv run talentlens set-ai on|off   turn the local AI on or off
uv run talentlens benchmark       measure CPU vs GPU and use the faster
uv run talentlens join LINK       connect to your team with an invite link
uv run talentlens set-device auto|cpu|cuda
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


def _benchmark() -> int:
    """Measure CPU (and NVIDIA GPU, if present) on real embedding work; save the faster."""
    from .ai.device import PROFILES, benchmark
    from .settings_store import SettingsStore

    s = get_settings()
    s.ensure_dirs()
    print("Measuring how fast this computer reads resumes and profiles...")
    r = benchmark(s.model_cache_dir)
    cpu, gpu = r.get("cpu_per_s"), r.get("cuda_per_s")
    print(f"  CPU: {cpu or 'failed'} per second ({PROFILES['cpu'].model})")
    if gpu or r.get("cuda_error"):
        print(f"  GPU: {gpu or 'failed'} per second ({r.get('gpu_name') or 'NVIDIA'})")
    else:
        print("  GPU: none found (that's fine)")
    SettingsStore(s.settings_path).update(device=r["choice"], device_benchmark=r)
    print(f"Using the {'GPU' if r['choice'] == 'cuda' else 'CPU'}. Saved in TalentLens settings.")
    return 0


def _join(link: str) -> int:
    """Connect to a team from an invite link (same as pasting it in Settings)."""
    from .connections import redeem_invite
    from .settings_store import SettingsStore

    s = get_settings()
    s.ensure_dirs()
    try:
        t = redeem_invite(link)
    except Exception as e:
        print(f"Couldn't connect: {e}")
        return 1
    SettingsStore(s.settings_path).update(
        team_server=t["server"], team_token=t["token"], team_name=t["name"]
    )
    who = t["name"] or "you"
    print(f"Connected to {t['server']} as {who}. TalentLens will sync when it starts.")
    return 0


def _set_device(value: str) -> int:
    from .settings_store import SettingsStore

    s = get_settings()
    s.ensure_dirs()
    SettingsStore(s.settings_path).update(device=None if value == "auto" else value)
    print(f"Device set to {value} (takes effect next time TalentLens starts)")
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
    sub.add_parser("benchmark", help="measure CPU vs GPU and save the faster")
    j = sub.add_parser("join", help="connect to your team with an invite link")
    j.add_argument("link")
    d = sub.add_parser("set-device", help="run the models on the cpu, the cuda GPU, or auto")
    d.add_argument("value", choices=["auto", "cpu", "cuda"])
    args = ap.parse_args(argv)
    if args.cmd == "join":
        sys.exit(_join(args.link))
    if args.cmd == "benchmark":
        sys.exit(_benchmark())
    if args.cmd == "set-device":
        sys.exit(_set_device(args.value))
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
