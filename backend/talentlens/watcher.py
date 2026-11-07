"""Watch the CV folder and queue an incremental scan (debounced) when files change."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .config import CV_EXTENSIONS
from .jobs import IndexQueue

log = logging.getLogger(__name__)


class _Handler(FileSystemEventHandler):
    def __init__(self, on_change) -> None:
        self.on_change = on_change

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory or event.event_type in ("opened", "closed_no_write"):
            return
        paths = [event.src_path, getattr(event, "dest_path", "")]
        for p in paths:
            if not p:
                continue
            name = Path(str(p)).name
            if name.startswith(("~$", ".")):
                continue
            if Path(name).suffix.lower() in CV_EXTENSIONS:
                self.on_change()
                return


class FolderWatcher:
    def __init__(self, folder: Path, queue: IndexQueue, debounce_s: float = 2.0) -> None:
        self.folder = folder
        self.queue = queue
        self.debounce_s = debounce_s
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self._observer: Observer | None = None

    def _fire(self) -> None:
        self.queue.request(reason="folder change")

    def _changed(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce_s, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def start(self) -> bool:
        if not self.folder.is_dir():
            log.warning("CV folder %s does not exist; watcher not started", self.folder)
            return False
        observer = Observer()
        observer.schedule(_Handler(self._changed), str(self.folder), recursive=True)
        observer.daemon = True
        observer.start()
        self._observer = observer
        return True

    def stop(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
