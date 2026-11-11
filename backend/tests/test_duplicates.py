import json
from datetime import date
from decimal import Decimal

from sqlmodel import select

from backend.app import db
from backend.app.models import InvoiceFingerprint
from backend.app.pipeline import duplicates

from .conftest import add_prior_run, codes, make_ctx

ACME = {"vendor_id": "V001", "name": "Acme Office Supplies Inc."}


def run(config, run_id="new", sha=None, **invoice):
    ctx = make_ctx(config, run_id=run_id, **invoice)
    if sha:
        ctx.sha256 = sha
    ctx.vendor = ACME
    ctx.current_stage = "duplicates"
    duplicates.run(ctx)
    return ctx


def test_reformatted_number_is_duplicate(fresh_db, config):
    add_prior_run("orig", "APPROVE", "V001", "INV1001", "4250.00", date(2026, 10, 3))
    ctx = run(config, invoice_number="INV 1001", invoice_number_norm="INV1001", total=Decimal("4250.00"), invoice_date=date(2026, 10, 3))
    finding = next(c for c in ctx.findings if c.code == "DUPLICATE_INVOICE")
    assert finding.severity == "block" and finding.data["run_id"] == "orig"


def test_identical_file_is_duplicate(fresh_db, config):
    add_prior_run("orig", "HOLD", "V001", "INV2000", "10.00", date(2026, 10, 3), sha="abc")
    ctx = run(config, sha="abc", invoice_number_norm="SOMETHINGELSE", total=Decimal("99.00"), invoice_date=date(2026, 10, 3))
    assert next(c for c in ctx.findings if c.code == "DUPLICATE_INVOICE").data["match"] == "exact_file"


def test_rejected_invoice_does_not_block_resubmission(fresh_db, config):
    rules = json.dumps({"findings": [{"code": "ARITHMETIC_MISMATCH"}]})
    add_prior_run("bad", "REJECT", "V001", "INV1001", "4250.00", date(2026, 10, 3), rules_json=rules)
    ctx = run(config, invoice_number_norm="INV1001", total=Decimal("4250.00"), invoice_date=date(2026, 10, 3))
    assert "DUPLICATE_INVOICE" not in codes(ctx)
    assert "RESUBMISSION" in codes(ctx)


def test_near_duplicate_within_window(fresh_db, config):
    add_prior_run("orig", "APPROVE", "V001", "INV10010", "4250.00", date(2026, 10, 3))
    near = run(config, invoice_number_norm="INV10011", total=Decimal("4250.00"), invoice_date=date(2026, 10, 10))
    assert "POSSIBLE_DUPLICATE" in codes(near)
    far = run(config, run_id="far", invoice_number_norm="INV10011", total=Decimal("4250.00"), invoice_date=date(2026, 10, 11))
    assert "POSSIBLE_DUPLICATE" not in codes(far)


def test_different_vendor_same_number_is_fine(fresh_db, config):
    add_prior_run("other", "APPROVE", "V002", "INV1001", "4250.00", date(2026, 10, 3))
    ctx = run(config, invoice_number_norm="INV1001", total=Decimal("4250.00"), invoice_date=date(2026, 10, 3))
    assert codes(ctx) == set()


def test_fingerprint_written(fresh_db, config):
    run(config, run_id="fp", invoice_number_norm="X1", total=Decimal("1.00"), invoice_date=date(2026, 10, 3))
    with db.session() as s:
        assert s.exec(select(InvoiceFingerprint).where(InvoiceFingerprint.run_id == "fp")).first() is not None
