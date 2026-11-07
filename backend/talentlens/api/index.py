from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from ..state import AppState
from . import get_state

router = APIRouter(prefix="/api/index", tags=["index"])
State = Annotated[AppState, Depends(get_state)]

NO_FOLDER: dict[str, Any] = {
    "state": "no_folder",
    "kind": None,
    "reason": None,
    "total": 0,
    "done": 0,
    "current": "",
    "started_at": None,
    "finished_at": None,
    "last_report": None,
    "version": 0,
    "errors": [],
    "ai_pending": 0,
    "ai_paused": False,
    "counts": {"total": 0},
    "ai_done": 0,
    "ai_total": 0,
    "last_index_at": None,
}


def _counts(st: AppState) -> tuple[dict[str, int], int]:
    with st.db.connect() as conn:
        rows = conn.execute("SELECT status, COUNT(*) AS n FROM cvs GROUP BY status").fetchall()
        ai_done = conn.execute(
            "SELECT COUNT(*) FROM cvs WHERE status='indexed' AND "
            "(llm_sha = sha256 OR confident = 1)"
        ).fetchone()[0]
    counts = {r["status"]: r["n"] for r in rows}
    counts["total"] = sum(counts.values())
    return counts, ai_done


def status_payload(st: AppState) -> dict[str, Any]:
    if st.library is None:
        return dict(NO_FOLDER)
    s = asdict(st.queue.status())
    counts, ai_done = _counts(st)
    s["counts"] = counts
    # overall smart-reading progress (never resets per pass)
    s["ai_total"] = counts.get("indexed", 0)
    s["ai_done"] = ai_done
    s["ai_paused"] = bool(st.prefs.get("ai_paused"))
    s["last_index_at"] = st.db.get_meta("last_index_at")
    return s


@router.get("/status")
def index_status(st: State) -> dict[str, Any]:
    return status_payload(st)


@router.post("/refresh", status_code=202)
def refresh(st: State, full: bool = False) -> dict[str, Any]:
    st.queue.request(full=full, reason="full refresh" if full else "refresh")
    return status_payload(st)


@router.post("/ai")
def set_ai(st: State, paused: bool) -> dict[str, Any]:
    """Pause or resume background smart reading (remembered across restarts)."""
    st.prefs.update(ai_paused=paused)
    st.queue.set_ai_paused(paused)
    return status_payload(st)


@router.get("/events")
async def events(request: Request, st: State) -> StreamingResponse:
    """Server-Sent Events stream of index status (each change, plus a 15 s heartbeat)."""

    async def gen():
        last: str | None = None
        version = -1
        queue = None
        while not await request.is_disconnected():
            lib = st.library
            if lib is None:
                await asyncio.sleep(2)
            else:
                if lib.queue is not queue:  # folder switched: follow the new library
                    queue, version = lib.queue, -1
                await asyncio.to_thread(queue.wait_version, version, 15.0)
                version = queue.status().version
            payload = json.dumps(status_payload(st))
            if payload != last:
                last = payload
                yield f"event: status\ndata: {payload}\n\n"
            else:
                yield ": keep-alive\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
