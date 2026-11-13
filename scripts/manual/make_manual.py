"""Build the TalentLens setup manual: a captioned video and a PDF booklet, from fictional data only.

    uv run python scripts/manual/make_manual.py            # everything
    uv run python scripts/manual/make_manual.py --no-video # booklet only (reuses screenshots)

What it does:
  1. Creates a throwaway TalentLens profile (fresh data folder, demo resumes) in a temp folder.
  2. Starts TalentLens on 127.0.0.1:8765 (the port invite pages link to) and a mock team server
     (scripts/manual/mock_team.py) on 127.0.0.1:8790 that serves invented LinkedIn connections.
  3. Runs scripts/manual/record.mjs (Playwright): records the walkthrough with on-screen captions
     and saves a screenshot per step.
  4. Converts the recording to MP4 (ffmpeg from imageio-ffmpeg) and builds the PDF (booklet.mjs).

Outputs go to docs/manual/. Port 8765 must be free (close TalentLens first). Needs Ollama running
for the "Match to a job" scenes, and Playwright's Chromium:
    npx --prefix frontend playwright install chromium
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs" / "manual"
HERE = Path(__file__).resolve().parent
APP_PORT, TEAM_PORT = 8765, 8790

NEW_RESUME = """Noah Example
Senior Data Engineer | Hyderabad, India | noah.example@example.com
9 years of experience with Python, SQL, Apache Spark, Airflow, Kafka and AWS
for payments and lending platforms. dbt, Snowflake, Kubernetes."""


def prepare(root: Path) -> None:
    sys.path.insert(0, str(REPO / "backend"))
    from talentlens.config import Settings
    from tests.conftest import make_pdf
    from tests.demo_data import DEMO_RESUMES

    if root.exists():
        shutil.rmtree(root)
    resumes = root / "Resumes"
    resumes.mkdir(parents=True)
    for name, text in DEMO_RESUMES.items():
        make_pdf(resumes / name, text)
    (root / "new").mkdir()
    make_pdf(root / "new" / "Noah_Example_Resume.pdf", NEW_RESUME)

    appdata = root / "appdata"
    appdata.mkdir()
    real = Settings(_env_file=None)
    if real.model_cache_dir.is_dir():  # reuse downloaded AI models instead of fetching them again
        shutil.copytree(real.model_cache_dir, appdata / "models", dirs_exist_ok=True)
    seed = {}
    if real.settings_path.is_file():  # keep this computer's measured CPU/GPU choice, nothing else
        saved = json.loads(real.settings_path.read_text(encoding="utf-8"))
        seed = {k: saved[k] for k in ("device", "device_benchmark") if k in saved}
    (appdata / "settings.json").write_text(json.dumps(seed), encoding="utf-8")


def serve(root: Path) -> None:
    sys.path.insert(0, str(REPO / "backend"))
    import uvicorn

    from talentlens.config import Settings
    from talentlens.main import create_app

    settings = Settings(data_dir=root / "appdata", port=APP_PORT, discover=False, _env_file=None)
    uvicorn.run(create_app(settings), host="127.0.0.1", port=APP_PORT, log_level="warning")


def wait_for(url: str, timeout: float = 120) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=3):
                return
        except Exception:
            time.sleep(0.5)
    raise SystemExit(f"Timed out waiting for {url}")


def port_free(port: int) -> bool:
    import socket

    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def node(script: str, env: dict) -> None:
    subprocess.run(["node", str(HERE / script)], cwd=REPO, env={**os.environ, **env}, check=True)


def to_mp4(webm: Path, mp4: Path, cuts: list[list[float]]) -> None:
    ff = subprocess.run(
        [
            "uv",
            "run",
            "--no-project",
            "--with",
            "imageio-ffmpeg",
            "python",
            "-c",
            "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    keep = "+".join(f"between(t,{a},{b})" for a, b in cuts)
    vf = f"fps=25,select='not({keep})',setpts=N/25/TB" if cuts else "fps=25"
    subprocess.run(
        [
            ff,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(webm),
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "26",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-an",
            str(mp4),
        ],
        check=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="all", choices=["all", "serve"])
    ap.add_argument("--root")
    ap.add_argument(
        "--no-video", action="store_true", help="only rebuild the PDF from existing screenshots"
    )
    args = ap.parse_args()
    if args.cmd == "serve":
        serve(Path(args.root))
        return

    OUT.mkdir(parents=True, exist_ok=True)
    if not args.no_video:
        for p in (APP_PORT, TEAM_PORT):
            if not port_free(p):
                raise SystemExit(
                    f"Port {p} is in use. Close TalentLens (or whatever uses it) and try again."
                )
        # a neutral, user-agnostic path, because it appears on screen
        public = Path(os.environ.get("PUBLIC", "")) / "Documents"
        root = (public if public.is_dir() else Path(tempfile.gettempdir())) / "TalentLens Demo"
        prepare(root)
        procs = [
            subprocess.Popen(
                [sys.executable, str(HERE / "mock_team.py"), "--port", str(TEAM_PORT)], cwd=REPO
            ),
            subprocess.Popen(
                [sys.executable, str(Path(__file__)), "serve", "--root", str(root)], cwd=REPO
            ),
        ]
        try:
            wait_for(f"http://127.0.0.1:{TEAM_PORT}/join/x")
            wait_for(f"http://127.0.0.1:{APP_PORT}/api/settings")
            work = root / "video"
            node(
                "record.mjs",
                {
                    "MANUAL_OUT": str(OUT),
                    "MANUAL_WORK": str(work),
                    "MANUAL_RESUMES": str(root / "Resumes"),
                    "MANUAL_NEW_RESUME": str(root / "new" / "Noah_Example_Resume.pdf"),
                },
            )
        finally:
            for p in procs:
                p.terminate()
            for p in procs:
                p.wait(10)
        cuts = json.loads((work / "cuts.json").read_text())
        to_mp4(work / "walkthrough.webm", OUT / "TalentLens-Setup-Video.mp4", cuts)
        print("video:", OUT / "TalentLens-Setup-Video.mp4")
    node("booklet.mjs", {"MANUAL_OUT": str(OUT)})
    print("booklet:", OUT / "TalentLens-Setup-Guide.pdf")


if __name__ == "__main__":
    main()
