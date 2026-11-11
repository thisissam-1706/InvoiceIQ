from datetime import date, timedelta
from typing import Callable, Optional

from .. import db
from ..models import POConsumption
from . import SEVERITY_RANK, STAGES, Check, RunContext, StageResult, fmt_money, q2, sentence
from .explain import generate_text

EMAIL_CODES = {
    "MISSING_INVOICE_NUMBER",
    "MISSING_TOTAL",
    "ARITHMETIC_MISMATCH",
    "PO_MISSING",
    "PO_NOT_FOUND",
    "PRICE_VARIANCE_EXCEEDS_TOL",
}


def decide(findings: list[Check], never_auto_approve_on: list[str]) -> str:
    if any(f.severity == "block" for f in findings):
        return "REJECT"
    if any(f.severity == "review" for f in findings):
        return "HOLD"
    if any(f.code in never_auto_approve_on for f in findings):
        return "HOLD"
    return "APPROVE"


def _vendor(ctx: RunContext) -> str:
    if ctx.vendor:
        return ctx.vendor["name"]
    return ctx.invoice.vendor_name or "the vendor"


def _po(ctx: RunContext) -> str:
    return ctx.po["po_number"] if ctx.po else "the PO"


ACTIONS: dict[str, Callable[[Check, RunContext], str]] = {
    "DUPLICATE_INVOICE": lambda c, ctx: f"Do not pay. This invoice was already processed in run {c.data.get('run_id', '')[:8]}; let {_vendor(ctx)} know it was received once.",
    "VENDOR_INACTIVE": lambda c, ctx: f"Do not pay. Ask procurement whether {_vendor(ctx)} should be reactivated; otherwise return the invoice to the vendor.",
    "PO_CLOSED": lambda c, ctx: f"Do not pay against {_po(ctx)}, which is closed. Ask procurement whether a new PO is needed.",
    "BANK_DETAILS_MISMATCH": lambda c, ctx: f"Call {_vendor(ctx)} on the phone number in the vendor master (not the invoice) to confirm the bank change, then update the vendor record via the change-control process.",
    "PO_BUDGET_EXCEEDED": lambda c, ctx: f"Ask the PO owner to raise a change order for {ctx.money(c.data.get('overrun'))} or request a revised invoice from {_vendor(ctx)}.",
    "PO_INFERRED": lambda c, ctx: f"Confirm with the requester that this invoice belongs to {c.data.get('po_number')}, then approve it with an override note.",
    "VENDOR_NOT_FOUND": lambda c, ctx: "Route to vendor onboarding before payment (verified tax ID, W-9 and bank details).",
    "VENDOR_FUZZY_MATCH": lambda c, ctx: f"Confirm the invoice really comes from {_vendor(ctx)} before approving.",
    "TAX_ID_MISMATCH": lambda c, ctx: f"Verify {_vendor(ctx)}'s tax ID with the vendor before paying.",
    "PO_MISSING": lambda c, ctx: f"Ask {_vendor(ctx)} for the PO number, or ask the requester to raise a PO.",
    "PO_NOT_FOUND": lambda c, ctx: f"Check the PO number with {_vendor(ctx)}; it does not exist in the procurement system.",
    "PO_VENDOR_MISMATCH": lambda c, ctx: "Confirm which vendor the PO was issued to before paying.",
    "MISSING_INVOICE_NUMBER": lambda c, ctx: f"Request a corrected invoice with an invoice number from {_vendor(ctx)}.",
    "MISSING_TOTAL": lambda c, ctx: f"Ask {_vendor(ctx)} to confirm the total" + (f" (the lines add up to {ctx.money(c.data['suggested_total'])})" if c.data.get("suggested_total") is not None else "") + ".",
    "MISSING_INVOICE_DATE": lambda c, ctx: f"Ask {_vendor(ctx)} for the invoice date.",
    "ARITHMETIC_MISMATCH": lambda c, ctx: f"Request a corrected invoice from {_vendor(ctx)}; do not pay the printed total until the arithmetic is fixed.",
    "PRICE_VARIANCE_EXCEEDS_TOL": lambda c, ctx: f"Ask {_vendor(ctx)} to re-bill at the PO price, or have the buyer approve the new price with a PO amendment.",
    "TOTAL_VARIANCE_EXCEEDS_TOL": lambda c, ctx: "Reconcile the invoice total with the PO before paying.",
    "QTY_EXCEEDS_PO": lambda c, ctx: "Check whether the extra quantity was ordered; if so, the buyer should amend the PO.",
    "QTY_EXCEEDS_RECEIVED": lambda c, ctx: "Confirm receipt with the warehouse before paying for goods not yet received.",
    "UNMATCHED_LINE": lambda c, ctx: "Ask the buyer whether the unmatched lines were ordered.",
    "LOW_EXTRACTION_CONFIDENCE": lambda c, ctx: "Check the highlighted fields against the PDF before approving.",
    "POSSIBLE_DUPLICATE": lambda c, ctx: f"Compare with run {c.data.get('run_id', '')[:8]} and confirm this is not the same invoice.",
    "FUTURE_DATED": lambda c, ctx: "Confirm the invoice date with the vendor.",
    "AMOUNT_ABOVE_AUTO_LIMIT": lambda c, ctx: "Get sign-off from an approver with the right spending authority.",
}


def _sorted_findings(ctx: RunContext) -> list[Check]:
    return sorted(
        (c for c in ctx.findings if c.severity in ("block", "review")),
        key=lambda c: (-SEVERITY_RANK[c.severity], not c.critical, STAGES.index(c.stage) if c.stage in STAGES else 99),
    )


def build_actions(ctx: RunContext) -> list[dict]:
    seen, out = set(), []
    for c in _sorted_findings(ctx):
        if c.code in seen or c.code not in ACTIONS:
            continue
        seen.add(c.code)
        out.append({"code": c.code, "severity": c.severity, "text": sentence(ACTIONS[c.code](c, ctx))})
    return out


def _email_requests(ctx: RunContext) -> list[str]:
    reqs = []
    for c in _sorted_findings(ctx):
        if c.code == "MISSING_INVOICE_NUMBER":
            reqs.append("An invoice number. None is printed on the copy we received.")
        elif c.code == "MISSING_TOTAL":
            hint = f" The line items add up to {ctx.money(c.data['suggested_total'])}." if c.data.get("suggested_total") is not None else ""
            reqs.append("The invoice total, which is missing or unreadable on our copy." + hint)
        elif c.code == "ARITHMETIC_MISMATCH":
            reqs.append("A corrected invoice. " + c.message.replace("The invoice does not add up: ", "On our copy, ").rstrip("."))
        elif c.code == "PO_MISSING":
            reqs.append("The purchase order number this invoice relates to.")
        elif c.code == "PO_NOT_FOUND":
            reqs.append(f"The correct PO number. We could not find {c.data.get('po_number')} in our system.")
        elif c.code == "PRICE_VARIANCE_EXCEEDS_TOL":
            lines = "; ".join(
                f"{l['description']}: billed {ctx.money(l['invoice_price'])}, agreed {ctx.money(l['po_price'])}" for l in c.data.get("lines", [])
            )
            reqs.append(f"A revised invoice at the agreed PO prices ({lines}).")
    return reqs


def build_vendor_email(ctx: RunContext) -> Optional[dict]:
    if ctx.decision != "HOLD" or not ctx.vendor or not any(c.code in EMAIL_CODES for c in ctx.findings):
        return None
    inv = ctx.invoice
    ref = inv.invoice_number or (f"dated {inv.invoice_date.isoformat()}" if inv.invoice_date else "you sent us")
    subject = f"Invoice {inv.invoice_number or ''} – information needed before payment".replace("  ", " ")
    amount = f" for {ctx.money(inv.total)}" if inv.total is not None else ""
    dated = f" dated {inv.invoice_date.strftime('%b %-d, %Y')}" if inv.invoice_date and inv.invoice_number else ""
    bullets = "\n".join(f"- {r}" for r in _email_requests(ctx))
    quote = ctx.po["po_number"] if ctx.po else "your invoice number"
    body = (
        f"Hello {ctx.vendor['name']} billing team,\n\n"
        f"Thank you for invoice {ref}{dated}{amount}. Before we can schedule payment we need the following:\n\n"
        f"{bullets}\n\n"
        f"Please reply with a corrected invoice or the missing details and quote {quote}.\n\n"
        "Kind regards,\nAccounts Payable"
    )
    polished = generate_text(
        ctx,
        "Polish this accounts-payable email to a vendor so it is clear, polite and concise. Keep every fact, number "
        "and bullet point exactly; do not add new requests or facts; keep the greeting and sign-off. Return only the email body.\n\n"
        + body,
    )
    return {"to": f"{ctx.vendor['name']} (billing contact on file)", "subject": subject, "body": polished or body, "polished_by_llm": bool(polished)}


def record_consumption(run_id: str, po_number: str, amount, reason: str) -> None:
    with db.session() as s:
        s.add(POConsumption(po_number=po_number, run_id=run_id, amount=str(q2(amount)), reason=reason))
        s.commit()


def run(ctx: RunContext) -> StageResult:
    policy = ctx.config.policy
    ctx.decision = decide(ctx.findings, policy.never_auto_approve_on)
    forced = [c.code for c in ctx.findings if c.code in policy.never_auto_approve_on]

    if ctx.decision == "APPROVE":
        if ctx.po and ctx.invoice.pretax_subtotal is not None:
            record_consumption(ctx.run_id, ctx.po["po_number"], ctx.invoice.pretax_subtotal, "auto_approve")
        terms = ctx.vendor["payment_terms_days"] if ctx.vendor else 30
        ctx.payment_due_date = (ctx.invoice.invoice_date or date.today()) + timedelta(days=terms)

    actions = build_actions(ctx)
    email = build_vendor_email(ctx)
    ctx.actions = {
        "actions": actions,
        "primary": actions[0]["text"] if actions else None,
        "vendor_email": email,
        "payment_due_date": ctx.payment_due_date,
        "po_consumed": ctx.invoice.pretax_subtotal if ctx.decision == "APPROVE" and ctx.po else None,
    }

    counts = {sev: sum(1 for c in ctx.findings if c.severity == sev) for sev in ("block", "review", "warning", "info")}
    reason = ", ".join(f"{n} {sev}" for sev, n in counts.items() if n) or "no findings"
    summary = f"{ctx.decision} ({reason})"
    if ctx.decision == "APPROVE" and ctx.payment_due_date:
        summary += f"; payment due {ctx.payment_due_date.isoformat()}"
        if ctx.po:
            summary += f"; {fmt_money(ctx.invoice.pretax_subtotal, ctx.currency)} consumed on {ctx.po['po_number']}"
    return StageResult(
        summary,
        {
            "decision": ctx.decision,
            "rule": "block → REJECT, review → HOLD, otherwise APPROVE",
            "severity_counts": counts,
            "never_auto_approve_hits": forced,
            "actions": actions,
            "vendor_email": bool(email),
            "payment_due_date": ctx.payment_due_date,
        },
    )
