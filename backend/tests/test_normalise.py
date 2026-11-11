from datetime import date
from decimal import Decimal

import pytest

from backend.app.pipeline.normalise import (
    last4,
    normalise_extraction,
    normalise_invoice_number,
    normalise_po_number,
    parse_amount,
    parse_date,
)
from backend.app.schemas import InvoiceExtraction


@pytest.mark.parametrize("raw", ["INV-1001", "INV 1001", "inv#1001", "Inv. 1001", " INV/1001 ", "inv no. 1001"])
def test_invoice_number_variants_collapse(raw):
    assert normalise_invoice_number(raw) == "INV1001"


def test_invoice_number_keeps_distinct_numbers_distinct():
    assert normalise_invoice_number("INV-1001") != normalise_invoice_number("INV-1009")
    assert normalise_invoice_number(None) is None


@pytest.mark.parametrize("raw", ["PO-2026-0102", "PO 2026-0102", "po#2026/0102", "P.O. 2026 0102", "2026-0102"])
def test_po_number_variants(raw):
    assert normalise_po_number(raw) == "PO-2026-0102"


@pytest.mark.parametrize(
    "raw, expected",
    [("$4,250.00", Decimal("4250.00")), ("1 234.50", Decimal("1234.50")), ("(12.00)", Decimal("-12.00")), (None, None)],
)
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


def test_ambiguous_date_uses_country_order():
    us, reading, ambiguous = parse_date("10/03/2026", month_first=True)
    eu, _, _ = parse_date("10/03/2026", month_first=False)
    assert ambiguous and "month-first" in reading
    assert us == date(2026, 10, 3)
    assert eu == date(2026, 3, 10)


def test_unambiguous_dates():
    assert parse_date("25/10/2026")[0] == date(2026, 10, 25)
    assert parse_date("Oct 3, 2026")[:2] == (date(2026, 10, 3), "unambiguous")
    assert parse_date("2026-10-03")[0] == date(2026, 10, 3)
    assert parse_date("06 Oct 2026")[0] == date(2026, 10, 6)
    assert parse_date("not a date")[0] is None


def test_last4():
    assert last4("****4421") == "4421"
    assert last4("XXXXXX3098") == "3098"
    assert last4("12") is None


def _ext(**fields) -> InvoiceExtraction:
    data = {k: {"value": v, "confidence": 0.9} for k, v in fields.items() if k != "line_items"}
    data["line_items"] = fields.get("line_items", [])
    return InvoiceExtraction.model_validate(data)


def test_tax_included_backs_out_rate():
    inv = normalise_extraction(
        _ext(total="5250.00", tax_rate="5", tax_included_in_prices=True,
             line_items=[{"description": "Camera", "quantity": 10, "unit_price": 525, "amount": 5250}])
    )
    assert inv.tax_mode == "included"
    assert inv.tax_rate == Decimal("0.05")
    assert inv.pretax_subtotal == Decimal("5000.00")
    assert inv.tax_effective == Decimal("250.00")
    assert inv.lines[0].unit_price_pretax == Decimal("500.0000")


def test_separate_tax_uses_subtotal():
    inv = normalise_extraction(_ext(subtotal="3615.00", tax_amount="289.20", tax_rate="0.08", total="3904.20"))
    assert inv.tax_mode == "separate"
    assert inv.pretax_subtotal == Decimal("3615.00")
    assert inv.tax_effective == Decimal("289.20")


def test_subtotal_equals_total_without_tax_line_is_treated_inclusive():
    inv = normalise_extraction(_ext(subtotal="100.00", total="100.00"))
    assert inv.tax_mode == "included"
    assert inv.pretax_subtotal == Decimal("100.00")


def test_missing_subtotal_falls_back_to_line_sum():
    inv = normalise_extraction(
        _ext(tax_rate="0", line_items=[{"description": "a", "quantity": 2, "unit_price": "10.50", "amount": "21.00"},
                                       {"description": "b", "quantity": 1, "unit_price": "4", "amount": None}])
    )
    assert inv.lines[1].amount == Decimal("4.00")
    assert inv.pretax_subtotal == Decimal("25.00")
