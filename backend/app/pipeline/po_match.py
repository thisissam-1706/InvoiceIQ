import json
from decimal import Decimal
from typing import Optional

from rapidfuzz import fuzz
from sqlmodel import select

from .. import db
from ..models import GoodsReceipt, POConsumption, POLine, PurchaseOrder, Run
from . import InvoiceLine, RunContext, StageResult, fmt_pct, q2

LINE_MATCH_THRESHOLD = 80
INFER_MIN_SCORE = 0.80
INFER_MIN_LEAD = 0.15
SERVICE_UOMS = {"lot", "month"}


def load_po(s, po_number: str) -> Optional[dict]:
    po = s.get(PurchaseOrder, po_number)
    if po is None:
        return None
    lines = s.exec(select(POLine).where(POLine.po_number == po_number).order_by(POLine.line_no)).all()
    receipts = {
        r.line_no: Decimal(r.received_qty)
        for r in s.exec(select(GoodsReceipt).where(GoodsReceipt.po_number == po_number)).all()
    }
    consumption = s.exec(select(POConsumption).where(POConsumption.po_number == po_number)).all()
    consumed = sum((Decimal(c.amount) for c in consumption), Decimal("0"))

    billed: dict[int, Decimal] = {}
    for c in consumption:
        run = s.get(Run, c.run_id)
        if run and run.matching_json:
            for m in json.loads(run.matching_json).get("line_matches", []):
                if m.get("po_line_no") is not None and m.get("invoice_qty") is not None:
                    billed[m["po_line_no"]] = billed.get(m["po_line_no"], Decimal("0")) + Decimal(m["invoice_qty"])

    total = Decimal(po.total_amount)
    line_dicts = [
        {
            "line_no": l.line_no,
            "sku": l.sku,
            "description": l.description,
            "quantity": Decimal(l.quantity),
            "unit_price": Decimal(l.unit_price),
            "uom": l.uom,
            "received_qty": receipts.get(l.line_no),
            "billed_qty": billed.get(l.line_no, Decimal("0")),
        }
        for l in lines
    ]
    return {
        "po_number": po.po_number,
        "vendor_id": po.vendor_id,
        "status": po.status,
        "issue_date": po.issue_date,
        "total": total,
        "consumed": consumed,
        "remaining": total - consumed,
        "lines": line_dicts,
        "is_blanket": len(line_dicts) == 1 and line_dicts[0]["uom"] == "lot",
    }


def line_score(inv_line: InvoiceLine, po_line: dict) -> tuple[float, str]:
    if inv_line.sku and po_line["sku"] and inv_line.sku.upper() == po_line["sku"].upper():
        return 100.0, "sku"
    return float(fuzz.token_set_ratio(inv_line.description.lower(), po_line["description"].lower())), "description"


def match_lines(inv_lines: list[InvoiceLine], po_lines: list[dict]) -> tuple[list[tuple[int, int, float, str]], list[int]]:
    """Greedy best-first pairing; returns ([(inv_idx, po_idx, score, method)], unmatched invoice indexes)."""
    scored = []
    for i, il in enumerate(inv_lines):
        for j, pl in enumerate(po_lines):
            score, method = line_score(il, pl)
            if score >= LINE_MATCH_THRESHOLD:
                scored.append((score, i, j, method))
    scored.sort(key=lambda t: (-t[0], t[1], t[2]))
    used_inv, used_po, pairs = set(), set(), []
    for score, i, j, method in scored:
        if i in used_inv or j in used_po:
            continue
        used_inv.add(i)
        used_po.add(j)
        pairs.append((i, j, score, method))
    pairs.sort()
    unmatched = [i for i in range(len(inv_lines)) if i not in used_inv]
    return pairs, unmatched


def amount_proximity(amount: Optional[Decimal], remaining: Decimal) -> float:
    if amount is None or remaining <= 0:
        return 0.0
    return float(1 - min(Decimal(1), abs(amount - remaining) / remaining))


def score_candidate(inv_lines: list[InvoiceLine], amount: Optional[Decimal], po: dict) -> dict:
    if inv_lines and po["lines"]:
        best = [max(line_score(il, pl)[0] for pl in po["lines"]) for il in inv_lines]
        line_match = sum(best) / len(best) / 100
    else:
        line_match = 0.0
    proximity = amount_proximity(amount, po["remaining"])
    return {
        "po_number": po["po_number"],
        "line_match_score": round(line_match, 3),
        "amount_proximity_score": round(proximity, 3),
        "score": round(0.6 * line_match + 0.4 * proximity, 3),
    }


def _select_po(ctx: RunContext, s) -> Optional[dict]:
    inv = ctx.invoice
    if inv.po_number:
        po = load_po(s, inv.po_number)
        ctx.po_match = {"method": "explicit", "reference": inv.po_reference_raw, "normalised": inv.po_number}
        if po is None:
            ctx.add("PO_NOT_FOUND", "review", f"The invoice quotes PO {inv.po_number}, but no such purchase order exists.", data={"po_number": inv.po_number})
            return None
        if ctx.vendor and po["vendor_id"] != ctx.vendor["vendor_id"]:
            ctx.add(
                "PO_VENDOR_MISMATCH", "review",
                f"PO {po['po_number']} belongs to vendor {po['vendor_id']}, not {ctx.vendor['name']} ({ctx.vendor['vendor_id']}).",
            )
        else:
            ctx.passed("PO_FOUND", f"PO {po['po_number']} quoted on the invoice exists and belongs to this vendor.")
        if po["status"] in ("closed", "cancelled"):
            ctx.add("PO_CLOSED", "block", f"PO {po['po_number']} is {po['status']}; no further invoices can be paid against it.")
        return po

    if not ctx.vendor:
        ctx.po_match = {"method": "none"}
        ctx.add("PO_MISSING", "review", "No PO number on the invoice, and with an unknown vendor there are no purchase orders to match against.")
        return None

    open_pos = s.exec(
        select(PurchaseOrder).where(PurchaseOrder.vendor_id == ctx.vendor["vendor_id"], PurchaseOrder.status == "open")
    ).all()
    candidates = sorted(
        (score_candidate(inv.lines, inv.pretax_subtotal, load_po(s, p.po_number)) for p in open_pos),
        key=lambda c: -c["score"],
    )
    ctx.po_match = {"method": "inferred", "candidates": candidates}
    best = candidates[0] if candidates else None
    runner_up = candidates[1]["score"] if len(candidates) > 1 else 0.0
    if best and best["score"] >= INFER_MIN_SCORE and best["score"] - runner_up >= INFER_MIN_LEAD:
        ctx.po_match["score"] = best["score"]
        ctx.add(
            "PO_INFERRED", "review",
            f"No PO number is printed, so the system inferred {best['po_number']} (score {best['score']:.2f}: line match "
            f"{best['line_match_score']:.2f}, amount fit {best['amount_proximity_score']:.2f}, "
            f"{len(candidates)} open PO{'s' if len(candidates) != 1 else ''} considered). Inferred POs always need a person to confirm.",
            data={"po_number": best["po_number"], **best, "runner_up": runner_up},
        )
        return load_po(s, best["po_number"])
    ctx.po_match["method"] = "none"
    detail = f" Best candidate {best['po_number']} scored only {best['score']:.2f}." if best else " The vendor has no open POs."
    ctx.add("PO_MISSING", "review", "No PO number is printed and no open PO could be matched with confidence." + detail)
    return None


def _check_lines(ctx: RunContext, po: dict) -> None:
    inv = ctx.invoice
    pairs, unmatched = match_lines(inv.lines, po["lines"])
    over_po, over_received = [], []
    ctx.line_matches = []
    for i, j, score, method in pairs:
        il, pl = inv.lines[i], po["lines"][j]
        unit = il.unit_price_pretax if il.unit_price_pretax is not None else il.unit_price
        variance = (unit - pl["unit_price"]) / pl["unit_price"] if unit is not None and pl["unit_price"] else None
        qty = il.quantity
        row = {
            "invoice_line": i + 1,
            "description": il.description,
            "sku": il.sku,
            "po_line_no": pl["line_no"],
            "po_description": pl["description"],
            "po_sku": pl["sku"],
            "match_method": method,
            "match_score": round(score, 1),
            "uom": pl["uom"],
            "invoice_qty": qty,
            "po_qty": pl["quantity"],
            "already_billed_qty": pl["billed_qty"],
            "received_qty": pl["received_qty"],
            "invoice_unit_price": unit,
            "po_unit_price": pl["unit_price"],
            "variance_pct": variance.quantize(Decimal("0.0001")) if variance is not None else None,
            "line_amount": il.amount,
            "price_checked": not po["is_blanket"],
        }
        ctx.line_matches.append(row)
        if po["is_blanket"] or qty is None:
            continue
        cumulative = qty + pl["billed_qty"]
        label = f"line {pl['line_no']} ({pl['description']})"
        if cumulative > pl["quantity"]:
            over_po.append(f"{label}: {cumulative:g} billed incl. earlier invoices vs {pl['quantity']:g} ordered")
        elif pl["uom"] not in SERVICE_UOMS and pl["received_qty"] is not None and cumulative > pl["received_qty"]:
            over_received.append(f"{label}: {cumulative:g} billed vs {pl['received_qty']:g} received")

    if over_po:
        ctx.add("QTY_EXCEEDS_PO", "review", "Billed quantity exceeds the ordered quantity on " + "; ".join(over_po) + ".")
    if over_received:
        ctx.add("QTY_EXCEEDS_RECEIVED", "review", "Billed quantity exceeds goods received on " + "; ".join(over_received) + ".")
    if not over_po and not over_received and pairs and not po["is_blanket"]:
        ctx.passed("QTY_WITHIN_PO_AND_RECEIPTS", "Billed quantities are within ordered and received quantities.")
    if unmatched:
        names = ", ".join(f"'{inv.lines[i].description}'" for i in unmatched)
        ctx.add("UNMATCHED_LINE", "review", f"{len(unmatched)} invoice line(s) do not correspond to any line on {po['po_number']}: {names}.")
    elif pairs:
        ctx.passed("ALL_LINES_MATCHED", f"All {len(pairs)} invoice line(s) matched to {po['po_number']}.")


def _check_budget(ctx: RunContext, po: dict) -> None:
    amount = ctx.invoice.pretax_subtotal
    if amount is None:
        return
    tol = ctx.config.tolerance
    remaining = po["remaining"]
    # Itemised POs get the same small slack as the total tolerance so a within-tolerance price
    # difference is not double-penalised; blanket POs only get po_overrun_pct.
    slack = Decimal("0") if po["is_blanket"] else min(tol.total_abs, tol.total_pct * po["total"])
    allowed = max(remaining, Decimal("0")) * (1 + tol.po_overrun_pct) + slack
    overrun = q2(amount - remaining)
    after = remaining - amount
    pct_used = (po["consumed"] + amount) / po["total"] if po["total"] else Decimal("0")
    ctx.budget = {
        "po_total": po["total"],
        "consumed_before": po["consumed"],
        "this_invoice": amount,
        "remaining_before": remaining,
        "remaining_after": after,
        "allowed": q2(allowed),
        "overrun": overrun if overrun > 0 else Decimal("0"),
        "pct_consumed_after": pct_used.quantize(Decimal("0.0001")),
        "is_blanket": po["is_blanket"],
    }
    if amount > allowed:
        ctx.add(
            "PO_BUDGET_EXCEEDED", "review",
            f"{po['po_number']} has a total of {ctx.money(po['total'])}, of which {ctx.money(po['consumed'])} is already consumed, "
            f"leaving {ctx.money(remaining)}. This invoice's pre-tax amount of {ctx.money(amount)} would exceed it by {ctx.money(overrun)}.",
            data={k: ctx.budget[k] for k in ("po_total", "consumed_before", "this_invoice", "overrun")},
        )
    elif after > Decimal("0.01"):
        ctx.add(
            "PO_PARTIAL_CONSUMPTION", "info",
            f"This invoice brings {po['po_number']} to {pct_used * 100:.1f}% consumed ({ctx.money(po['consumed'] + amount)} of {ctx.money(po['total'])}); {ctx.money(after)} remains.",
            data={"pct_consumed_after": ctx.budget["pct_consumed_after"]},
        )
    else:
        ctx.passed("PO_BUDGET_OK", f"Invoice fits the remaining PO budget of {ctx.money(remaining)}.")


def run(ctx: RunContext) -> StageResult:
    with db.session() as s:
        po = _select_po(ctx, s)
    if po is None:
        return StageResult("No purchase order selected", {"po_match": ctx.po_match})
    ctx.po = po
    _check_lines(ctx, po)
    if po["status"] not in ("closed", "cancelled"):
        _check_budget(ctx, po)

    how = ctx.po_match["method"]
    score = f", score {ctx.po_match['score']:.2f}" if ctx.po_match.get("score") is not None else ""
    remaining_after = ctx.budget.get("remaining_after")
    budget_note = f"; remaining after this invoice {ctx.money(remaining_after)}" if remaining_after is not None else ""
    variances = [m["variance_pct"] for m in ctx.line_matches if m["variance_pct"] is not None and m["price_checked"]]
    worst = max(variances, key=abs) if variances else None
    var_note = f"; worst price variance {fmt_pct(worst)}" if worst else ""
    return StageResult(
        f"Matched {po['po_number']} ({how}{score}); {len(ctx.line_matches)} line(s){var_note}{budget_note}",
        {"po_match": ctx.po_match, "po_number": po["po_number"], "line_matches": ctx.line_matches, "budget": ctx.budget},
    )
