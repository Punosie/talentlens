"""Runtime configuration (env vars prefixed TALENTLENS_, optionally from a .env file).

TalentLens never writes the .env file. It only reads it.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

# File types we accept as resumes / JDs
CV_EXTENSIONS: frozenset[str] = frozenset({".pdf", ".docx", ".doc"})
JD_EXTENSIONS: frozenset[str] = frozenset({".pdf", ".docx", ".doc", ".txt"})
INDEXABLE_EXTENSIONS: frozenset[str] = frozenset({".pdf", ".docx", ".doc", ".txt"})


def _default_cv_dir() -> Path:
    return Path(os.path.expandvars(r"%USERPROFILE%")) / "OneDrive" / "Desktop" / "CVs" / "files"


def _default_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "TalentLens"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TALENTLENS_",
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    cv_dir: Path = Field(default_factory=_default_cv_dir)
    cv_index_csv: Path | None = None
    data_dir: Path = Field(default_factory=_default_data_dir)

    host: str = "127.0.0.1"
    port: int = 8765

    llm: Literal["ollama", "off", "mock"] = "ollama"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:3b-instruct"
    ollama_timeout_s: float = 120.0

    embed_model: str = "BAAI/bge-small-en-v1.5"
    rerank_model: str = "jinaai/jina-reranker-v1-turbo-en"
    embeddings: Literal["fastembed", "mock"] = "fastembed"

    max_upload_mb: int = 20
    ocr_min_chars_per_page: int = 50
    watch: bool = True
    scan_on_startup: bool = True

    @field_validator("cv_dir", "data_dir", "cv_index_csv", mode="before")
    @classmethod
    def _expand(cls, v: object) -> object:
        if isinstance(v, str) and v.strip():
            return Path(os.path.expandvars(os.path.expanduser(v.strip())))
        if isinstance(v, str):
            return None
        return v

    @field_validator("host")
    @classmethod
    def _loopback_only(cls, v: str) -> str:
        if v not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("TalentLens only binds to loopback (127.0.0.1) for privacy")
        return v

    @property
    def db_path(self) -> Path:
        return self.data_dir / "talentlens.db"

    @property
    def model_cache_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def resolved_cv_index_csv(self) -> Path | None:
        if self.cv_index_csv:
            return self.cv_index_csv
        guess = self.cv_dir.parent / "cv_index.csv"
        return guess if guess.is_file() else None

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.model_cache_dir, self.log_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
