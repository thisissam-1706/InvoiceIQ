from datetime import date

from backend.app.pipeline import vendor_match

from .conftest import codes, make_ctx


def run(config, **invoice):
    ctx = make_ctx(config, **invoice)
    ctx.current_stage = "vendor_match"
    vendor_match.run(ctx)
    return ctx


def test_tax_id_match_beats_name(fresh_db, config):
    ctx = run(config, vendor_name="Totally Different Name", vendor_tax_id="12-3456789", currency="USD")
    assert ctx.vendor["vendor_id"] == "V001"
    assert ctx.vendor_match["method"] == "tax_id"
    assert codes(ctx) == set()


def test_alias_matches_by_name(fresh_db, config):
    ctx = run(config, vendor_name="ACME Supplies")
    assert ctx.vendor["vendor_id"] == "V001"
    assert ctx.vendor_match["status"] == "matched"


def test_fuzzy_band_holds(fresh_db, config):
    ctx = run(config, vendor_name="Greenleaf Caterers")
    assert ctx.vendor["vendor_id"] == "V005"
    assert "VENDOR_FUZZY_MATCH" in codes(ctx)


def test_unknown_vendor(fresh_db, config):
    ctx = run(config, vendor_name="Zenith Print House")
    assert ctx.vendor is None
    assert "VENDOR_NOT_FOUND" in codes(ctx)


def test_inactive_vendor_blocks(fresh_db, config):
    ctx = run(config, vendor_name="Orion Security Systems")
    finding = next(c for c in ctx.findings if c.code == "VENDOR_INACTIVE")
    assert finding.severity == "block"


def test_bank_change_is_critical(fresh_db, config):
    ctx = run(config, vendor_name="Greenleaf Catering Co.", bank_last4="8834")
    finding = next(c for c in ctx.findings if c.code == "BANK_DETAILS_MISMATCH")
    assert finding.critical and finding.severity == "review"
    assert "fraud" in finding.message


def test_matching_bank_passes(fresh_db, config):
    ctx = run(config, vendor_name="Greenleaf Catering Co.", bank_last4="2250", bank_routing="322271627")
    assert "BANK_DETAILS_MISMATCH" not in codes(ctx)


def test_tax_id_conflict_with_name_match(fresh_db, config):
    ctx = run(config, vendor_name="Delta Industrial Parts Co.", vendor_tax_id="99-0000000")
    assert ctx.vendor["vendor_id"] == "V004"
    assert "TAX_ID_MISMATCH" in codes(ctx)


def test_ambiguous_date_resolved_by_vendor_country(fresh_db, config):
    ctx = run(config, vendor_name="Acme Office Supplies Inc.", invoice_date=date(2026, 10, 3), invoice_date_raw="10/03/2026", date_ambiguous=True)
    assert ctx.invoice.invoice_date == date(2026, 10, 3)
    assert "US vendor" in ctx.invoice.date_reading
