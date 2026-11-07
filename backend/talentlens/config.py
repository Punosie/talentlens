"""Runtime configuration (env vars prefixed TALENTLENS_, optionally from a .env file).

TalentLens never writes the .env file. It only reads it. Settings that people change in the app
(resume folder, AI options) live in <data_dir>/settings.json; see settings_store.py.
"""

from __future__ import annotations

import os
import sys
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


IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"


def _default_data_dir() -> Path:
    """Per-user app data, always outside cloud-synced folders."""
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "TalentLens"
    if IS_MAC:
        return Path.home() / "Library" / "Application Support" / "TalentLens"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "TalentLens"


def discover_cv_dirs() -> list[Path]:
    """Likely resume folders on this machine, best first. Used only when nothing is configured."""
    home = Path.home()
    patterns = [
        "OneDrive*/Desktop/CVs/files",
        "Library/CloudStorage/OneDrive-*/Desktop/CVs/files",  # macOS OneDrive
        "Desktop/CVs/files",
        "OneDrive*/Desktop/CVs",
        "Library/CloudStorage/OneDrive-*/Desktop/CVs",
        "Desktop/CVs",
        "Documents/CVs",
    ]
    found: list[Path] = []
    for pat in patterns:
        try:
            for p in sorted(home.glob(pat)):
                if p.is_dir() and p not in found:
                    found.append(p)
        except OSError:
            continue
    return found


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TALENTLENS_",
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # None = not configured here; the app then uses settings.json, then auto-discovery
    cv_dir: Path | None = None
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
    def legacy_db_path(self) -> Path:
        """v0.1 kept one database here; v0.2 keeps one per resume folder under libraries/."""
        return self.data_dir / "talentlens.db"

    @property
    def libraries_dir(self) -> Path:
        return self.data_dir / "libraries"

    @property
    def settings_path(self) -> Path:
        return self.data_dir / "settings.json"

    @property
    def cv_dir_locked(self) -> bool:
        """True when the folder comes from an env var, .env or code (the UI must not change it)."""
        return "cv_dir" in self.model_fields_set and self.cv_dir is not None

    @property
    def llm_locked(self) -> bool:
        return "llm" in self.model_fields_set

    @property
    def model_cache_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def provenance_csv_for(self, cv_dir: Path) -> Path | None:
        """Optional read-only provenance CSV: configured, or `cv_index.csv` next to the folder."""
        if self.cv_index_csv:
            return self.cv_index_csv
        for guess in (cv_dir.parent / "cv_index.csv", cv_dir / "cv_index.csv"):
            if guess.is_file():
                return guess
        return None

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.model_cache_dir, self.log_dir, self.libraries_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
