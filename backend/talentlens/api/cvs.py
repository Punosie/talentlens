from __future__ import annotations

import mimetypes
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from ..bulk import ArchiveRejected, iter_zip
from ..db import loads_list
from ..serializers import SUMMARY_COLUMNS, cv_summary
from ..state import AppState
from ..storage import DuplicateUpload, UploadRejected
from . import get_state

router = APIRouter(prefix="/api/cvs", tags=["cvs"])
State = Annotated[AppState, Depends(get_state)]

MAX_FILES_PER_UPLOAD = 50  # the UI sends bigger imports in batches
MAX_ZIP_BYTES = 300 * 1024 * 1024


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


@router.get("/{cv_id:int}")
def get_cv(cv_id: int, st: State) -> dict[str, Any]:
    with st.db.connect() as conn:
        row = conn.execute(
            f"SELECT {SUMMARY_COLUMNS}, sha256, size, text, education, parser FROM cvs WHERE id=?",
            (cv_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Resume not found")
    st.indexer.prioritize([cv_id])  # opened by the user: improve it with smart reading next
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


@router.get("/{cv_id:int}/file")
def get_cv_file(cv_id: int, st: State, download: bool = False) -> FileResponse:
    with st.db.connect() as conn:
        row = conn.execute(
            "SELECT rel_path, filename, source FROM cvs WHERE id=?", (cv_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Resume not found")
    if row["source"] != "file":
        raise HTTPException(404, "This person comes from LinkedIn and has no resume file")
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


@router.get("/status")
def files_status(st: State, paths: Annotated[list[str], Query(max_length=200)]) -> dict[str, Any]:
    """Per-file progress for the upload panel: waiting / ready / unreadable."""
    with st.db.connect() as conn:
        marks = ",".join("?" * len(paths)) or "''"
        rows = {
            r["rel_path"]: r
            for r in conn.execute(
                f"SELECT id, rel_path, status, name FROM cvs WHERE rel_path IN ({marks})", paths
            )
        }
    out = {}
    for p in paths:
        r = rows.get(p)
        if r is None:
            out[p] = {"state": "reading"}
        elif r["status"] == "indexed":
            out[p] = {"state": "ready", "id": r["id"], "name": r["name"]}
        elif r["status"] == "pending":
            out[p] = {"state": "reading"}
        else:
            out[p] = {"state": "unreadable", "id": r["id"]}
    return out


def _save_one(
    st: AppState,
    label: str,
    name: str,
    data: bytes,
    known: dict[str, str],
    sizes: dict[int, list[Any]],
) -> dict[str, Any]:
    max_bytes = st.settings.max_upload_bytes
    try:
        path, digest = st.store.save_upload(
            name, data, max_bytes=max_bytes, known_hashes=known, sizes=sizes
        )
    except DuplicateUpload as e:
        return {
            "filename": label,
            "status": "duplicate",
            "message": "Already in your library",
            "existing": e.existing_rel_path,
        }
    except UploadRejected as e:
        return {"filename": label, "status": "rejected", "message": str(e)}
    known[digest] = st.store.rel(path)
    return {
        "filename": label,
        "status": "added",
        "saved_as": path.name,
        "rel_path": st.store.rel(path),
        "message": "Added",
    }


def _ingest(st: AppState, uploads: list[tuple[str, Any]]) -> list[dict[str, Any]]:
    """Runs in a worker thread: saves plain files and the contents of ZIP archives."""
    with st.db.connect() as conn:
        known = {
            r["sha256"]: r["rel_path"] for r in conn.execute("SELECT sha256, rel_path FROM cvs")
        }
    sizes = st.store.size_index()
    max_bytes = st.settings.max_upload_bytes
    results: list[dict[str, Any]] = []
    for name, fileobj in uploads:
        if name.lower().endswith(".zip"):
            fileobj.seek(0, 2)
            if fileobj.tell() > MAX_ZIP_BYTES:
                results.append(
                    {"filename": name, "status": "rejected", "message": "ZIP is over 300 MB"}
                )
                continue
            fileobj.seek(0)
            try:
                for item in iter_zip(fileobj, max_file_bytes=max_bytes):
                    label = f"{name} › {item.name}"
                    if item.data is None:
                        results.append(
                            {"filename": label, "status": "skipped", "message": item.skipped}
                        )
                    else:
                        results.append(_save_one(st, label, item.name, item.data, known, sizes))
            except ArchiveRejected as e:
                results.append({"filename": name, "status": "rejected", "message": str(e)})
            continue
        fileobj.seek(0)
        data = fileobj.read(max_bytes + 1)
        results.append(_save_one(st, name, name, data, known, sizes))
    return results


@router.post("")
async def upload_cvs(
    st: State,
    files: Annotated[list[UploadFile], File(description="Resumes (PDF/DOCX/DOC) or ZIP archives")],
) -> dict[str, Any]:
    if not files:
        raise HTTPException(400, "No files were sent")
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise HTTPException(400, f"Upload at most {MAX_FILES_PER_UPLOAD} files at a time")
    uploads = [(up.filename or "resume", up.file) for up in files]
    try:
        results = await run_in_threadpool(_ingest, st, uploads)
    finally:
        for up in files:
            await up.close()
    added = sum(r["status"] == "added" for r in results)
    if added:
        st.queue.request(reason="upload")
    summary = {
        k: sum(r["status"] == k for r in results)
        for k in ("added", "duplicate", "rejected", "skipped")
    }
    return {"added": added, "summary": summary, "results": results}
