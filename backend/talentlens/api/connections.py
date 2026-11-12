"""Connections database (MongoDB) sync: status and "sync now"."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from ..state import AppState
from . import get_state

router = APIRouter(prefix="/api/connections", tags=["connections"])
State = Annotated[AppState, Depends(get_state)]


def _status(st: AppState) -> dict[str, Any]:
    lib = st.library
    sync = lib.connections if lib else None
    if not sync:
        return {"configured": bool(st.mongodb_uri()), "state": "off"}
    return sync.snapshot()


@router.get("/status")
def status(st: State) -> dict[str, Any]:
    return _status(st)


@router.post("/sync", status_code=202)
def sync_now(st: State, full: bool = False) -> dict[str, Any]:
    """Queue a sync with MongoDB (pull LinkedIn profiles, push new resumes).
    full=true also removes profiles that were deleted from MongoDB."""
    lib = st.lib()
    if lib.connections:
        lib.connections.full_next = lib.connections.full_next or full
        lib.queue.request(reason="connections sync")
    return _status(st)
