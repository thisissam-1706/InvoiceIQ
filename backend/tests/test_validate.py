from datetime import date
from decimal import Decimal

from backend.app.pipeline import validate

from .conftest import codes, line, make_ctx

TODAY = date(2026, 11, 6)
GOOD = {
    "invoice_number": "INV-1",
    "invoice_date": date(2026, 10, 3),
    "vendor_name": "Acme",
    "subtotal": Decimal("100.00"),
    "tax_amount": Decimal("8.00"),
    "total": Decimal("108.00"),
    "lines": [line("Widget", 10, "10.00")],
}
CONFIDENT = {k: {"value": "1" if k == "total" else "x", "confidence": 0.95} for k in validate.REQUIRED_FIELDS}


def run(config, extraction=None, **overrides):
    ctx = make_ctx(config, extraction=extraction or CONFIDENT, **{**GOOD, **overrides})
    ctx.current_stage = "validate"
    validate.run(ctx, today=TODAY)
    return ctx


def test_clean_invoice_has_no_findings(config):
    ctx = run(config)
    assert codes(ctx) == set()
    assert any(c.code == "ARITHMETIC_OK" for c in ctx.checks)


def test_subtotal_mismatch_names_the_numbers(config):
    ctx = run(config, subtotal=Decimal("120.00"), total=Decimal("128.00"))
    finding = next(c for c in ctx.findings if c.code == "ARITHMETIC_MISMATCH")
    assert "$100.00" in finding.message and "$120.00" in finding.message


def test_line_math_error_detected(config):
    ctx = run(config, lines=[line("Widget", 10, "10.00", amount="99.00")], subtotal=Decimal("99.00"), total=Decimal("107.00"))
    assert "ARITHMETIC_MISMATCH" in codes(ctx)


def test_one_cent_rounding_is_tolerated(config):
    ctx = run(config, total=Decimal("108.01"))
    assert "ARITHMETIC_MISMATCH" not in codes(ctx)
    ctx = run(config, total=Decimal("108.02"))
    assert "ARITHMETIC_MISMATCH" in codes(ctx)


def test_missing_total_suggests_line_sum(config):
    ctx = run(config, total=None, subtotal=None, tax_amount=None, tax_effective=Decimal("0"))
    finding = next(c for c in ctx.findings if c.code == "MISSING_TOTAL")
    assert finding.data["suggested_total"] == Decimal("100.00")


def test_missing_invoice_number(config):
    assert "MISSING_INVOICE_NUMBER" in codes(run(config, invoice_number=None))


def test_low_confidence_threshold_is_inclusive(config):
    at_threshold = {**CONFIDENT, "total": {"value": "108", "confidence": 0.70}}
    below = {**CONFIDENT, "total": {"value": "108", "confidence": 0.69}}
    assert "LOW_EXTRACTION_CONFIDENCE" not in codes(run(config, extraction=at_threshold))
    assert "LOW_EXTRACTION_CONFIDENCE" in codes(run(config, extraction=below))


def test_future_and_stale_dates(config):
    assert "FUTURE_DATED" not in codes(run(config, invoice_date=date(2026, 11, 9)))
    assert "FUTURE_DATED" in codes(run(config, invoice_date=date(2026, 11, 10)))
    stale = run(config, invoice_date=date(2026, 4, 1))
    assert next(c for c in stale.findings if c.code == "STALE_INVOICE").severity == "warning"
