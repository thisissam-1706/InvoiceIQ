import asyncio
import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func, or_
from sqlmodel import select

from .. import db, events
from ..models import AuditEvent, Run, RunStep
from ..pipeline import code_info
from ..pipeline.decision import record_consumption
from ..pipeline.orchestrator import INCOMING_DIR, audit, create_run, worker
from ..schemas import AuditOut, OverrideRequest, RunCreated, RunDetail, RunList, RunSummary, StepOut
from ..settings import SAMPLES_DIR

router = APIRouter(prefix="/api", tags=["runs"])

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
HEARTBEAT_SECONDS = 15


def _loads(raw: Optional[str]) -> Optional[dict]:
    return json.loads(raw) if raw else None


def run_summary(r: Run) -> RunSummary:
    return RunSummary.model_validate(r, from_attributes=True)


def _get_run(s, run_id: str) -> Run:
    run = s.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    return run


def _start(path: Path, name: str, source: str, rerun_of: Optional[str] = None) -> RunCreated:
    run = create_run(path, name, source, rerun_of=rerun_of)
    worker.enqueue(run.id)
    return RunCreated(run_id=run.id, file_name=name)


@router.post("/runs", response_model=list[RunCreated])
async def upload_runs(files: list[UploadFile] = File(...)) -> list[RunCreated]:
    if not files:
        raise HTTPException(400, "No files uploaded")
    INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    created = []
    for f in files:
        data = await f.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"{f.filename} is larger than 25 MB")
        name = Path(f.filename or "upload.pdf").name
        tmp = INCOMING_DIR / f"{uuid.uuid4().hex}{Path(name).suffix.lower() or '.bin'}"
        tmp.write_bytes(data)
        created.append(_start(tmp, name, "upload"))
    return created


@router.post("/runs/sample/{filename}", response_model=RunCreated)
def run_sample(filename: str) -> RunCreated:
    path = (SAMPLES_DIR / filename).resolve()
    if path.parent != SAMPLES_DIR.resolve() or path.suffix != ".pdf" or not path.exists():
        raise HTTPException(404, "Sample not found. Run backend/scripts/generate_samples.py first.")
    return _start(path, filename, "sample")


@router.get("/runs", response_model=RunList)
def list_runs(
    decision: Optional[str] = None,
    status: Optional[str] = None,
    vendor_id: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> RunList:
    stmt = select(Run)
    if decision:
        stmt = stmt.where(Run.decision == decision.upper())
    if status:
        stmt = stmt.where(Run.status == status.lower())
    if vendor_id:
        stmt = stmt.where(Run.vendor_id == vendor_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(Run.file_name.ilike(like), Run.invoice_number.ilike(like), Run.vendor_name.ilike(like), Run.po_number.ilike(like))
        )
    with db.session() as s:
        total = s.exec(select(func.count()).select_from(stmt.subquery())).one()
        rows = s.exec(stmt.order_by(Run.created_at.desc()).offset(offset).limit(limit)).all()
    return RunList(items=[run_summary(r) for r in rows], total=total)


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: str) -> RunDetail:
    with db.session() as s:
        run = _get_run(s, run_id)
        steps = s.exec(select(RunStep).where(RunStep.run_id == run_id).order_by(RunStep.id)).all()
        audit_rows = s.exec(select(AuditEvent).where(AuditEvent.run_id == run_id).order_by(AuditEvent.id)).all()
    rules = _loads(run.rules_json)
    return RunDetail(
        run=run_summary(run),
        steps=[
            StepOut(
                stage=st.stage,
                status=st.status,
                started_at=st.started_at,
                finished_at=st.finished_at,
                duration_ms=st.duration_ms,
                summary=st.summary,
                detail=_loads(st.detail_json) or {},
            )
            for st in steps
        ],
        extraction=_loads(run.extraction_json),
        validation=_loads(run.validation_json),
        matching=_loads(run.matching_json),
        rules=rules,
        checks=[{**c, **code_info(c.get("code", ""))} for c in (rules or {}).get("checks", [])],
        explanation=run.explanation_text,
        actions=_loads(run.suggested_action),
        audit=[AuditOut(at=a.at, actor=a.actor, action=a.action, note=a.note) for a in audit_rows],
        llm_provider=run.llm_provider,
        llm_model=run.llm_model,
        provider_note=run.provider_note,
    )


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _key(event: dict) -> tuple:
    return event["type"], event.get("stage")


@router.get("/runs/{run_id}/events")
async def run_events(run_id: str, request: Request) -> StreamingResponse:
    with db.session() as s:
        _get_run(s, run_id)
    queue = events.bus.subscribe(run_id)

    async def stream():
        try:
            replay, run = events.replay_events(run_id)
            seen = set()
            for ev in replay:
                seen.add(_key(ev))
                yield _sse(ev)
            if run and run.status in ("completed", "failed"):
                return
            while not await request.is_disconnected():
                try:
                    ev = await asyncio.wait_for(queue.get(), HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                if _key(ev) in seen:
                    continue
                seen.add(_key(ev))
                yield _sse(ev)
                if ev["type"] in ("run_completed", "run_failed"):
                    return
        finally:
            events.bus.unsubscribe(run_id, queue)

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@router.get("/runs/{run_id}/file")
def run_file(run_id: str) -> FileResponse:
    with db.session() as s:
        run = _get_run(s, run_id)
    path = Path(run.file_path)
    if not path.exists():
        raise HTTPException(404, "Original file is no longer available")
    return FileResponse(
        path, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{run.file_name}"'}
    )


@router.post("/runs/{run_id}/override", response_model=RunSummary)
def override(run_id: str, body: OverrideRequest) -> RunSummary:
    with db.session() as s:
        run = _get_run(s, run_id)
        if run.decision != "HOLD" or run.decision_overridden:
            raise HTTPException(409, "Only invoices currently on HOLD can be overridden")
        if run.superseded_by:
            raise HTTPException(409, "This run was superseded by a re-run; override the newer run instead")
        run.decision = body.decision
        run.decision_overridden = True
        s.add(run)
        s.commit()
        s.refresh(run)
    matching = _loads(run.matching_json) or {}
    consumed = None
    if body.decision == "APPROVE" and run.po_number and matching.get("pretax_subtotal") is not None:
        consumed = Decimal(matching["pretax_subtotal"])
        record_consumption(run.id, run.po_number, consumed, "override_approve")
    note = body.note + (f" [{run.po_number} consumed {consumed:,.2f}]" if consumed is not None else "")
    audit(run.id, f"override_{body.decision.lower()}", note, actor="reviewer")
    return run_summary(run)


@router.post("/runs/{run_id}/rerun", response_model=RunCreated)
def rerun(run_id: str) -> RunCreated:
    with db.session() as s:
        run = _get_run(s, run_id)
        if run.status in ("queued", "running"):
            raise HTTPException(409, "This run is still processing")
        if run.decision == "APPROVE":
            raise HTTPException(
                409, "Approved invoices have already consumed PO budget; re-running would double-count. Reset demo data instead."
            )
        if run.superseded_by:
            raise HTTPException(409, "This run has already been re-run")
        path = Path(run.file_path)
        if not path.exists():
            raise HTTPException(410, "Original file is no longer available")
        created = _start(path, run.file_name, run.source, rerun_of=run.id)
        run.superseded_by = created.run_id
        s.add(run)
        s.commit()
    audit(run_id, "superseded", f"Re-run as {created.run_id[:8]} with current settings")
    audit(created.run_id, "rerun_of", f"Re-run of {run_id[:8]}")
    return created
