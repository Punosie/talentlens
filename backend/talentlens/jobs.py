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
    state: str = "idle"  # idle | queued | running | enhancing
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
    ai_pending: int = 0
    ai_paused: bool = False
    ai_last: dict[str, int] | None = None


class IndexQueue:
    def __init__(self, indexer: Indexer) -> None:
        self.indexer = indexer
        self._cv = threading.Condition()
        self._pending: str | None = None  # None | "incremental" | "full"
        self._pending_reason: str | None = None
        self._status = IndexStatus()
        self._stop = False
        self.ai_paused = False
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
                # state stays "running" until _enhance() decides what happens next, so
                # observers never see a transient "idle" between the two stages
                self._update(
                    current="",
                    finished_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    last_report=report_dict,
                    errors=list(report_dict.get("errors", []))[:50],  # type: ignore[arg-type]
                )
            self._enhance()

    def _finish(self, **changes: object) -> None:
        # caller holds self._cv
        self._update(state="queued" if self._pending else "idle", current="", **changes)

    def _enhance(self) -> None:
        """Stage 2: LLM refinement. Yields as soon as a new index request arrives."""
        pending = self._safe_pending_count()
        with self._cv:
            if self._pending is not None or self._stop or self.ai_paused or pending == 0:
                self._finish(ai_pending=pending)
                return
            self._update(state="enhancing", total=pending, done=0, current="")

        def should_stop() -> bool:
            with self._cv:
                return self._pending is not None or self._stop or self.ai_paused

        try:
            result = self.indexer.refine_pending(should_stop=should_stop, progress=self._progress)
        except Exception:
            log.exception("AI enhancement crashed")
            result = {}
        pending = self._safe_pending_count()
        with self._cv:
            self._finish(ai_pending=pending, ai_last=result)

    def _safe_pending_count(self) -> int:
        try:
            return self.indexer.pending_llm_count()
        except Exception:
            return 0

    def set_ai_paused(self, paused: bool) -> IndexStatus:
        with self._cv:
            self.ai_paused = paused
            self._update(ai_paused=paused)
            if not paused and self._status.state == "idle":
                # kick the worker so pending AI work resumes
                self._pending = self._pending or "incremental"
                self._pending_reason = "resume AI"
            self._cv.notify_all()
            return IndexStatus(**asdict(self._status))
