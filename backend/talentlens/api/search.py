from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query

from ..search import Filters
from ..state import AppState
from . import get_state

router = APIRouter(prefix="/api", tags=["search"])
State = Annotated[AppState, Depends(get_state)]


@router.get("/search")
def search(
    st: State,
    q: Annotated[str | None, Query(max_length=500)] = None,
    skills: Annotated[list[str] | None, Query()] = None,
    skills_mode: Literal["all", "any"] = "all",
    years_min: Annotated[float | None, Query(ge=0, le=60)] = None,
    years_max: Annotated[float | None, Query(ge=0, le=60)] = None,
    location: Annotated[list[str] | None, Query()] = None,
    domain: Annotated[list[str] | None, Query()] = None,
    ext: Annotated[list[str] | None, Query()] = None,
    include_unreadable: bool = False,
    sort: Literal["relevance", "recent", "experience", "name"] = "relevance",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    filters = Filters(
        skills=skills or [],
        skills_mode=skills_mode,
        years_min=years_min,
        years_max=years_max,
        locations=location or [],
        domains=domain or [],
        exts=ext or [],
        include_unreadable=include_unreadable,
    )
    return st.search.search(q, filters, sort=sort, limit=limit, offset=offset)


@router.get("/facets")
def facets(st: State) -> dict[str, Any]:
    return st.search.facets()
