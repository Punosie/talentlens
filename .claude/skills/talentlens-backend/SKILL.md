---
name: talentlens-backend
description: Conventions and hard rules for TalentLens backend work (FastAPI, SQLite, parsing, indexing, local AI). Load before changing anything under backend/ or scripts/.
---

# TalentLens backend conventions

## Hard rules (never break)
1. **CV source files are read-only.** Never modify, rename, move or delete an existing file in the CV folder (`TALENTLENS_CV_DIR`). Uploads only *add* new files:
   - reject duplicates by SHA-256
   - suffix ` (2)`, ` (3)` and so on when the name collides
   - sanitize filenames and refuse path traversal
2. **Never write** `cv_index.csv`, `not_copied.csv` or any `.env`. Read them only. Setup scripts may create `.env` only when none exists.
3. App state (SQLite DB, embeddings, model cache, logs) lives in `TALENTLENS_DATA_DIR` (default `%LOCALAPPDATA%\TalentLens`), never inside the CV folder or OneDrive.
4. Bind to `127.0.0.1` only. Cap uploads at 20 MB, validate the extension and the magic bytes.
5. Tests use synthetic fixtures generated in `conftest.py`. Never use real CVs in tests, logs or fixtures.

## Stack
- Python 3.12 via `uv`. Run with `uv run ...`; add dependencies with `uv add`.
- FastAPI and pydantic v2, with routers in `talentlens/api/`. Settings come from `talentlens.config.Settings` (pydantic-settings, `TALENTLENS_` prefix).
- SQLite in WAL mode. FTS5 handles lexical search. Embeddings are float32 BLOBs, kept in an in-memory numpy matrix for cosine search.
- AI is local only:
  - Ollama (`qwen2.5:3b-instruct`) with JSON-schema `format`
  - `fastembed` (bge-small-en-v1.5, bge-reranker-base)
  - RapidOCR
- Every AI call must degrade gracefully. When Ollama is unavailable, fall back to the rule-based extractor and never crash indexing.
- `TALENTLENS_LLM=mock` swaps in a deterministic fake for tests.

## Patterns
- Long work (indexing) runs on the single background job queue (`talentlens.jobs`) and reports progress for the SSE endpoint. Request handlers never block on parsing or LLM calls.
- Indexing is incremental, keyed on (path, size, mtime) and then SHA-256. A "full" refresh re-extracts everything but still never touches the source files.
- Every new endpoint and pure function gets a pytest test. UI flows get a Playwright spec in `frontend/e2e/`.
- Lint with `uv run ruff check` and format with `uv run ruff format`.
