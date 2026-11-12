"""Connections database (MongoDB) <-> TalentLens library.

Pull: LinkedIn connection profiles in MongoDB become searchable, matchable records
      (source='linkedin') in the current library, embedded locally like any CV.
Push: resumes read by TalentLens are written to MongoDB as people, linked to the
      LinkedIn profile they belong to when the CV contains its LinkedIn URL, or matched by
      email/file hash on later updates; otherwise a new person ("cv:<hash>") is created.

Hard rules: never touches the CV folder; never deletes anything in MongoDB; never sends
data anywhere but the configured MongoDB.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import re
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .ai import rules, taxonomy
from .db import Database, loads_list
from .enrich import CVFields
from .indexer import Indexer, embedding_text

log = logging.getLogger(__name__)

SOURCE = "linkedin"
REL_PREFIX = "linkedin/"
EMBED_BATCH = 64
PAGE_SIZE = 200  # fetched fully per round trip: no server cursor stays open while we embed
PROFILE_FIELDS = {
    "full_name": 1,
    "headline": 1,
    "about": 1,
    "current": 1,
    "loc": 1,
    "location": 1,
    "years_exp": 1,
    "skills": 1,
    "experiences": 1,
    "education": 1,
    "industry": 1,
    "certifications": 1,
    "languages": 1,
    "owners": 1,
    "profile_url": 1,
    "seniority": 1,
    "migrated_at": 1,
    "sources": 1,
}
_LINKEDIN_URL = re.compile(r"linkedin\.com/in/([A-Za-z0-9\-_%]{3,100})", re.I)

# ------------------------------------------------------------------ pull: profile -> record

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _ym(d: Any) -> str:
    if not isinstance(d, dict) or not d.get("year"):
        return ""
    m = d.get("month")
    return (
        f"{_MONTHS[m - 1]} {d['year']}" if isinstance(m, int) and 1 <= m <= 12 else str(d["year"])
    )


def _clean(s: Any) -> str:
    return s.strip() if isinstance(s, str) else ""


def profile_text(doc: dict[str, Any]) -> str:
    """Readable plain-text 'resume' built from a LinkedIn profile (what search, the reranker
    and the explanation model read)."""
    lines: list[str] = [_clean(doc.get("full_name")), _clean(doc.get("headline"))]
    if doc.get("location"):
        lines.append(f"Location: {doc['location']}")
    if doc.get("industry"):
        lines.append(f"Industry: {doc['industry']}")
    if doc.get("years_exp"):
        lines.append(f"Experience: about {round(float(doc['years_exp']))} years")
    about = _clean(doc.get("about"))
    if about:
        lines += ["", "About", about]
    exps = doc.get("experiences") or []
    if exps:
        lines += ["", "Experience"]
        for e in exps:
            if not isinstance(e, dict):
                continue
            when = " – ".join(
                x
                for x in (
                    _ym(e.get("start")),
                    "Present" if e.get("is_current") else _ym(e.get("end")),
                )
                if x
            )
            head = " at ".join(x for x in (_clean(e.get("title")), _clean(e.get("company"))) if x)
            meta = " · ".join(
                x for x in (when, _clean(e.get("location")), _clean(e.get("employment_type"))) if x
            )
            lines.append(f"- {head}" + (f" ({meta})" if meta else ""))
            desc = _clean(e.get("description"))
            if desc:
                lines.append("  " + desc.replace("\n", "\n  "))
    edu = doc.get("education") or []
    if edu:
        lines += ["", "Education"]
        for e in edu:
            if isinstance(e, dict):
                parts = [x for x in (_clean(e.get("degree")), _clean(e.get("field"))) if x]
                years = "–".join(str(y) for y in (e.get("start_year"), e.get("end_year")) if y)
                lines.append(
                    f"- {_clean(e.get('school'))}"
                    + (f": {', '.join(parts)}" if parts else "")
                    + (f" ({years})" if years else "")
                )
    skills = [s for s in doc.get("skills") or [] if isinstance(s, str)]
    if skills:
        lines += ["", "Skills", ", ".join(skills)]
    certs = [c for c in doc.get("certifications") or [] if isinstance(c, dict) and c.get("name")]
    if certs:
        lines += ["", "Certifications"] + [
            f"- {c['name']}" + (f" ({c['authority']})" if c.get("authority") else "") for c in certs
        ]
    langs = [
        lng.get("name")
        for lng in doc.get("languages") or []
        if isinstance(lng, dict) and lng.get("name")
    ]
    if langs:
        lines += ["", "Languages", ", ".join(langs)]
    return "\n".join(lines).strip()


def profile_fields(doc: dict[str, Any], text: str) -> CVFields:
    """Structured fields for a LinkedIn profile, normalised with TalentLens's own taxonomy so
    skill/location/industry filters and JD matching treat it exactly like a CV."""
    tax = taxonomy.skills()
    dm = taxonomy.domains()
    gz = taxonomy.gazetteer()
    loc = doc.get("loc") or {}
    city, country = gz.normalize(
        _clean(loc.get("city")) or None, _clean(loc.get("country")) or None
    )
    city = city or (_clean(loc.get("city")) or None)
    country = country or (_clean(loc.get("country")) or None)

    skills: list[str] = []
    seen: set[str] = set()
    for raw in [s for s in doc.get("skills") or [] if isinstance(s, str)] + rules.extract_skills(
        text, limit=40
    ):
        c = tax.canonicalize(raw) or raw.strip()
        if c and c.lower() not in seen:
            seen.add(c.lower())
            skills.append(c)

    current = doc.get("current") or {}
    title = _clean(current.get("title")) or _clean(doc.get("headline"))[:90] or None
    domains: list[str] = []
    for raw in [doc.get("industry")] if doc.get("industry") else []:
        d = dm.canonicalize(raw)
        if d and d not in domains:
            domains.append(d)
    for d in rules.extract_domains(text, title, limit=3):
        if d not in domains:
            domains.append(d)

    education = []
    for e in doc.get("education") or []:
        if isinstance(e, dict) and e.get("school"):
            parts = ", ".join(x for x in (_clean(e.get("degree")), _clean(e.get("field"))) if x)
            education.append(f"{parts} — {e['school']}" if parts else _clean(e["school"]))

    years = doc.get("years_exp")
    return CVFields(
        name=_clean(doc.get("full_name")) or None,
        email=None,
        phone=None,
        location=rules.format_location(city, country) or (_clean(doc.get("location")) or None),
        city=city,
        country=country,
        years_exp=float(years) if isinstance(years, (int, float)) and years > 0 else None,
        title=title,
        skills=skills[:60],
        domains=domains[:4],
        education=education[:4],
        summary=_clean(doc.get("headline")) or (_clean(doc.get("about"))[:300] or None),
        extractor=SOURCE,
        confident=True,
    )


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest().upper()


def _owners(doc: dict[str, Any]) -> list[str]:
    return [
        o["account"] for o in doc.get("owners") or [] if isinstance(o, dict) and o.get("account")
    ]


# ------------------------------------------------------------------ push: CV -> person


def linkedin_id_in(text: str | None) -> str | None:
    m = _LINKEDIN_URL.search(text or "")
    return m.group(1).rstrip("/").lower() if m else None


def cv_person_doc(row: dict[str, Any]) -> dict[str, Any]:
    """Fields describing a person known only from their CV (used when creating them)."""
    name = row.get("name") or re.sub(r"\.(pdf|docx?)$", "", row.get("filename") or "", flags=re.I)
    skills = loads_list(row.get("skills"))
    return {
        "full_name": name,
        "name_sort": (name or "").strip().lower(),
        "headline": row.get("title"),
        "about": row.get("summary"),
        "current": {"title": row.get("title"), "company": None},
        "loc": {"city": row.get("city"), "state": None, "country": row.get("country")},
        "location": row.get("location"),
        "years_exp": row.get("years_exp"),
        "skills": skills,
        "industry": (loads_list(row.get("domains")) or [None])[0],
        "has_full_profile": True,
        "profile_url": None,
    }


def cv_info(row: dict[str, Any]) -> dict[str, Any]:
    """What a CV adds to any person (stored under `cv`, never overwriting LinkedIn data)."""
    return {
        "filename": row.get("filename"),
        "sha256": row.get("sha256"),
        "email": row.get("email"),
        "phone": row.get("phone"),
        "title": row.get("title"),
        "years_exp": row.get("years_exp"),
        "location": row.get("location"),
        "skills": loads_list(row.get("skills")),
        "domains": loads_list(row.get("domains")),
        "education": loads_list(row.get("education")),
        "summary": row.get("summary"),
        "extractor": row.get("extractor"),
        "updated_at": datetime.now(UTC),
    }


# ------------------------------------------------------------------ sync service


@dataclass
class SyncStatus:
    configured: bool = False
    state: str = "idle"  # idle | pulling | pushing | error | off
    last_pull_at: str | None = None
    last_push_at: str | None = None
    pulled: int = 0  # profiles in the library from MongoDB
    last_changes: dict[str, int] = field(default_factory=dict)
    pushed_total: int = 0
    error: str | None = None


ClientFactory = Callable[[str], Any]


def _default_client(uri: str) -> Any:
    from pymongo import MongoClient

    return MongoClient(uri, serverSelectionTimeoutMS=10000, appname="talentlens")


class ConnectionsSync:
    def __init__(
        self,
        db: Database,
        indexer: Indexer,
        uri: str | None,
        *,
        database: str = "linkedin",
        collection: str = "connections",
        client_factory: ClientFactory = _default_client,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.db = db
        self.indexer = indexer
        self.uri = uri
        self.database = database
        self.collection = collection
        self._client_factory = client_factory
        self._client: Any = None
        self._clock = clock
        self._lock = threading.Lock()
        self.full_next = False  # set by "sync now (full)"; consumed by the next run
        self.status = SyncStatus(configured=bool(uri), state="idle" if uri else "off")
        self.status.last_pull_at = db.get_meta("mongo_last_pull_at")
        self.status.last_push_at = db.get_meta("mongo_last_push_at")
        self.status.pulled = self._count_local()

    # -- plumbing
    def _col(self) -> Any:
        if self._client is None:
            self._client = self._client_factory(self.uri or "")
        return self._client[self.database][self.collection]

    def _count_local(self) -> int:
        with self.db.connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM cvs WHERE source=?", (SOURCE,)).fetchone()[0]

    def close(self) -> None:
        if self._client is not None:
            with contextlib.suppress(Exception):
                self._client.close()
            self._client = None

    # -- one full cycle (called from the background job queue)
    def run(
        self, *, full: bool = False, progress: Callable[[int, int, str], None] | None = None
    ) -> dict[str, int]:
        if not self.uri:
            return {}
        if not self._lock.acquire(blocking=False):
            return {}
        full = full or self.full_next
        self.full_next = False
        try:
            changes = self.pull(full=full, progress=progress)
            changes.update(self.push())
            self.status.error = None
            self.status.state = "idle"
            return changes
        except Exception as e:  # network/auth problems never break indexing
            log.warning("Connections sync failed: %s", e)
            self.status.state = "error"
            self.status.error = _friendly_error(e)
            return {}
        finally:
            self._lock.release()

    # -- MongoDB -> library
    def pull(
        self, *, full: bool = False, progress: Callable[[int, int, str], None] | None = None
    ) -> dict[str, int]:
        self.status.state = "pulling"
        col = self._col()
        last = None if full else self.db.get_meta("mongo_pull_cursor")
        query: dict[str, Any] = {"sources": SOURCE}
        if last:
            query["migrated_at"] = {"$gt": datetime.fromisoformat(last)}
        started = datetime.now(UTC)

        with self.db.connect() as conn:
            local = {
                r["rel_path"]: (r["id"], r["sha256"], r["owners"], r["profile_url"])
                for r in conn.execute(
                    "SELECT id, rel_path, sha256, owners, profile_url FROM cvs WHERE source=?",
                    (SOURCE,),
                )
            }

        added = updated = meta_only = unchanged = 0
        seen: set[str] = set()
        batch: list[tuple[str, dict[str, Any], str, CVFields]] = []
        newest: datetime | None = None
        total = col.count_documents(query)

        def flush() -> None:
            nonlocal added, updated
            if not batch:
                return
            texts = [embedding_text(f, t) for _, _, t, f in batch]
            try:
                emb = self.indexer.enricher.embed_documents(texts)
            except Exception:
                log.exception("Embedding LinkedIn profiles failed; storing without vectors")
                emb = None
            with self.db.write() as conn:
                for i, (rel, doc, text, fields) in enumerate(batch):
                    blob = emb[i].astype("float32").tobytes() if emb is not None else None
                    self.indexer.upsert_external(
                        conn,
                        rel_path=rel,
                        filename=f"{fields.name or doc['_id']} (LinkedIn)",
                        source=SOURCE,
                        sha=_sha(text),
                        text=text,
                        fields=fields,
                        blob=blob,
                        mtime=_ts(doc.get("migrated_at")),
                        extra={
                            "person_id": doc["_id"],
                            "owners": json.dumps(_owners(doc)),
                            "profile_url": doc.get("profile_url"),
                        },
                    )
                    if rel in local:
                        updated += 1
                    else:
                        added += 1
            batch.clear()

        for done, doc in enumerate(_pages(col, query), start=1):
            rel = REL_PREFIX + str(doc["_id"])
            seen.add(rel)
            m = doc.get("migrated_at")
            if isinstance(m, datetime):
                m = m if m.tzinfo else m.replace(tzinfo=UTC)
                newest = m if newest is None or m > newest else newest
            text = profile_text(doc)
            have = local.get(rel)
            if have and have[1] == _sha(text):
                owners = json.dumps(_owners(doc))
                if have[2] != owners or have[3] != doc.get("profile_url"):
                    with self.db.write() as conn:
                        conn.execute(
                            "UPDATE cvs SET owners=?, profile_url=?, person_id=? WHERE id=?",
                            (owners, doc.get("profile_url"), doc["_id"], have[0]),
                        )
                    meta_only += 1
                else:
                    unchanged += 1
            else:
                batch.append((rel, doc, text, profile_fields(doc, text)))
                if len(batch) >= EMBED_BATCH:
                    flush()
            if progress and done % 200 == 0:
                progress(done, total, "Syncing connections")
        flush()

        removed = 0
        if (
            full
        ):  # profiles deleted from MongoDB disappear locally (MongoDB itself is never touched)
            gone = [v[0] for k, v in local.items() if k not in seen]
            if gone:
                with self.db.write() as conn:
                    self.indexer.delete_ids(conn, gone)
                removed = len(gone)

        cursor = newest.isoformat() if newest else (last or None)
        if full and not newest:
            cursor = started.isoformat()
        if cursor:
            self.db.set_meta("mongo_pull_cursor", cursor)
        now = _now()
        self.db.set_meta("mongo_last_pull_at", now)
        self.status.last_pull_at = now
        self.status.pulled = self._count_local()
        changes = {
            "added": added,
            "updated": updated + meta_only,
            "removed": removed,
            "unchanged": unchanged,
        }
        self.status.last_changes = dict(changes)
        if added or updated or removed:
            self.indexer.notify_changed()
        return changes

    # -- library CVs -> MongoDB
    def push(self, limit: int = 500) -> dict[str, int]:
        self.status.state = "pushing"
        with self.db.connect() as conn:
            rows = [
                dict(r)
                for r in conn.execute(
                    "SELECT id, filename, sha256, llm_sha, name, email, phone, location, city, "
                    "country, years_exp, title, skills, domains, education, summary, extractor, "
                    "text, person_id FROM cvs WHERE source='file' AND status='indexed' "
                    "AND (mongo_pushed IS NULL "
                    "OR mongo_pushed != sha256 || ':' || COALESCE(llm_sha, '')) "
                    "ORDER BY added_at LIMIT ?",
                    (limit,),
                )
            ]
        if not rows:
            return {"pushed": 0}
        col = self._col()
        linked = created = 0
        for row in rows:
            pid, is_new = self._target_person(col, row)
            update: dict[str, Any] = {
                "$set": {"cv": cv_info(row), "migrated_at": datetime.now(UTC)},
                "$addToSet": {"sources": "cv"},
            }
            if is_new:
                update["$setOnInsert"] = {**cv_person_doc(row), "owners": []}
            elif pid.startswith("cv:"):
                # a CV-only person: their profile IS the CV, so keep it current
                update["$set"].update({k: v for k, v in cv_person_doc(row).items()})
            col.update_one({"_id": pid}, update, upsert=True)
            with self.db.write() as conn:
                conn.execute(
                    "UPDATE cvs SET person_id=?, mongo_pushed=? WHERE id=?",
                    (pid, f"{row['sha256']}:{row['llm_sha'] or ''}", row["id"]),
                )
            if is_new:
                created += 1
            else:
                linked += 1
        now = _now()
        self.db.set_meta("mongo_last_push_at", now)
        self.status.last_push_at = now
        self.status.pushed_total = self._count_pushed()
        return {"pushed": len(rows), "created": created, "linked": linked}

    def _target_person(self, col: Any, row: dict[str, Any]) -> tuple[str, bool]:
        """Which MongoDB person this CV belongs to. Order: LinkedIn URL in the CV text ->
        the person this file was linked to before -> same file hash -> same email -> new."""
        lid = linkedin_id_in(row.get("text"))
        if lid:
            hit = col.find_one(
                {"_id": {"$regex": f"^{re.escape(lid)}$", "$options": "i"}}, {"_id": 1}
            )
            if hit:
                return str(hit["_id"]), False
        if row.get("person_id"):
            return str(row["person_id"]), not bool(
                col.find_one({"_id": row["person_id"]}, {"_id": 1})
            )
        hit = col.find_one({"cv.sha256": row["sha256"]}, {"_id": 1})
        if hit:
            return str(hit["_id"]), False
        if row.get("email"):
            hit = col.find_one({"cv.email": row["email"]}, {"_id": 1})
            if hit:
                return str(hit["_id"]), False
        return f"cv:{row['sha256'][:20].lower()}", True

    def _count_pushed(self) -> int:
        with self.db.connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM cvs WHERE source='file' AND mongo_pushed IS NOT NULL"
            ).fetchone()[0]

    def snapshot(self) -> dict[str, Any]:
        s = self.status
        return {
            "configured": s.configured,
            "state": s.state,
            "last_pull_at": s.last_pull_at,
            "last_push_at": s.last_push_at,
            "profiles": s.pulled,
            "last_changes": s.last_changes,
            "cvs_pushed": self._count_pushed() if s.configured else 0,
            "error": s.error,
        }


def _pages(col: Any, query: dict[str, Any]) -> Iterable[dict[str, Any]]:
    """All matching profiles in _id order, one short query per page (keyset pagination).

    A single long-lived cursor gets closed by shared Atlas tiers while slow local embedding
    runs between batches (CursorNotFound); short independent queries never time out."""
    last: Any = None
    while True:
        q = dict(query)
        if last is not None:
            q["_id"] = {"$gt": last}
        page = list(col.find(q, PROFILE_FIELDS).sort("_id", 1).limit(PAGE_SIZE))
        if not page:
            return
        yield from page
        last = page[-1]["_id"]
        if len(page) < PAGE_SIZE:
            return


def _ts(v: Any) -> float:
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=UTC)).timestamp()
    return 0.0


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _friendly_error(e: Exception) -> str:
    msg = str(e)
    if "Authentication failed" in msg or "bad auth" in msg:
        return "MongoDB rejected the username or password."
    if "ServerSelectionTimeout" in type(e).__name__ or "timed out" in msg:
        return (
            "Couldn't reach MongoDB. Check your internet connection and the Atlas IP access list."
        )
    if "not authorized" in msg:
        return "This MongoDB user isn't allowed to read or write the connections database."
    return "Couldn't sync with MongoDB."


def iter_owner_counts(rows: Iterable[Any]) -> dict[str, int]:
    """Count records per LinkedIn owner (for facets)."""
    out: dict[str, int] = {}
    for r in rows:
        for o in loads_list(r["owners"]):
            out[o] = out.get(o, 0) + 1
    return out
