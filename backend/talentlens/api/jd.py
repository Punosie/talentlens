from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..ai.llm import LLMUnavailable
from ..config import JD_EXTENSIONS
from ..jd import Requirements, parse_llm, parse_rules
from ..parsing import ParseError, parse_bytes
from ..search import Filters
from ..shortlist import Shortlister, explain_stream
from ..state import AppState
from ..storage import safe_filename, sniff_matches
from . import get_state

router = APIRouter(prefix="/api", tags=["shortlist"])
State = Annotated[AppState, Depends(get_state)]

MAX_JD_TEXT = 60_000


class RequirementsModel(BaseModel):
    title: str | None = None
    must_have_skills: list[str] = Field(default_factory=list, max_length=30)
    nice_to_have_skills: list[str] = Field(default_factory=list, max_length=30)
    min_years: float | None = Field(default=None, ge=0, le=50)
    max_years: float | None = Field(default=None, ge=0, le=50)
    locations: list[str] = Field(default_factory=list, max_length=10)
    domains: list[str] = Field(default_factory=list, max_length=10)
    summary: str | None = None
    source: str = "user"

    def to_req(self) -> Requirements:
        return Requirements.from_dict(self.model_dump())


class ResultFilters(BaseModel):
    """Hard filters on who is ranked (the requirements still decide the order)."""

    locations: list[str] = Field(default_factory=list, max_length=20)
    years_min: float | None = Field(default=None, ge=0, le=60)
    years_max: float | None = Field(default=None, ge=0, le=60)
    skills: list[str] = Field(default_factory=list, max_length=30)
    skills_mode: Literal["all", "any"] = "all"
    domains: list[str] = Field(default_factory=list, max_length=20)

    def to_filters(self) -> Filters:
        return Filters(
            skills=self.skills,
            skills_mode=self.skills_mode,
            years_min=self.years_min,
            years_max=self.years_max,
            locations=self.locations,
            domains=self.domains,
        )


class ShortlistRequest(BaseModel):
    requirements: RequirementsModel
    jd_text: str = Field(default="", max_length=MAX_JD_TEXT)
    limit: int = Field(default=50, ge=1, le=200)
    rerank: bool = True
    sources: list[Literal["file", "linkedin"]] = Field(default_factory=list)
    owners: list[str] = Field(default_factory=list, max_length=20)
    filters: ResultFilters | None = None


class ExplainRequest(BaseModel):
    cv_id: int
    requirements: RequirementsModel


class SaveRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    jd_text: str = Field(default="", max_length=MAX_JD_TEXT)
    requirements: RequirementsModel
    results: list[dict[str, Any]] = Field(default_factory=list, max_length=500)


def _shortlister(st: AppState) -> Shortlister:
    sl = st.extras.get("shortlister")
    if sl is None:
        sl = Shortlister(st.db, st.search, st.reranker)
        st.extras["shortlister"] = sl
    return sl


@router.post("/jd/parse")
async def parse_jd(
    st: State,
    text: Annotated[str | None, Form(max_length=MAX_JD_TEXT)] = None,
    file: Annotated[UploadFile | None, File()] = None,
    mode: Annotated[Literal["rules", "ai"], Form()] = "rules",
) -> dict[str, Any]:
    """Extract requirements from a JD (file or pasted text).

    mode="rules" is instant. mode="ai" asks the local LLM (about 30-60 s on CPU) and falls back
    to the rules if the LLM is unavailable.
    """
    jd_text = (text or "").strip()
    if file is not None and file.filename:
        name = safe_filename(file.filename)
        ext = Path(name).suffix.lower()
        if ext not in JD_EXTENSIONS:
            raise HTTPException(
                400, f"Unsupported JD file type '{ext}'. Use PDF, DOCX, DOC or TXT."
            )
        data = await file.read(st.settings.max_upload_bytes + 1)
        if len(data) > st.settings.max_upload_bytes:
            raise HTTPException(400, "JD file is too large")
        if not sniff_matches(ext, data[:16]):
            raise HTTPException(400, f"File content is not a valid {ext[1:].upper()} document")
        try:
            parsed = await run_in_threadpool(parse_bytes, name, data)
        except ParseError as e:
            raise HTTPException(422, f"Could not read the JD: {e}") from e
        jd_text = parsed.text
    if len(jd_text) < 20:
        raise HTTPException(
            400, "Paste the job description or upload a file (at least a few lines)"
        )

    base = await run_in_threadpool(parse_rules, jd_text)
    warning = None
    req = base
    if mode == "ai":
        if st.llm.available():
            try:
                with st.queue.interactive():
                    req = await run_in_threadpool(parse_llm, st.llm, jd_text, base)
            except LLMUnavailable as e:
                warning = f"AI parsing failed ({e}); showing rule-based requirements."
        else:
            warning = "Local AI is not available; showing rule-based requirements."
    return {"jd_text": jd_text, "requirements": req.as_dict(), "warning": warning}


@router.post("/shortlist")
async def shortlist(st: State, body: ShortlistRequest) -> dict[str, Any]:
    """rerank=false: instant ranking (embeddings + skills). rerank=true: refine the top."""
    req = body.requirements.to_req()
    if not (req.must_have_skills or req.title or req.summary or body.jd_text.strip()):
        raise HTTPException(400, "Add at least one requirement or the JD text")
    result = await run_in_threadpool(
        _shortlister(st).rank,
        req,
        body.jd_text,
        limit=body.limit,
        rerank=body.rerank,
        sources=body.sources,
        owners=body.owners,
        filters=body.filters.to_filters() if body.filters else None,
    )
    # let background smart reading improve the people the user is looking at, first
    st.indexer.prioritize([i["id"] for i in result["items"][:20]])
    return result


@router.post("/shortlist/explain")
async def explain_match(st: State, body: ExplainRequest) -> StreamingResponse:
    """Streams a 3-line plain-text explanation (Verdict / Strengths / Gaps) as it is written."""
    if not st.llm.available():
        raise HTTPException(503, "Smart reading (local AI) is not available right now")
    with st.db.connect() as conn:
        row = conn.execute("SELECT text FROM cvs WHERE id=?", (body.cv_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Resume not found")
    req = body.requirements.to_req()
    queue = st.queue

    def gen() -> Iterator[bytes]:
        try:
            with queue.interactive():
                for piece in explain_stream(st.llm, req, row["text"] or ""):
                    yield piece.encode("utf-8")
        except LLMUnavailable:
            yield b"\n[Smart reading stopped unexpectedly. Please try again.]"

    return StreamingResponse(
        gen(),
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- saved shortlists -----------------------------------------------------------
_CSV_COLS = [
    "rank",
    "score",
    "name",
    "title",
    "years_exp",
    "location",
    "email",
    "phone",
    "matched_must",
    "missing_must",
    "matched_nice",
    "domains",
    "filename",
]


def _csv(results: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(_CSV_COLS)
    for r in results:
        row = []
        for c in _CSV_COLS:
            v = r.get(c)
            if isinstance(v, list):
                v = "; ".join(map(str, v))
            v = "" if v is None else str(v)
            if v[:1] in ("=", "+", "-", "@"):  # neutralise spreadsheet formula injection
                v = "'" + v
            row.append(v)
        w.writerow(row)
    return buf.getvalue()


def content_disposition(filename: str) -> str:
    """RFC 6266 / 5987: ASCII fallback plus a UTF-8 encoded name for non-Latin characters."""
    ascii_name = filename.encode("ascii", "replace").decode().replace("?", "_").replace('"', "")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def _csv_response(results: list[dict[str, Any]], name: str) -> StreamingResponse:
    fname = safe_filename(f"{name}.csv")
    return StreamingResponse(
        iter(["﻿" + _csv(results)]),  # BOM so Excel opens UTF-8 correctly
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": content_disposition(fname)},
    )


@router.post("/shortlist/export")
def export_unsaved(body: SaveRequest) -> StreamingResponse:
    return _csv_response(body.results, body.name)


@router.post("/shortlists", status_code=201)
def save_shortlist(st: State, body: SaveRequest) -> dict[str, Any]:
    with st.db.write() as conn:
        cur = conn.execute(
            "INSERT INTO shortlists(name, jd_text, requirements, results) VALUES (?,?,?,?)",
            (
                body.name.strip(),
                body.jd_text,
                json.dumps(body.requirements.model_dump()),
                json.dumps(body.results),
            ),
        )
        sid = cur.lastrowid
    return {"id": sid, "name": body.name.strip()}


@router.get("/shortlists")
def list_shortlists(st: State) -> list[dict[str, Any]]:
    with st.db.connect() as conn:
        rows = conn.execute(
            "SELECT id, name, created_at, requirements, json_array_length(results) AS n "
            "FROM shortlists ORDER BY id DESC"
        ).fetchall()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "created_at": r["created_at"],
            "count": r["n"],
            "title": json.loads(r["requirements"]).get("title"),
        }
        for r in rows
    ]


def _get(st: AppState, sid: int) -> dict[str, Any]:
    with st.db.connect() as conn:
        r = conn.execute("SELECT * FROM shortlists WHERE id=?", (sid,)).fetchone()
    if r is None:
        raise HTTPException(404, "Shortlist not found")
    return {
        "id": r["id"],
        "name": r["name"],
        "created_at": r["created_at"],
        "jd_text": r["jd_text"],
        "requirements": json.loads(r["requirements"]),
        "results": json.loads(r["results"]),
    }


@router.get("/shortlists/{sid}")
def get_shortlist(st: State, sid: int) -> dict[str, Any]:
    return _get(st, sid)


@router.get("/shortlists/{sid}/export.csv")
def export_shortlist(st: State, sid: int) -> StreamingResponse:
    s = _get(st, sid)
    return _csv_response(s["results"], s["name"])


class RenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


@router.patch("/shortlists/{sid}")
def rename_shortlist(st: State, sid: int, body: RenameRequest) -> dict[str, Any]:
    with st.db.write() as conn:
        cur = conn.execute("UPDATE shortlists SET name=? WHERE id=?", (body.name.strip(), sid))
    if not cur.rowcount:
        raise HTTPException(404, "Shortlist not found")
    return {"id": sid, "name": body.name.strip()}


@router.delete("/shortlists/{sid}", status_code=204)
def delete_shortlist(st: State, sid: int) -> None:
    with st.db.write() as conn:
        cur = conn.execute("DELETE FROM shortlists WHERE id=?", (sid,))
    if not cur.rowcount:
        raise HTTPException(404, "Shortlist not found")
