from __future__ import annotations

import mimetypes
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from ..db import loads_list
from ..serializers import SUMMARY_COLUMNS, cv_summary
from ..state import AppState
from ..storage import DuplicateUpload, UploadRejected
from . import get_state

router = APIRouter(prefix="/api/cvs", tags=["cvs"])
State = Annotated[AppState, Depends(get_state)]

MAX_FILES_PER_UPLOAD = 50


@router.get("")
def list_cvs(
    st: State,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    with st.db.connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM cvs").fetchone()[0]
        rows = conn.execute(
            f"SELECT {SUMMARY_COLUMNS} FROM cvs ORDER BY added_at DESC, id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return {"total": total, "items": [cv_summary(r) for r in rows]}


@router.get("/{cv_id}")
def get_cv(cv_id: int, st: State) -> dict[str, Any]:
    with st.db.connect() as conn:
        row = conn.execute(
            f"SELECT {SUMMARY_COLUMNS}, sha256, size, text, education, parser FROM cvs WHERE id=?",
            (cv_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Resume not found")
    out = cv_summary(row)
    out.update(
        size=row["size"],
        sha256=row["sha256"],
        text=row["text"] or "",
        education=loads_list(row["education"]),
        parser=row["parser"],
        provenance=st.provenance.lookup(row["filename"], row["sha256"]),
    )
    return out


@router.get("/{cv_id}/file")
def get_cv_file(cv_id: int, st: State, download: bool = False) -> FileResponse:
    with st.db.connect() as conn:
        row = conn.execute("SELECT rel_path, filename FROM cvs WHERE id=?", (cv_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Resume not found")
    try:
        path = st.store.resolve_rel(row["rel_path"])
    except UploadRejected as e:
        raise HTTPException(400, str(e)) from e
    if not path.is_file():
        raise HTTPException(404, "File is no longer on disk; refresh the index")
    media = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(
        path,
        media_type=media,
        filename=row["filename"],
        content_disposition_type="attachment" if download else "inline",
    )


@router.post("")
async def upload_cvs(
    st: State, files: Annotated[list[UploadFile], File(description="Resumes (PDF/DOCX/DOC)")]
) -> dict[str, Any]:
    if not files:
        raise HTTPException(400, "No files were sent")
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise HTTPException(400, f"Upload at most {MAX_FILES_PER_UPLOAD} files at a time")

    with st.db.connect() as conn:
        known = {
            r["sha256"]: r["rel_path"] for r in conn.execute("SELECT sha256, rel_path FROM cvs")
        }

    max_bytes = st.settings.max_upload_bytes
    results: list[dict[str, Any]] = []
    added = 0
    for up in files:
        name = up.filename or "resume"
        data = await up.read(max_bytes + 1)
        await up.close()
        try:
            path, digest = st.store.save_upload(name, data, max_bytes=max_bytes, known_hashes=known)
        except DuplicateUpload as e:
            results.append(
                {
                    "filename": name,
                    "status": "duplicate",
                    "message": str(e),
                    "existing": e.existing_rel_path,
                }
            )
            continue
        except UploadRejected as e:
            results.append({"filename": name, "status": "rejected", "message": str(e)})
            continue
        known[digest] = path.name
        added += 1
        results.append(
            {
                "filename": name,
                "status": "added",
                "saved_as": path.name,
                "message": "Added. Indexing now.",
            }
        )
    if added:
        st.queue.request(reason="upload")
    return {"added": added, "results": results}
