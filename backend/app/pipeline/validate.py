from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from . import CENT, RunContext, StageResult, code_title, fmt_money, q2

REQUIRED_FIELDS = ["invoice_number", "invoice_date", "vendor_name", "total"]
FUTURE_GRACE_DAYS = 3
STALE_AFTER_DAYS = 180


def check_required(ctx: RunContext) -> None:
    inv = ctx.invoice
    if not inv.invoice_number:
        ctx.add("MISSING_INVOICE_NUMBER", "review", "No invoice number could be found on the document, so it cannot be tracked or checked for duplicates reliably.", field="invoice_number")
    else:
        ctx.passed("INVOICE_NUMBER_PRESENT", f"Invoice number {inv.invoice_number} present.", field="invoice_number")
    if not inv.invoice_date:
        ctx.add("MISSING_INVOICE_DATE", "review", "No readable invoice date was found.", field="invoice_date")
    else:
        ctx.passed("INVOICE_DATE_PRESENT", f"Invoice date {inv.invoice_date.isoformat()} present.", field="invoice_date")
    if not inv.vendor_name:
        ctx.add("MISSING_VENDOR_NAME", "review", "No vendor name could be read from the invoice.", field="vendor_name")
    else:
        ctx.passed("VENDOR_NAME_PRESENT", f"Vendor name '{inv.vendor_name}' present.", field="vendor_name")
    if inv.total is None:
        suggested = None
        if inv.line_sum is not None:
            suggested = q2(inv.line_sum + (inv.tax_effective if inv.tax_mode != "included" else Decimal("0")))
        msg = "The invoice total is missing or unreadable."
        if suggested is not None:
            msg += f" The line items add up to {fmt_money(suggested, ctx.currency)}, which can be used as a suggested total once the vendor confirms it."
        ctx.add("MISSING_TOTAL", "review", msg, field="total", data={"suggested_total": suggested})
    else:
        ctx.passed("TOTAL_PRESENT", f"Invoice total {ctx.money(inv.total)} present.", field="total")


def check_arithmetic(ctx: RunContext) -> None:
    inv = ctx.invoice
    problems: list[str] = []
    data: dict = {}
    for i, line in enumerate(inv.lines, 1):
        if line.quantity is not None and line.unit_price is not None and line.amount is not None:
            expected = q2(line.quantity * line.unit_price)
            if abs(expected - q2(line.amount)) > CENT:
                problems.append(
                    f"line {i} ({line.description[:40]}) shows {ctx.money(line.amount)} but {line.quantity} × {ctx.money(line.unit_price)} = {ctx.money(expected)}"
                )
    line_sum = inv.line_sum
    data["line_sum"] = line_sum
    if inv.tax_mode == "included":
        gross = inv.total if inv.total is not None else inv.subtotal
        if line_sum is not None and gross is not None and abs(q2(line_sum) - q2(gross)) > CENT:
            problems.append(f"the line amounts add up to {ctx.money(line_sum)} but the tax-inclusive total is {ctx.money(gross)}")
    else:
        if line_sum is not None and inv.subtotal is not None and abs(q2(line_sum) - q2(inv.subtotal)) > CENT:
            problems.append(f"the line amounts add up to {ctx.money(line_sum)} but the printed subtotal is {ctx.money(inv.subtotal)}")
            data["printed_subtotal"] = inv.subtotal
            data["difference"] = q2(inv.subtotal - line_sum)
        if inv.subtotal is not None and inv.total is not None:
            expected_total = q2(inv.subtotal + (inv.tax_amount or Decimal("0")))
            if abs(expected_total - q2(inv.total)) > CENT:
                problems.append(f"subtotal {ctx.money(inv.subtotal)} plus tax {ctx.money(inv.tax_amount or Decimal('0'))} is {ctx.money(expected_total)}, not the printed total {ctx.money(inv.total)}")
    if problems:
        ctx.add("ARITHMETIC_MISMATCH", "review", "The invoice does not add up: " + "; ".join(problems) + ".", data=data)
    elif inv.lines:
        ctx.passed("ARITHMETIC_OK", "Line amounts, subtotal, tax and total are internally consistent.", data=data)


def check_confidence(ctx: RunContext) -> None:
    threshold = ctx.config.extraction.min_confidence
    low = []
    for name in REQUIRED_FIELDS:
        f = getattr(ctx.extraction, name)
        if f.value is not None and f.confidence < threshold:
            low.append(f"{name} ({f.confidence:.2f})")
    if low:
        ctx.add(
            "LOW_EXTRACTION_CONFIDENCE", "review",
            f"Some key fields were read with low confidence (below {threshold:.2f}): {', '.join(low)}. A person should confirm them against the PDF.",
            data={"fields": low, "threshold": threshold},
        )
    else:
        ctx.passed("EXTRACTION_CONFIDENCE_OK", f"All key fields read with confidence ≥ {threshold:.2f}.")


def check_dates(ctx: RunContext, today: Optional[date] = None) -> None:
    inv = ctx.invoice
    if not inv.invoice_date:
        return
    today = today or date.today()
    if inv.invoice_date > today + timedelta(days=FUTURE_GRACE_DAYS):
        ctx.add("FUTURE_DATED", "review", f"The invoice is dated {inv.invoice_date.isoformat()}, which is in the future.", field="invoice_date")
    elif inv.invoice_date < today - timedelta(days=STALE_AFTER_DAYS):
        age = (today - inv.invoice_date).days
        ctx.add("STALE_INVOICE", "warning", f"The invoice is {age} days old, older than the {STALE_AFTER_DAYS}-day window.", field="invoice_date")
    else:
        ctx.passed("INVOICE_DATE_PLAUSIBLE", "Invoice date is within the accepted window.", field="invoice_date")


def run(ctx: RunContext, today: Optional[date] = None) -> StageResult:
    check_required(ctx)
    check_arithmetic(ctx)
    check_confidence(ctx)
    check_dates(ctx, today)
    findings = [c for c in ctx.stage_checks(ctx.current_stage) if c.is_finding]
    passed = len(ctx.stage_checks(ctx.current_stage)) - len(findings)
    summary = (
        f"{passed} checks passed" + (f", {len(findings)} issue{'s' if len(findings) != 1 else ''}: " + ", ".join(code_title(f.code) for f in findings) if findings else ", document is internally consistent")
    )
    return StageResult(summary, {"checks": [c.__dict__ for c in ctx.stage_checks(ctx.current_stage)]})
