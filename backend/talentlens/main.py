"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import connections as connections_api
from .api import cvs as cvs_api
from .api import index as index_api
from .api import jd as jd_api
from .api import search as search_api
from .api import system as system_api
from .config import REPO_ROOT, Settings, get_settings
from .enrich import Enricher
from .library import FolderProblem
from .state import AppState, NoLibrary

log = logging.getLogger("talentlens")
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


def _setup_logging(settings: Settings) -> None:
    root = logging.getLogger()
    if any(getattr(h, "_talentlens", False) for h in root.handlers):
        return
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        settings.log_dir / "talentlens.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    handler._talentlens = True  # type: ignore[attr-defined]
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def create_app(settings: Settings | None = None, enricher: Enricher | None = None) -> FastAPI:
    settings = settings or get_settings()
    _setup_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        state: AppState = app.state.tl
        state.start()
        log.info(
            "TalentLens %s started; resume folder=%s (%s)",
            __version__,
            state.library.folder if state.library else None,
            state.cv_dir_source,
        )
        try:
            yield
        finally:
            state.stop()

    app = FastAPI(
        title="TalentLens",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.tl = AppState.build(settings, enricher)
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    @app.exception_handler(NoLibrary)
    async def _no_library(_req: Request, exc: NoLibrary) -> JSONResponse:
        return JSONResponse({"detail": str(exc), "code": "no_folder"}, status_code=409)

    @app.exception_handler(FolderProblem)
    async def _folder_problem(_req: Request, exc: FolderProblem) -> JSONResponse:
        return JSONResponse({"detail": str(exc), "code": "bad_folder"}, status_code=400)

    @app.get("/api/health", tags=["meta"])
    def health() -> dict[str, Any]:
        st: AppState = app.state.tl
        lib = st.library
        return {
            "status": "ok",
            "version": __version__,
            "cv_dir": str(lib.folder) if lib else None,
            "cv_dir_exists": bool(lib and lib.store.exists()),
            "needs_setup": lib is None,
            "llm": st.llm.status(),
            "embed_model": st.embedder.model_name,
        }

    app.include_router(cvs_api.router)
    app.include_router(index_api.router)
    app.include_router(search_api.router)
    app.include_router(jd_api.router)
    app.include_router(system_api.router)
    app.include_router(connections_api.router)

    _mount_frontend(app, FRONTEND_DIST)
    return app


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    if not (dist / "index.html").is_file():
        return
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
    index_html = dist / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index_html, headers={"Cache-Control": "no-cache"})
