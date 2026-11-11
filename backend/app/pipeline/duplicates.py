import json
from datetime import date
from decimal import Decimal

from rapidfuzz import fuzz
from sqlmodel import select

from .. import db
from ..models import InvoiceFingerprint, Run
from . import CENT, RunContext, StageResult

NEAR_DUP_NUMBER_SIMILARITY = 85
NEAR_DUP_DATE_WINDOW_DAYS = 7


def _was_rejected_as_duplicate(run: Run) -> bool:
    if not run.rules_json:
        return False
    findings = json.loads(run.rules_json).get("findings", [])
    return any(f["code"] == "DUPLICATE_INVOICE" for f in findings)


def _prior_runs(s, ctx: RunContext) -> list[tuple[InvoiceFingerprint, Run]]:
    rows = s.exec(
        select(InvoiceFingerprint, Run)
        .where(InvoiceFingerprint.run_id == Run.id)
        .where(Run.id != ctx.run_id, Run.decision.is_not(None), Run.superseded_by.is_(None))
        .order_by(Run.created_at)
    ).all()
    return list(rows)


def run(ctx: RunContext) -> StageResult:
    inv = ctx.invoice
    vendor_id = ctx.vendor["vendor_id"] if ctx.vendor else None
    total = inv.total

    with db.session() as s:
        priors = _prior_runs(s, ctx)
        live = [(fp, r) for fp, r in priors if r.decision != "REJECT"]
        rejected = [(fp, r) for fp, r in priors if r.decision == "REJECT" and not _was_rejected_as_duplicate(r)]

        hit = None
        exact = next((r for fp, r in live if fp.exact_hash == ctx.sha256), None)
        if exact:
            hit = ("exact_file", exact)
            ctx.add(
                "DUPLICATE_INVOICE", "block",
                f"Identical file already processed in run {exact.id[:8]} ({exact.file_name}, decision {exact.decision}).",
                data={"run_id": exact.id, "match": "exact_file"},
            )

        if not hit and vendor_id and inv.invoice_number_norm:
            semantic = next(
                (r for fp, r in live if fp.vendor_id == vendor_id and fp.invoice_number_norm == inv.invoice_number_norm), None
            )
            if semantic:
                hit = ("same_vendor_and_number", semantic)
                ctx.add(
                    "DUPLICATE_INVOICE", "block",
                    f"This is a duplicate of invoice {semantic.invoice_number} from the same vendor, already processed in run "
                    f"{semantic.id[:8]} ({semantic.file_name}, decision {semantic.decision}). The layout and formatting differ, "
                    f"but both normalise to {inv.invoice_number_norm}.",
                    data={"run_id": semantic.id, "match": "vendor+invoice_number", "invoice_number_norm": inv.invoice_number_norm},
                )

        if not hit and vendor_id and total is not None and inv.invoice_date and inv.invoice_number_norm:
            for fp, r in live:
                if fp.vendor_id != vendor_id or fp.total_amount is None or not fp.invoice_date or not fp.invoice_number_norm:
                    continue
                same_total = abs(Decimal(fp.total_amount) - total) <= CENT
                days = abs((date.fromisoformat(fp.invoice_date) - inv.invoice_date).days)
                similarity = fuzz.ratio(fp.invoice_number_norm, inv.invoice_number_norm)
                if same_total and days <= NEAR_DUP_DATE_WINDOW_DAYS and similarity >= NEAR_DUP_NUMBER_SIMILARITY:
                    hit = ("near_duplicate", r)
                    ctx.add(
                        "POSSIBLE_DUPLICATE", "review",
                        f"Looks like a possible duplicate of {r.invoice_number} (run {r.id[:8]}): same vendor and total, dates {days} day(s) apart, "
                        f"invoice numbers {similarity:.0f}% similar.",
                        data={"run_id": r.id, "match": "near", "similarity": round(similarity, 1), "days_apart": days},
                    )
                    break

        if not hit:
            resub = next(
                (
                    r for fp, r in rejected
                    if fp.exact_hash == ctx.sha256
                    or (vendor_id and inv.invoice_number_norm and fp.vendor_id == vendor_id and fp.invoice_number_norm == inv.invoice_number_norm)
                ),
                None,
            )
            if resub:
                ctx.add(
                    "RESUBMISSION", "info",
                    f"Resubmission of an invoice rejected earlier in run {resub.id[:8]} for a non-duplicate reason; allowed to proceed.",
                    data={"run_id": resub.id},
                )
            else:
                ctx.passed("NO_DUPLICATE", f"No duplicate found among {len(live)} earlier invoice(s).")

        s.add(
            InvoiceFingerprint(
                run_id=ctx.run_id,
                vendor_id=vendor_id,
                invoice_number_norm=inv.invoice_number_norm,
                invoice_date=inv.invoice_date.isoformat() if inv.invoice_date else None,
                total_amount=str(total) if total is not None else None,
                exact_hash=ctx.sha256,
            )
        )
        s.commit()

    ctx.duplicate = {"compared_against": len(live), "match": hit[0] if hit else None, "run_id": hit[1].id if hit else None}
    if hit:
        return StageResult(f"Duplicate signal ({hit[0].replace('_', ' ')}) against run {hit[1].id[:8]}", ctx.duplicate)
    return StageResult(f"No duplicates among {len(live)} earlier invoice(s); fingerprint stored", ctx.duplicate)
