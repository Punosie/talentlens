"""Connections database (MongoDB) sync: status and "sync now"."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from ..state import AppState, FolderProblem
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


class JoinBody(BaseModel):
    invite: str = Field(min_length=10, max_length=500)


def _same_origin(request: Request) -> bool:
    """Joining a team must come from TalentLens's own page (a click on 'Connect'), never
    from another website silently pointing this computer at a foreign server."""
    origin = request.headers.get("origin")
    return bool(origin) and origin.rstrip("/") == str(request.base_url).rstrip("/")


@router.post("/join")
async def join(st: State, body: JoinBody, request: Request) -> dict[str, Any]:
    if not _same_origin(request):
        raise HTTPException(403, "Open TalentLens and paste the invite link there.")
    try:
        team = await run_in_threadpool(st.join_team, body.invite)
    except FolderProblem as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, **team}


@router.post("/leave")
async def leave(st: State, request: Request) -> dict[str, Any]:
    if not _same_origin(request):
        raise HTTPException(403, "Forbidden")
    await run_in_threadpool(st.leave_team)
    return {"ok": True}
