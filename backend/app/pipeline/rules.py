from decimal import Decimal

from . import RunContext, StageResult, code_title, fmt_pct, jsonable, pct_text, q2


def check_price_variance(ctx: RunContext) -> None:
    tol = ctx.config.tolerance.unit_price_pct
    within, beyond = [], []
    for m in ctx.line_matches:
        if not m["price_checked"] or m["variance_pct"] is None:
            continue
        v = m["variance_pct"]
        if v == 0:
            continue
        entry = {
            "po_line_no": m["po_line_no"],
            "description": m["po_description"],
            "po_price": m["po_unit_price"],
            "invoice_price": m["invoice_unit_price"],
            "variance_pct": v,
        }
        text = f"{m['po_description']}: {ctx.money(m['invoice_unit_price'])} vs PO {ctx.money(m['po_unit_price'])} ({fmt_pct(v)})"
        (within if abs(v) <= tol else beyond).append((text, entry))
    if beyond:
        ctx.add(
            "PRICE_VARIANCE_EXCEEDS_TOL", "review",
            f"Unit price differs from the PO by more than the allowed ±{pct_text(tol)}: " + "; ".join(t for t, _ in beyond) + ".",
            data={"lines": [e for _, e in beyond], "tolerance": tol},
        )
    if within:
        ctx.add(
            "PRICE_VARIANCE_WITHIN_TOL", "info",
            f"Small price difference within the ±{pct_text(tol)} tolerance: " + "; ".join(t for t, _ in within) + ".",
            data={"lines": [e for _, e in within], "tolerance": tol},
        )
    if not beyond and not within and any(m["price_checked"] for m in ctx.line_matches):
        ctx.passed("PRICES_MATCH_PO", "All unit prices match the PO exactly.")


def check_total_variance(ctx: RunContext) -> None:
    inv = ctx.invoice
    priced = [m for m in ctx.line_matches if m["price_checked"] and m["invoice_qty"] is not None]
    if not ctx.po or ctx.po["is_blanket"] or not priced or inv.total is None:
        return
    tol = ctx.config.tolerance
    expected = sum((m["invoice_qty"] * m["po_unit_price"] for m in priced), Decimal("0")) + inv.tax_effective
    expected = q2(expected)
    allowed = q2(min(tol.total_abs, tol.total_pct * expected))
    gap = q2(inv.total - expected)
    data = {"expected": expected, "invoice_total": inv.total, "gap": gap, "allowed": allowed}
    if abs(gap) > allowed:
        ctx.add(
            "TOTAL_VARIANCE_EXCEEDS_TOL", "review",
            f"The invoice total {ctx.money(inv.total)} differs from the expected {ctx.money(expected)} (billed quantities at PO prices plus tax) "
            f"by {ctx.money(abs(gap))}; the allowed difference is {ctx.money(allowed)}.",
            data=data,
        )
    else:
        ctx.passed("TOTAL_WITHIN_TOL", f"Invoice total is within {ctx.money(allowed)} of the expected {ctx.money(expected)}.", data=data)


def check_amount_limit(ctx: RunContext) -> None:
    limit = ctx.config.policy.auto_approve_max_amount
    amount = ctx.invoice.total if ctx.invoice.total is not None else ctx.invoice.pretax_subtotal
    if amount is None:
        return
    if amount > limit:
        ctx.add(
            "AMOUNT_ABOVE_AUTO_LIMIT", "review",
            f"{ctx.money(amount)} is above the {ctx.money(limit)} auto-approval limit and needs a manual sign-off.",
            data={"amount": amount, "limit": limit},
        )
    else:
        ctx.passed("WITHIN_AUTO_LIMIT", f"Amount is within the {ctx.money(limit)} auto-approval limit.")


def run(ctx: RunContext) -> StageResult:
    check_price_variance(ctx)
    check_total_variance(ctx)
    check_amount_limit(ctx)
    mine = ctx.stage_checks(ctx.current_stage)
    flagged = [code_title(c.code) for c in mine if c.severity in ("review", "block")]
    summary = (
        f"Tolerance rules applied (price ±{pct_text(ctx.config.tolerance.unit_price_pct)}): "
        + (", ".join(flagged) if flagged else "all within policy")
    )
    return StageResult(summary, {"checks": [c.__dict__ for c in mine], "config_snapshot": jsonable(ctx.config)})
