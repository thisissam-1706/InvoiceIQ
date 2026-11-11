import asyncio
import json
import threading
from datetime import datetime
from typing import Any, Optional

from sqlmodel import select

from . import db
from .models import Run, RunStep, utcnow_iso
from .pipeline import jsonable


def make_event(
    type_: str,
    run_id: str,
    stage: Optional[str] = None,
    summary: Optional[str] = None,
    detail: Optional[dict] = None,
    decision: Optional[str] = None,
    at: Optional[str] = None,
    duration_ms: Optional[int] = None,
) -> dict:
    return {
        "type": type_,
        "run_id": run_id,
        "stage": stage,
        "at": at or utcnow_iso(),
        "summary": summary,
        "detail": detail or {},
        "decision": decision,
        "duration_ms": duration_ms,
    }


class EventBus:
    """Worker thread → asyncio subscribers. Each SSE connection owns one queue on its own loop."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: dict[str, list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = {}

    def subscribe(self, run_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._subs.setdefault(run_id, []).append((asyncio.get_running_loop(), queue))
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue) -> None:
        with self._lock:
            subs = [s for s in self._subs.get(run_id, []) if s[1] is not queue]
            if subs:
                self._subs[run_id] = subs
            else:
                self._subs.pop(run_id, None)

    def publish(self, event: dict) -> None:
        with self._lock:
            targets = list(self._subs.get(event["run_id"], []))
        for loop, queue in targets:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, event)
            except RuntimeError:
                pass  # subscriber's loop already closed


bus = EventBus()


def _ms_between(start: str, end: str) -> int:
    parse = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))  # noqa: E731
    return int((parse(end) - parse(start)).total_seconds() * 1000)


def stage_started(run_id: str, stage: str) -> RunStep:
    with db.session() as s:
        step = RunStep(run_id=run_id, stage=stage, status="started")
        s.add(step)
        run = s.get(Run, run_id)
        run.current_stage = stage
        s.add(run)
        s.commit()
        s.refresh(step)
    bus.publish(make_event("stage_started", run_id, stage, at=step.started_at))
    return step


def stage_finished(step: RunStep, status: str, summary: str, detail: Any) -> None:
    finished = utcnow_iso()
    detail = jsonable(detail or {})
    with db.session() as s:
        row = s.get(RunStep, step.id)
        row.status = status
        row.finished_at = finished
        row.duration_ms = _ms_between(row.started_at, finished)
        row.summary = summary
        row.detail_json = json.dumps(detail)
        s.add(row)
        s.commit()
        duration = row.duration_ms
    type_ = "stage_completed" if status == "completed" else "stage_failed"
    bus.publish(make_event(type_, step.run_id, step.stage, summary, detail, at=finished, duration_ms=duration))


def replay_events(run_id: str) -> tuple[list[dict], Optional[Run]]:
    """Rebuild the event sequence for a run from persisted steps, for late SSE subscribers."""
    with db.session() as s:
        run = s.get(Run, run_id)
        steps = s.exec(select(RunStep).where(RunStep.run_id == run_id).order_by(RunStep.id)).all()
    events = []
    for step in steps:
        events.append(make_event("stage_started", run_id, step.stage, at=step.started_at))
        if step.status in ("completed", "failed"):
            detail = json.loads(step.detail_json) if step.detail_json else {}
            type_ = "stage_completed" if step.status == "completed" else "stage_failed"
            events.append(make_event(type_, run_id, step.stage, step.summary, detail, at=step.finished_at, duration_ms=step.duration_ms))
    if run and run.status == "completed":
        events.append(make_event("run_completed", run_id, summary=run.explanation_text, decision=run.decision, at=run.finished_at))
    elif run and run.status == "failed":
        events.append(make_event("run_failed", run_id, run.current_stage, run.error_message, at=run.finished_at))
    return events, run
