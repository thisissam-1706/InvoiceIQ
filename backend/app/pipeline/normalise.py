import re
from datetime import date
from decimal import Decimal
from typing import Optional

from dateutil import parser as dateparser

from ..schemas import InvoiceExtraction
from . import InvoiceLine, NormalisedInvoice, RunContext, StageResult, q2, to_decimal

MONTH_FIRST_COUNTRIES = {"US", "PH", "CA", "FM"}
_AMBIGUOUS_NUMERIC = re.compile(r"^\s*(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})\s*$")


def normalise_invoice_number(raw: Optional[str]) -> Optional[str]:
    """'INV-1001', 'INV 1001', 'inv#1001' and 'Inv No. 1001' all become 'INV1001'."""
    if not raw:
        return None
    s = raw.upper()
    s = re.sub(r"\bNO\.", "", s)
    s = re.sub(r"[#\s\-./\\_:]", "", s)
    return s or None


def normalise_po_number(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    m = re.search(r"(\d{4})\D{0,3}(\d{3,4})\b", raw)
    if not m:
        return re.sub(r"\s+", "", raw.upper()) or None
    return f"PO-{m.group(1)}-{int(m.group(2)):04d}"


def parse_amount(raw) -> Optional[Decimal]:
    if raw is None:
        return None
    if isinstance(raw, Decimal):
        return raw
    s = re.sub(r"[^\d.\-()]", "", str(raw))
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    return to_decimal(s)


def parse_date(raw: Optional[str], month_first: bool = True) -> tuple[Optional[date], Optional[str], bool]:
    """Returns (date, how it was read, whether the reading was ambiguous)."""
    if not raw:
        return None, None, False
    m = _AMBIGUOUS_NUMERIC.match(raw)
    ambiguous = False
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a > 12 and b <= 12:
            month_first, reading = False, "day-first (first number > 12)"
        elif b > 12 and a <= 12:
            month_first, reading = True, "month-first (second number > 12)"
        elif a == b:
            reading = "unambiguous (day equals month)"
        else:
            ambiguous = True
            reading = "ambiguous; read month-first" if month_first else "ambiguous; read day-first"
    else:
        reading = "unambiguous"
    try:
        parsed = dateparser.parse(raw, dayfirst=not month_first, fuzzy=True).date()
    except (ValueError, OverflowError):
        return None, f"could not parse '{raw}'", False
    return parsed, reading, ambiguous


def last4(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    return digits[-4:] if len(digits) >= 4 else None


def normalise_extraction(ext: InvoiceExtraction, month_first: bool = True) -> NormalisedInvoice:
    inv = NormalisedInvoice()
    inv.vendor_name = ext.vendor_name.value
    inv.vendor_tax_id = ext.vendor_tax_id.value
    inv.vendor_address = ext.vendor_address.value
    inv.invoice_number = ext.invoice_number.value
    inv.invoice_number_norm = normalise_invoice_number(ext.invoice_number.value)
    inv.invoice_date_raw = ext.invoice_date.value
    inv.invoice_date, inv.date_reading, inv.date_ambiguous = parse_date(ext.invoice_date.value, month_first)
    inv.due_date_raw = ext.due_date.value
    inv.due_date, _, _ = parse_date(ext.due_date.value, month_first)
    inv.po_reference_raw = ext.po_reference.value
    inv.po_number = normalise_po_number(ext.po_reference.value)
    inv.reference_notes = ext.reference_notes.value
    currency = (ext.currency.value or "").strip().upper()
    inv.currency = {"$": "USD", "US$": "USD", "€": "EUR", "£": "GBP"}.get(currency, currency) or None
    inv.subtotal = parse_amount(ext.subtotal.value)
    inv.tax_amount = parse_amount(ext.tax_amount.value)
    rate = parse_amount(ext.tax_rate.value)
    inv.tax_rate = rate / 100 if rate is not None and rate > 1 else rate
    inv.total = parse_amount(ext.total.value)
    inv.bank_last4 = last4(ext.bank_account_last4.value)
    inv.bank_routing = re.sub(r"\D", "", ext.bank_routing.value or "") or None
    inv.remit_notes = ext.remit_notes.value
    inv.lines = [
        InvoiceLine(
            description=l.description,
            sku=(l.sku or "").strip().upper() or None,
            quantity=l.quantity,
            unit_price=l.unit_price,
            amount=l.amount if l.amount is not None else (
                q2(l.quantity * l.unit_price) if l.quantity is not None and l.unit_price is not None else None
            ),
        )
        for l in ext.line_items
    ]
    _resolve_tax(inv, ext.tax_included_in_prices.value)
    return inv


def _resolve_tax(inv: NormalisedInvoice, included_flag: Optional[bool]) -> None:
    """Work out the pre-tax subtotal the PO should be compared against (POs are pre-tax)."""
    line_sum = inv.line_sum
    no_tax_line = inv.tax_amount is None and inv.tax_rate is None
    included = included_flag is True or (
        inv.subtotal is not None and inv.total is not None and inv.subtotal == inv.total and no_tax_line
    )

    if included:
        inv.tax_mode = "included"
        gross = inv.total if inv.total is not None else (inv.subtotal if inv.subtotal is not None else line_sum)
        if gross is None:
            inv.tax_note = "Tax-inclusive prices, but no gross amount was found."
            return
        if inv.tax_rate:
            factor = 1 + inv.tax_rate
            inv.pretax_subtotal = q2(gross / factor)
            inv.tax_note = f"Prices include tax; backed out {inv.tax_rate * 100:.4g}% as amount / (1 + rate)."
        elif inv.tax_amount:
            factor = gross / (gross - inv.tax_amount) if gross != inv.tax_amount else Decimal("1")
            inv.pretax_subtotal = q2(gross - inv.tax_amount)
            inv.tax_note = "Prices include tax; subtracted the printed tax amount."
        else:
            factor = Decimal("1")
            inv.pretax_subtotal = gross
            inv.tax_note = "Treated as tax-inclusive with no tax shown; pre-tax equals the gross amount."
        inv.tax_effective = q2(gross - inv.pretax_subtotal)
        for line in inv.lines:
            if line.unit_price is not None:
                line.unit_price_pretax = (line.unit_price / factor).quantize(Decimal("0.0001"))
        return

    base = inv.subtotal if inv.subtotal is not None else line_sum
    if inv.tax_amount is not None:
        tax = inv.tax_amount
    elif inv.tax_rate is not None and base is not None:
        tax = q2(base * inv.tax_rate)
    else:
        tax = Decimal("0")
    inv.tax_mode = "separate" if not no_tax_line else "none"
    inv.tax_effective = tax
    inv.pretax_subtotal = base
    if base is None and inv.total is not None:
        inv.pretax_subtotal = inv.total - tax
    inv.tax_note = (
        "Tax shown as a separate line; PO compared against the pre-tax subtotal."
        if inv.tax_mode == "separate"
        else "No tax shown on the invoice."
    )
    if inv.subtotal is None and line_sum is not None:
        inv.tax_note += " Subtotal not printed; used the sum of line amounts."
    for line in inv.lines:
        line.unit_price_pretax = line.unit_price


def run(ctx: RunContext) -> StageResult:
    inv = normalise_extraction(ctx.extraction)
    ctx.invoice = inv
    if inv.date_ambiguous:
        inv.date_reading += " (US default; re-checked once the vendor is known)"

    parts = []
    if inv.invoice_number:
        parts.append(f"invoice # {inv.invoice_number} → {inv.invoice_number_norm}")
    if inv.invoice_date:
        parts.append(f"date {inv.invoice_date.isoformat()}")
    if inv.pretax_subtotal is not None:
        parts.append(f"pre-tax {inv.pretax_subtotal:,.2f}")
    parts.append(f"tax {inv.tax_mode}")
    if inv.po_number:
        parts.append(f"PO ref {inv.po_number}")
    return StageResult(
        "Normalised " + ", ".join(parts),
        {
            "invoice_number": inv.invoice_number,
            "invoice_number_norm": inv.invoice_number_norm,
            "invoice_date_raw": inv.invoice_date_raw,
            "invoice_date": inv.invoice_date,
            "date_reading": inv.date_reading,
            "po_reference_raw": inv.po_reference_raw,
            "po_number": inv.po_number,
            "currency": inv.currency,
            "subtotal": inv.subtotal,
            "tax_amount": inv.tax_amount,
            "tax_rate": inv.tax_rate,
            "total": inv.total,
            "tax_mode": inv.tax_mode,
            "tax_note": inv.tax_note,
            "pretax_subtotal": inv.pretax_subtotal,
            "bank_last4": inv.bank_last4,
            "line_count": len(inv.lines),
        },
    )
