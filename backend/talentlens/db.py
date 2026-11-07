"""SQLite persistence (WAL mode). Small, explicit schema; no ORM magic.

The DB lives in the app data dir, never next to the CV files.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cvs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    rel_path    TEXT NOT NULL UNIQUE,        -- path relative to CV dir (POSIX separators)
    filename    TEXT NOT NULL,
    ext         TEXT NOT NULL,
    sha256      TEXT NOT NULL,
    size        INTEGER NOT NULL,
    mtime       REAL NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending', -- pending|indexed|unreadable|error
    error       TEXT,
    text        TEXT,
    text_chars  INTEGER NOT NULL DEFAULT 0,
    pages       INTEGER,
    ocr_used    INTEGER NOT NULL DEFAULT 0,
    parser      TEXT,
    extractor   TEXT,                         -- llm|rules|mock
    name        TEXT,
    email       TEXT,
    phone       TEXT,
    location    TEXT,
    city        TEXT,
    country     TEXT,
    years_exp   REAL,
    title       TEXT,
    skills      TEXT NOT NULL DEFAULT '[]',   -- JSON list of canonical skills
    domains     TEXT NOT NULL DEFAULT '[]',   -- JSON list
    education   TEXT NOT NULL DEFAULT '[]',   -- JSON list
    summary     TEXT,
    embedding   BLOB,
    embed_model TEXT,
    llm_json    TEXT,                         -- raw LLM extraction (merged deterministically)
    llm_sha     TEXT,                         -- sha256 of the content llm_json belongs to
    llm_at      TEXT,
    llm_attempts INTEGER NOT NULL DEFAULT 0,
    llm_error   TEXT,
    added_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    indexed_at  TEXT
);
CREATE INDEX IF NOT EXISTS ix_cvs_sha ON cvs(sha256);
CREATE INDEX IF NOT EXISTS ix_cvs_status ON cvs(status);
CREATE INDEX IF NOT EXISTS ix_cvs_years ON cvs(years_exp);
CREATE INDEX IF NOT EXISTS ix_cvs_country ON cvs(country);
CREATE INDEX IF NOT EXISTS ix_cvs_city ON cvs(city);

CREATE TABLE IF NOT EXISTS cv_skills (
    cv_id INTEGER NOT NULL REFERENCES cvs(id) ON DELETE CASCADE,
    skill TEXT NOT NULL COLLATE NOCASE,
    PRIMARY KEY (cv_id, skill)
);
CREATE INDEX IF NOT EXISTS ix_cv_skills_skill ON cv_skills(skill);

CREATE TABLE IF NOT EXISTS cv_domains (
    cv_id  INTEGER NOT NULL REFERENCES cvs(id) ON DELETE CASCADE,
    domain TEXT NOT NULL COLLATE NOCASE,
    PRIMARY KEY (cv_id, domain)
);
CREATE INDEX IF NOT EXISTS ix_cv_domains_domain ON cv_domains(domain);

CREATE VIRTUAL TABLE IF NOT EXISTS cv_fts USING fts5(
    name, title, skills, domains, location, body,
    tokenize = 'porter unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS shortlists (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    jd_text      TEXT NOT NULL,
    requirements TEXT NOT NULL,   -- JSON
    results      TEXT NOT NULL,   -- JSON
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
"""


class Database:
    """Thin thread-safe wrapper: one connection per call, WAL for concurrent readers."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._write_lock = threading.RLock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """Serialise writers inside the process to avoid SQLITE_BUSY churn."""
        with self._write_lock, self.connect() as conn:
            yield conn

    # --- meta helpers -----------------------------------------------------
    def get_meta(self, key: str, default: str | None = None) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self.write() as conn:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )


def loads_list(value: str | None) -> list[Any]:
    if not value:
        return []
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []
