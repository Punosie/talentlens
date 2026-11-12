"""App-managed settings (things people change in the UI), kept in <data_dir>/settings.json.

This is deliberately separate from .env, which TalentLens never writes.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "cv_dir": None,  # str path of the resume folder chosen in the app
    "ai_enabled": True,  # False = rules only, even if Ollama is installed
    "ai_paused": False,  # background smart reading paused
    "ollama_model": None,  # None = use config default
    "onboarded": False,  # first-run guide completed
    "mongodb_uri": None,  # connections database chosen in the app
}


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._data: dict[str, Any] = dict(DEFAULTS)
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._data.update({k: v for k, v in raw.items() if k in DEFAULTS})
        except (OSError, ValueError):
            pass  # missing or unreadable: defaults

    def get(self, key: str) -> Any:
        with self._lock:
            return self._data.get(key, DEFAULTS.get(key))

    def all(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._data)

    def update(self, **changes: Any) -> dict[str, Any]:
        unknown = set(changes) - set(DEFAULTS)
        if unknown:
            raise KeyError(f"Unknown settings: {sorted(unknown)}")
        with self._lock:
            self._data.update(changes)
            self._write()
            return dict(self._data)

    def _write(self) -> None:
        # atomic replace so a crash never leaves a half-written file
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".settings-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
