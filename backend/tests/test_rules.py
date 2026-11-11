from decimal import Decimal

from backend.app.pipeline import Check, rules
from backend.app.pipeline.decision import decide

from .conftest import codes, make_ctx


def match(po_price: str, inv_price: str, qty: int = 100, blanket: bool = False) -> dict:
    po, inv = Decimal(po_price), Decimal(inv_price)
    return {
        "po_line_no": 1,
        "po_description": "Widget",
        "po_unit_price": po,
        "invoice_unit_price": inv,
        "invoice_qty": Decimal(qty),
        "variance_pct": ((inv - po) / po).quantize(Decimal("0.0001")),
        "price_checked": not blanket,
    }


def run(config, matches: list[dict], total: str, tax: str = "0", blanket: bool = False):
    ctx = make_ctx(config, total=Decimal(total), tax_effective=Decimal(tax))
    ctx.po = {"po_number": "PO-1", "is_blanket": blanket}
    ctx.line_matches = matches
    ctx.current_stage = "rules"
    rules.run(ctx)
    return ctx


def test_price_variance_exactly_at_tolerance_is_info(config):
    ctx = run(config, [match("10.00", "10.20")], "1020.00")
    finding = next(c for c in ctx.findings if c.code == "PRICE_VARIANCE_WITHIN_TOL")
    assert finding.severity == "info"
    assert "PRICE_VARIANCE_EXCEEDS_TOL" not in codes(ctx)


def test_price_variance_just_over_tolerance_holds(config):
    ctx = run(config, [match("100.00", "102.01", qty=1)], "102.01")
    assert "PRICE_VARIANCE_EXCEEDS_TOL" in codes(ctx)


def test_exact_prices_pass(config):
    ctx = run(config, [match("10.00", "10.00")], "1000.00")
    assert codes(ctx) == set()


def test_total_variance_boundary(config):
    # expected 1000 + 80 tax; allowance = min(25, 1% of 1080) = 10.80
    at_limit = run(config, [match("10.00", "10.00")], "1090.80", tax="80.00")
    assert "TOTAL_VARIANCE_EXCEEDS_TOL" not in codes(at_limit)
    over = run(config, [match("10.00", "10.00")], "1090.81", tax="80.00")
    assert "TOTAL_VARIANCE_EXCEEDS_TOL" in codes(over)


def test_blanket_po_skips_price_and_total_checks(config):
    ctx = run(config, [match("12000.00", "6000.00", qty=1, blanket=True)], "6000.00", blanket=True)
    assert codes(ctx) == set()


def test_auto_approve_limit(config):
    config.policy.auto_approve_max_amount = Decimal("1000")
    assert "AMOUNT_ABOVE_AUTO_LIMIT" not in codes(run(config, [match("10.00", "10.00")], "1000.00"))
    assert "AMOUNT_ABOVE_AUTO_LIMIT" in codes(run(config, [match("10.00", "10.00")], "1000.01"))


def test_decision_policy():
    info = Check("PRICE_VARIANCE_WITHIN_TOL", "info", "")
    review = Check("PO_BUDGET_EXCEEDED", "review", "")
    block = Check("DUPLICATE_INVOICE", "block", "")
    assert decide([], []) == "APPROVE"
    assert decide([info], []) == "APPROVE"
    assert decide([info, review], []) == "HOLD"
    assert decide([review, block], []) == "REJECT"
    assert decide([Check("BANK_DETAILS_MISMATCH", "info", "")], ["BANK_DETAILS_MISMATCH"]) == "HOLD"
