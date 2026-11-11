from decimal import Decimal

from backend.app import db
from backend.app.models import POConsumption, Run
from backend.app.pipeline import po_match, vendor_match

from .conftest import codes, line, make_ctx

DELTA_LINES = [
    line("Ball bearing 6204-2RS", 400, "4.34", sku="DLT-BRG-6204"),
    line("Hex bolt M10x40, zinc", 2000, "0.62", sku="DLT-BLT-M10"),
    line("NBR gasket 50mm", 300, "19.88", sku="DLT-GSK-NBR"),
]


def run(config, vendor_name: str, **invoice):
    ctx = make_ctx(config, vendor_name=vendor_name, **invoice)
    ctx.current_stage = "vendor_match"
    vendor_match.run(ctx)
    ctx.current_stage = "po_match"
    po_match.run(ctx)
    return ctx


def consume(po: str, amount: str, run_id: str = "earlier") -> None:
    with db.session() as s:
        s.add(Run(id=run_id, file_name="x.pdf", file_path="/dev/null", status="completed", decision="APPROVE"))
        s.add(POConsumption(po_number=po, run_id=run_id, amount=amount))
        s.commit()


def test_explicit_po_exact_match(fresh_db, config):
    ctx = run(config, "Delta Industrial Parts Co.", po_number="PO-2026-0104", lines=DELTA_LINES, subtotal=Decimal("8940.00"))
    assert ctx.po["po_number"] == "PO-2026-0104"
    assert all(m["variance_pct"] == 0 for m in ctx.line_matches)
    assert not {"PO_BUDGET_EXCEEDED", "UNMATCHED_LINE", "QTY_EXCEEDS_PO"} & codes(ctx)


def test_unknown_and_closed_po(fresh_db, config):
    assert "PO_NOT_FOUND" in codes(run(config, "Delta Industrial Parts Co.", po_number="PO-2026-9999", lines=DELTA_LINES))
    closed = run(config, "Delta Industrial Parts Co.", po_number="PO-2026-0106", lines=[line("Ball bearing 6205-2RS", 500, "4.80")])
    assert next(c for c in closed.findings if c.code == "PO_CLOSED").severity == "block"


def test_po_of_another_vendor(fresh_db, config):
    ctx = run(config, "Acme Office Supplies Inc.", po_number="PO-2026-0104", lines=DELTA_LINES)
    assert "PO_VENDOR_MISMATCH" in codes(ctx)


def test_inferred_po_selected_and_flagged(fresh_db, config):
    ctx = run(config, "Delta Industrial Parts Co.", lines=DELTA_LINES, subtotal=Decimal("8940.00"))
    assert ctx.po["po_number"] == "PO-2026-0104"
    assert ctx.po_match["method"] == "inferred"
    assert ctx.po_match["score"] >= po_match.INFER_MIN_SCORE
    assert "PO_INFERRED" in codes(ctx)


def test_weak_inference_is_po_missing(fresh_db, config):
    ctx = run(config, "Delta Industrial Parts Co.", lines=[line("Forklift rental", 1, "900.00")], subtotal=Decimal("900.00"))
    assert ctx.po is None
    assert "PO_MISSING" in codes(ctx)


def test_blanket_budget_boundary(fresh_db, config):
    consume("PO-2026-0102", "11500.00")
    freight = lambda amt: [line("LTL freight services, Q4 lanes - partial billing", 1, amt)]  # noqa: E731
    exact = run(config, "Brightline Logistics LLC", po_number="PO-2026-0102", lines=freight("500.00"), subtotal=Decimal("500.00"))
    assert "PO_BUDGET_EXCEEDED" not in codes(exact)
    over = run(config, "Brightline Logistics LLC", po_number="PO-2026-0102", lines=freight("500.01"), subtotal=Decimal("500.01"))
    finding = next(c for c in over.findings if c.code == "PO_BUDGET_EXCEEDED")
    assert finding.data["overrun"] == Decimal("0.01")


def test_partial_consumption_is_info(fresh_db, config):
    ctx = run(config, "Brightline Logistics LLC", po_number="PO-2026-0102",
              lines=[line("LTL freight services", 1, "6000.00")], subtotal=Decimal("6000.00"))
    finding = next(c for c in ctx.findings if c.code == "PO_PARTIAL_CONSUMPTION")
    assert finding.severity == "info"
    assert ctx.budget["pct_consumed_after"] == Decimal("0.5000")


def test_quantity_above_received(fresh_db, config):
    lines = [line("Ball bearing 6204-2RS", 401, "4.34", sku="DLT-BRG-6204")]
    assert "QTY_EXCEEDS_PO" in codes(run(config, "Delta Industrial Parts Co.", po_number="PO-2026-0104", lines=lines))


def test_unmatched_line(fresh_db, config):
    lines = DELTA_LINES + [line("Expedited shipping surcharge", 1, "75.00")]
    assert "UNMATCHED_LINE" in codes(run(config, "Delta Industrial Parts Co.", po_number="PO-2026-0104", lines=lines))
