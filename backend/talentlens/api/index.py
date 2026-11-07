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


def _counts(st: AppState) -> dict[str, int]:
    with st.db.connect() as conn:
        rows = conn.execute("SELECT status, COUNT(*) AS n FROM cvs GROUP BY status").fetchall()
    counts = {r["status"]: r["n"] for r in rows}
    counts["total"] = sum(counts.values())
    return counts


def status_payload(st: AppState) -> dict[str, Any]:
    s = asdict(st.queue.status())
    s["counts"] = _counts(st)
    s["last_index_at"] = st.db.get_meta("last_index_at")
    return s


@router.get("/status")
def index_status(st: State) -> dict[str, Any]:
    return status_payload(st)


@router.post("/refresh", status_code=202)
def refresh(st: State, full: bool = False) -> dict[str, Any]:
    st.queue.request(full=full, reason="full refresh" if full else "refresh")
    return status_payload(st)


@router.get("/events")
async def events(request: Request, st: State) -> StreamingResponse:
    """Server-Sent Events stream of index status (each change, plus a 15 s heartbeat)."""

    async def gen():
        version = -1
        while not await request.is_disconnected():
            status = await asyncio.to_thread(st.queue.wait_version, version, 15.0)
            if status.version != version:
                version = status.version
                payload = status_payload(st)
                yield f"event: status\ndata: {json.dumps(payload)}\n\n"
            else:
                yield ": keep-alive\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
