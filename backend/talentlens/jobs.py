"""Single background worker that runs index jobs and publishes their progress.

Requests are coalesced: while a scan is pending, more incremental requests are
no-ops, and a full request upgrades a pending incremental one.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from .indexer import Indexer

log = logging.getLogger(__name__)


@dataclass
class IndexStatus:
    state: str = "idle"  # idle | queued | running
    kind: str | None = None  # incremental | full
    reason: str | None = None
    total: int = 0
    done: int = 0
    current: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    last_report: dict[str, object] | None = None
    version: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)


class IndexQueue:
    def __init__(self, indexer: Indexer) -> None:
        self.indexer = indexer
        self._cv = threading.Condition()
        self._pending: str | None = None  # None | "incremental" | "full"
        self._pending_reason: str | None = None
        self._status = IndexStatus()
        self._stop = False
        self._thread = threading.Thread(target=self._loop, name="talentlens-indexer", daemon=True)

    # --- lifecycle -------------------------------------------------------
    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify_all()
        if self._thread.is_alive():
            self._thread.join(timeout)

    # --- API ---------------------------------------------------------------
    def request(self, *, full: bool = False, reason: str = "manual") -> IndexStatus:
        kind = "full" if full else "incremental"
        with self._cv:
            if self._pending is None or (kind == "full" and self._pending != "full"):
                self._pending = kind
                self._pending_reason = reason
            if self._status.state == "idle":
                self._update(state="queued", kind=self._pending, reason=reason)
            self._cv.notify_all()
            return self.status()

    def status(self) -> IndexStatus:
        with self._cv:
            return IndexStatus(**asdict(self._status))

    def wait_version(self, after: int, timeout: float) -> IndexStatus:
        """Block until the status version exceeds `after` (or timeout). Used by SSE."""
        deadline = time.monotonic() + timeout
        with self._cv:
            while self._status.version <= after and not self._stop:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._cv.wait(remaining)
            return IndexStatus(**asdict(self._status))

    def wait_idle(self, timeout: float = 60.0) -> bool:
        """Test helper: block until no job is queued or running."""
        deadline = time.monotonic() + timeout
        with self._cv:
            while self._pending is not None or self._status.state != "idle":
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cv.wait(remaining)
            return True

    # --- internals ---------------------------------------------------------------
    def _update(self, **changes: object) -> None:
        # caller holds self._cv
        for k, v in changes.items():
            setattr(self._status, k, v)
        self._status.version += 1
        self._cv.notify_all()

    def _progress(self, done: int, total: int, current: str) -> None:
        with self._cv:
            self._update(done=done, total=total, current=current)

    def _loop(self) -> None:
        while True:
            with self._cv:
                while self._pending is None and not self._stop:
                    self._cv.wait()
                if self._stop:
                    return
                kind, reason = self._pending, self._pending_reason
                self._pending = self._pending_reason = None
                self._update(
                    state="running",
                    kind=kind,
                    reason=reason,
                    total=0,
                    done=0,
                    current="",
                    started_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    finished_at=None,
                )
            report_dict: dict[str, object]
            try:
                report = self.indexer.run(full=kind == "full", progress=self._progress)
                report_dict = report.as_dict()
            except Exception as e:
                log.exception("Index job crashed")
                report_dict = {"fatal": str(e)}
            with self._cv:
                self._update(
                    state="queued" if self._pending else "idle",
                    current="",
                    finished_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    last_report=report_dict,
                    errors=list(report_dict.get("errors", []))[:50],  # type: ignore[arg-type]
                )
