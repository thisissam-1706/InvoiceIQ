import json
import logging
import queue
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

from .. import db, events
from ..llm import ResolvedClient, build_client
from ..models import AuditEvent, Run, utcnow_iso
from ..settings import UPLOADS_DIR, config_store
from . import (
    STAGES,
    RunContext,
    StageError,
    StageResult,
    code_title,
    decision,
    duplicates,
    explain,
    ingest,
    jsonable,
    llm_extract,
    normalise,
    po_match,
    rules,
    text_extract,
    validate,
    vendor_match,
)

log = logging.getLogger(__name__)

STAGE_FUNCS: dict[str, Callable[[RunContext], StageResult]] = {
    "ingest": ingest.run,
    "text_extract": text_extract.run,
    "llm_extract": llm_extract.run,
    "normalise": normalise.run,
    "validate": validate.run,
    "vendor_match": vendor_match.run,
    "po_match": po_match.run,
    "duplicates": duplicates.run,
    "rules": rules.run,
    "decision": decision.run,
    "explain": explain.run,
}

INCOMING_DIR = UPLOADS_DIR / "incoming"


def audit(run_id: str, action: str, note: Optional[str] = None, actor: str = "system") -> None:
    with db.session() as s:
        s.add(AuditEvent(run_id=run_id, actor=actor, action=action, note=note))
        s.commit()


SOURCE_LABELS = {"upload": "upload", "inbox": "email inbox", "batch": "batch run", "sample": "demo sample", "rerun": "re-run"}


def create_run(file_path: Path, file_name: str, source: str, rerun_of: Optional[str] = None) -> Run:
    run = Run(id=str(uuid.uuid4()), file_name=file_name, file_path=str(file_path), source=source, rerun_of=rerun_of)
    with db.session() as s:
        s.add(run)
        s.commit()
    audit(run.id, "run_queued", f"Received via {SOURCE_LABELS.get(source, source)}: {file_name}")
    return run


def _persist(ctx: RunContext) -> None:
    inv = ctx.invoice
    with db.session() as s:
        run = s.get(Run, ctx.run_id)
        run.file_sha256 = ctx.sha256 or run.file_sha256
        if ctx.stored_path:
            run.file_path = str(ctx.stored_path)
        run.doc_type = ctx.doc_type or run.doc_type
        if ctx.extraction is not None:
            run.extraction_json = json.dumps({"fields": jsonable(ctx.extraction), "meta": jsonable(ctx.extraction_meta)})
        if inv is not None:
            run.invoice_number = inv.invoice_number
            run.invoice_total = str(inv.total) if inv.total is not None else None
            run.currency = ctx.currency
            run.validation_json = json.dumps(
                jsonable({"invoice": inv, "line_sum": inv.line_sum, "checks": [c for c in ctx.checks if c.stage == "validate"]})
            )
        if ctx.current_stage in ("vendor_match", "po_match", "duplicates") or ctx.vendor_match:
            run.vendor_id = ctx.vendor["vendor_id"] if ctx.vendor else None
            run.vendor_name = ctx.vendor["name"] if ctx.vendor else (inv.vendor_name if inv else None)
            run.po_number = ctx.po["po_number"] if ctx.po else None
            po_summary = None
            if ctx.po:
                po_summary = {k: v for k, v in ctx.po.items() if k != "lines"} | {"line_count": len(ctx.po["lines"])}
            run.matching_json = json.dumps(
                jsonable(
                    {
                        "vendor_match": ctx.vendor_match,
                        "vendor": ctx.vendor,
                        "po": po_summary,
                        "po_match": ctx.po_match,
                        "line_matches": ctx.line_matches,
                        "budget": ctx.budget,
                        "duplicate": ctx.duplicate,
                        "pretax_subtotal": inv.pretax_subtotal if inv else None,
                    }
                )
            )
        run.rules_json = json.dumps(
            jsonable(
                {
                    "config_snapshot": ctx.config,
                    "checks": ctx.checks,
                    "findings": [c for c in ctx.checks if c.is_finding],
                }
            )
        )
        if ctx.actions:
            run.suggested_action = json.dumps(jsonable(ctx.actions))
        s.add(run)
        s.commit()


def _finish(run_id: str, started: float, **fields) -> None:
    with db.session() as s:
        run = s.get(Run, run_id)
        for k, v in fields.items():
            setattr(run, k, v)
        run.finished_at = utcnow_iso()
        run.duration_ms = int((time.monotonic() - started) * 1000)
        s.add(run)
        s.commit()


def process_run(run_id: str, stage_delay_ms: Optional[int] = None, resolved: Optional[ResolvedClient] = None) -> Optional[str]:
    """Run every stage for one queued run; returns the decision, or None if the run failed."""
    config = config_store.get()
    delay = (config.demo.stage_delay_ms if stage_delay_ms is None else stage_delay_ms) / 1000
    resolved = resolved or build_client()
    started = time.monotonic()

    with db.session() as s:
        run = s.get(Run, run_id)
        if run is None:
            raise ValueError(f"Unknown run {run_id}")
        run.status = "running"
        run.llm_provider = resolved.client.provider
        run.llm_model = resolved.client.model
        run.provider_note = resolved.note
        s.add(run)
        s.commit()
        ctx = RunContext(
            run_id=run.id,
            file_path=Path(run.file_path),
            file_name=run.file_name,
            source=run.source,
            config=config,
            llm=resolved.client,
        )
    original_path = ctx.file_path

    for stage in STAGES:
        ctx.current_stage = stage
        step = events.stage_started(run_id, stage)
        try:
            result = STAGE_FUNCS[stage](ctx)
        except Exception as exc:
            message = str(exc) if isinstance(exc, StageError) else f"Unexpected error during {stage}: {type(exc).__name__}: {exc}"
            if not isinstance(exc, StageError):
                log.exception("Run %s failed in %s", run_id, stage)
            events.stage_finished(step, "failed", message, {"error": message})
            try:
                _persist(ctx)
            except Exception:
                log.exception("Could not persist partial state for run %s", run_id)
            _finish(run_id, started, status="failed", error_message=message)
            audit(run_id, "run_failed", f"{stage}: {message}")
            events.bus.publish(events.make_event("run_failed", run_id, stage, message))
            return None
        events.stage_finished(step, "completed", result.summary, result.detail)
        if stage == "ingest" and original_path.parent == INCOMING_DIR:
            original_path.unlink(missing_ok=True)
        _persist(ctx)
        if delay:
            time.sleep(delay)

    _finish(
        run_id,
        started,
        status="completed",
        decision=ctx.decision,
        original_decision=ctx.decision,
        explanation_text=ctx.explanation,
        current_stage="explain",
    )
    codes = ", ".join(sorted({code_title(c.code) for c in ctx.findings if c.severity in ("review", "block")})) or "all checks passed"
    audit(run_id, f"decision_{ctx.decision.lower()}", f"System decision {ctx.decision}: {codes}")
    events.bus.publish(events.make_event("run_completed", run_id, summary=ctx.explanation, decision=ctx.decision))
    return ctx.decision


class RunWorker:
    """One background thread so PO consumption and duplicate checks never race."""

    def __init__(self) -> None:
        self.queue: "queue.Queue[str]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self.current: Optional[str] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="run-worker", daemon=True)
        self._thread.start()

    @property
    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def enqueue(self, run_id: str) -> None:
        self.queue.put(run_id)

    def _loop(self) -> None:
        while True:
            run_id = self.queue.get()
            self.current = run_id
            try:
                process_run(run_id)
            except Exception:
                log.exception("Worker crashed on run %s", run_id)
            finally:
                self.current = None
                self.queue.task_done()


worker = RunWorker()
