import json
from collections import Counter
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from sqlmodel import select

from .. import db
from ..llm import build_client
from ..llm.cache import ResponseCache
from ..models import Run
from ..pipeline import CODE_LABELS, code_info, q2
from ..pipeline.orchestrator import worker
from ..schemas import ResetRequest
from ..settings import INBOX_DIR, SAMPLES_DIR, AppConfig, config_store, load_env

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health() -> dict:
    env = load_env()
    resolved = build_client()
    try:
        with db.session() as s:
            s.exec(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {
        "status": "ok" if db_ok and worker.alive else "degraded",
        "configured_provider": env.llm_provider,
        "provider": resolved.client.provider,
        "model": resolved.client.model,
        "provider_note": resolved.note,
        "cache_enabled": config_store.get().llm.cache_enabled,
        "cache_entries": ResponseCache().count(),
        "db_ok": db_ok,
        "worker_alive": worker.alive,
        "queue_size": worker.queue.qsize(),
        "current_run": worker.current,
        "inbox_dir": str(INBOX_DIR),
    }


def _known_codes() -> list[dict]:
    return [{"code": c, "label": l, **code_info(c)} for c, l in CODE_LABELS.items()]


@router.get("/settings")
def get_settings() -> dict:
    return {
        "config": json.loads(config_store.get().model_dump_json()),
        "known_codes": _known_codes(),
    }


@router.put("/settings")
def put_settings(body: AppConfig) -> dict:
    unknown = [c for c in body.policy.never_auto_approve_on if c not in CODE_LABELS]
    if unknown:
        raise HTTPException(422, f"Unknown finding codes: {', '.join(unknown)}")
    saved = config_store.update(body)
    return {"config": json.loads(saved.model_dump_json()), "known_codes": _known_codes()}


@router.post("/system/reset")
def reset(body: ResetRequest) -> dict:
    if not body.confirm:
        raise HTTPException(400, "Send {\"confirm\": true} to reset demo data")
    if worker.current or worker.queue.qsize():
        raise HTTPException(409, "Runs are still processing; wait for them to finish before resetting")
    db.reset_runtime_data()
    return {"ok": True}


@router.get("/samples")
def samples() -> list[dict]:
    manifest = SAMPLES_DIR / "manifest.json"
    if not manifest.exists():
        return []
    items = json.loads(manifest.read_text())
    with db.session() as s:
        for item in items:
            last = s.exec(select(Run).where(Run.file_name == item["file"]).order_by(Run.created_at.desc())).first()
            item["available"] = (SAMPLES_DIR / item["file"]).exists()
            item["last_run"] = (
                {"id": last.id, "decision": last.decision, "status": last.status, "overridden": last.decision_overridden}
                if last
                else None
            )
    return items


@router.get("/stats")
def stats() -> dict:
    with db.session() as s:
        runs = s.exec(select(Run).order_by(Run.created_at)).all()
    completed = [r for r in runs if r.status == "completed"]
    decisions = Counter(r.decision for r in completed)
    auto = [r for r in completed if r.decision == "APPROVE" and not r.decision_overridden]
    codes: Counter = Counter()
    for r in completed:
        for f in json.loads(r.rules_json or "{}").get("findings", []):
            if f["severity"] in ("review", "block", "warning"):
                codes[f["code"]] += 1
    durations = [r.duration_ms for r in completed if r.duration_ms]
    total_value = sum((Decimal(r.invoice_total) for r in completed if r.invoice_total), Decimal("0"))
    attention = [r for r in completed if r.decision == "HOLD" and not r.decision_overridden and not r.superseded_by]
    return {
        "total_runs": len(runs),
        "processed": len(completed),
        "failed": sum(1 for r in runs if r.status == "failed"),
        "in_progress": sum(1 for r in runs if r.status in ("queued", "running")),
        "approved": decisions.get("APPROVE", 0),
        "auto_approved": len(auto),
        "on_hold": len(attention),
        "rejected": decisions.get("REJECT", 0),
        "overridden": sum(1 for r in completed if r.decision_overridden),
        "auto_approve_rate": round(len(auto) / len(completed), 4) if completed else 0.0,
        "total_value": str(q2(total_value)),
        "avg_duration_ms": int(sum(durations) / len(durations)) if durations else 0,
        "top_findings": [{"code": c, "label": CODE_LABELS.get(c, c), **code_info(c), "count": n} for c, n in codes.most_common(5)],
        "recent": [
            {
                "id": r.id,
                "created_at": r.created_at,
                "file_name": r.file_name,
                "decision": r.decision,
                "status": r.status,
                "overridden": r.decision_overridden,
            }
            for r in runs[-20:]
        ],
        "needs_attention": [
            {
                "id": r.id,
                "created_at": r.created_at,
                "file_name": r.file_name,
                "vendor_name": r.vendor_name,
                "invoice_number": r.invoice_number,
                "invoice_total": r.invoice_total,
                "currency": r.currency,
                "codes": (codes_ := sorted(
                    {f["code"] for f in json.loads(r.rules_json or "{}").get("findings", []) if f["severity"] == "review"}
                )),
                "findings": [{"code": c, **code_info(c)} for c in codes_],
                "primary_action": (json.loads(r.suggested_action or "{}") or {}).get("primary"),
            }
            for r in attention
        ],
    }
