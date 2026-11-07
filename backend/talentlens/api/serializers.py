from __future__ import annotations

import sqlite3
from typing import Any

from ..db import loads_list

SUMMARY_COLUMNS = (
    "id, rel_path, filename, ext, status, error, name, email, phone, location, city, country, "
    "years_exp, title, skills, domains, summary, ocr_used, pages, extractor, added_at, indexed_at"
)


def cv_summary(row: sqlite3.Row) -> dict[str, Any]:
    keys = row.keys()
    out: dict[str, Any] = {
        "id": row["id"],
        "filename": row["filename"],
        "ext": row["ext"].lstrip("."),
        "status": row["status"],
        "error": row["error"],
        "name": row["name"],
        "title": row["title"],
        "email": row["email"],
        "phone": row["phone"],
        "location": row["location"],
        "years_exp": row["years_exp"],
        "skills": loads_list(row["skills"]),
        "domains": loads_list(row["domains"]),
        "summary": row["summary"],
        "ocr_used": bool(row["ocr_used"]),
        "pages": row["pages"],
        "extractor": row["extractor"],
        "added_at": row["added_at"],
        "indexed_at": row["indexed_at"],
    }
    if "city" in keys:
        out["city"] = row["city"]
        out["country"] = row["country"]
    return out
