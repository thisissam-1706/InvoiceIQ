"""Polls data/inbox/ for PDFs, standing in for an AP email inbox."""

import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from .pipeline.orchestrator import create_run, worker
from .settings import INBOX_DIR, config_store

log = logging.getLogger(__name__)


class InboxWatcher:
    def __init__(self, inbox: Path = INBOX_DIR) -> None:
        self.inbox = inbox
        self.processed = inbox / "processed"
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._sizes: dict[Path, int] = {}

    def start(self) -> None:
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.processed.mkdir(exist_ok=True)
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="inbox-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def poll_once(self) -> list[str]:
        started = []
        current = {p for p in self.inbox.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"}
        for path in sorted(current):
            try:
                size = path.stat().st_size
            except FileNotFoundError:
                continue
            # Only pick a file up once its size is unchanged across two polls, so half-copied files are skipped.
            if size > 0 and self._sizes.get(path) == size:
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                dest = self.processed / f"{stamp}_{path.name}"
                path.rename(dest)
                run = create_run(dest, path.name, "inbox")
                worker.enqueue(run.id)
                self._sizes.pop(path, None)
                started.append(run.id)
                log.info("Inbox picked up %s as run %s", path.name, run.id)
            else:
                self._sizes[path] = size
        for gone in set(self._sizes) - current:
            self._sizes.pop(gone, None)
        return started

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception:
                log.exception("Inbox poll failed")
            self._stop.wait(config_store.get().demo.inbox_poll_seconds)


watcher = InboxWatcher()
