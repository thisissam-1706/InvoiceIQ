"""Regex/keyword extractor for digital invoices; lets the app run with no API key."""

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from ..settings import FIXTURES_DIR
from .base import LLMUnavailable

MONTHS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
DATE = (
    r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|\d{1,2}\.\d{1,2}\.\d{4}"
    rf"|{MONTHS}\s+\d{{1,2}},?\s+\d{{4}}|\d{{1,2}}\s+{MONTHS},?\s+\d{{4}})"
)
NUM_RE = re.compile(r"(?<![\w\-/.])\$?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?![\w\-/%])")
SKU_RE = re.compile(r"^[A-Z]{2,5}-[A-Z0-9]{2,8}(?:-[A-Z0-9]{1,8})?\b")

INVOICE_NO_RE = re.compile(
    r"(?i:invoice\s*(?:#|no\.?|number|num\.?)|inv\.?\s*(?:#|no\.?|number)|bill\s*(?:#|no\.?|number))"
    r"\s*[:#.]?\s*([A-Z][A-Z\-]{0,10}[\- ]?\d[\w\-/]*|\d[\w\-/]*)"
)
INVOICE_DATE_RE = re.compile(
    r"(?i:invoice\s*date|inv\.?\s*date|bill\s*date|date\s*of\s*issue|issue\s*date|issued(?:\s*on)?)\s*[:\-]?\s*" + DATE
)
ANY_DATE_RE = re.compile(r"(?i:\bdate)\s*[:\-]?\s*" + DATE)
DUE_DATE_RE = re.compile(r"(?i:due\s*date|payment\s*due|due\s*on|due\s*by)\s*[:\-]?\s*" + DATE)
PO_RE = re.compile(r"(?i)\bP\.?O\.?[\s\-#:/]*\d{4}[\s\-/]\d{3,4}\b")
TAX_ID_RE = re.compile(r"(?i:tax\s*id|ein|fein|tin|vat\s*(?:no\.?|id))\W{0,6}(\d{2}-\d{7})")
BARE_TAX_ID_RE = re.compile(r"\b\d{2}-\d{7}\b")
ACCOUNT_RE = re.compile(
    r"(?i:a(?:ccount|cct)\.?(?:\s*(?:no\.?|number|#|ending(?:\s+in)?))?)\s*[:\-]?\s*([\dXx*•\- ]*\d{4})\b"
)
ROUTING_RE = re.compile(r"(?i:routing(?:\s*(?:no\.?|number|#))?|aba(?:\s*#)?|rtn)\s*[:\-]?\s*(\d{9})\b")
REF_RE = re.compile(r"(?i)\b(?:your\s+ref|order\s+ref|reference|ref)\b\.?\s*[:\-]\s*(.+)")
REMIT_RE = re.compile(r"(?i)\b(new|updated|changed)\s+(bank|banking|remittance|account)")
TAX_INCLUDED_RE = re.compile(r"(?i)incl(?:\.|udes|uding|usive(?:\s+of)?)?\s+(?:\d+(?:\.\d+)?%\s+)?(?:sales\s+)?tax")
RATE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")

HEADER_WORDS = {"invoice", "tax invoice", "bill", "statement", "commercial invoice"}


def _field(value=None, confidence: float = 0.0, source: Optional[str] = None) -> dict:
    return {"value": value, "confidence": confidence if value is not None else 0.0, "source_text": source}


def _num(token: str) -> Decimal:
    return Decimal(token.replace(",", "").replace("$", ""))


def _last_amount(line: str) -> Optional[Decimal]:
    nums = NUM_RE.findall(line)
    return _num(nums[-1]) if nums else None


def parse_line_item(line: str) -> Optional[dict]:
    """A line item is any text row whose trailing three numbers satisfy qty x unit = amount."""
    matches = list(NUM_RE.finditer(line))
    if len(matches) < 3:
        return None
    qty, unit, amount = (_num(m.group(1)) for m in matches[-3:])
    if qty <= 0 or abs(qty * unit - amount) > Decimal("0.011"):
        return None
    desc = line[: matches[-3].start()].strip(" -|:$\t")
    desc = re.sub(r"^\d{1,2}[.)]?\s+", "", desc)
    sku = None
    m = SKU_RE.match(desc)
    if m:
        sku = m.group(0)
        desc = desc[m.end():].strip(" -|")
    if not re.search(r"[A-Za-z]{3}", desc):
        return None
    return {"description": desc, "sku": sku, "quantity": str(qty), "unit_price": str(unit), "amount": str(amount)}


def _vendor_name(lines: list[str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    for i, line in enumerate(lines[:8]):
        cleaned = re.sub(r"(?i)^(from|vendor|supplier)\s*:\s*", "", line)
        cleaned = re.sub(r"(?i)\b(tax\s+)?invoice\b.*$", "", cleaned).strip(" -|")
        if not cleaned or cleaned.lower() in HEADER_WORDS or not re.search(r"[A-Za-z]{3}", cleaned):
            continue
        if INVOICE_NO_RE.search(line) or re.search(r"\d{3,}", cleaned):
            continue
        address = None
        if i + 1 < len(lines) and re.search(r"\d", lines[i + 1]):
            address = re.sub(r"(?i)\s+(invoice|inv\.?|bill)\b.*$", "", lines[i + 1]).strip()
        return cleaned, line, address
    return None, None, None


TABLES_MARKER = "=== TABLES ==="


def extract_from_text(text: str) -> dict:
    # Table rows repeat the page text in pipe form; parsing both would double the line items.
    text = text.split(TABLES_MARKER)[0]
    lines =[re.sub(r"\s+", " ", l).strip() for l in text.splitlines()]
    lines = [l for l in lines if l]
    out: dict = {}

    name, name_src, address = _vendor_name(lines)
    out["vendor_name"] = _field(name, 0.85, name_src)
    out["vendor_address"] = _field(address, 0.6, address)

    def first(regex: re.Pattern, conf: float = 0.92, group: int = 1, skip_due: bool = False) -> dict:
        for line in lines:
            for m in regex.finditer(line):
                if skip_due and re.search(r"(?i)due\s*$", line[: m.start()]):
                    continue
                return _field(m.group(group).strip(), conf, line)
        return _field()

    out["invoice_number"] = first(INVOICE_NO_RE)
    inv_date = first(INVOICE_DATE_RE)
    out["invoice_date"] = inv_date if inv_date["value"] else first(ANY_DATE_RE, 0.8, skip_due=True)
    out["due_date"] = first(DUE_DATE_RE)
    tax_id = first(TAX_ID_RE)
    out["vendor_tax_id"] = tax_id if tax_id["value"] else first(BARE_TAX_ID_RE, 0.7, group=0)

    po = first(PO_RE, group=0)
    out["po_reference"] = po
    ref = first(REF_RE, 0.8)
    if ref["value"] and po["value"] and po["value"] in ref["value"]:
        ref = _field()
    out["reference_notes"] = ref

    if re.search(r"\bUSD\b|\$", text):
        out["currency"] = _field("USD", 0.9 if "USD" in text else 0.75, "USD" if "USD" in text else "$")
    elif re.search(r"\bEUR\b|€", text):
        out["currency"] = _field("EUR", 0.9, "EUR")
    else:
        out["currency"] = _field()

    subtotal = tax_amount = tax_rate = total = None
    sub_src = tax_src = rate_src = total_src = None
    for line in lines:
        low = line.lower()
        if parse_line_item(line):
            continue
        amount = _last_amount(line)
        rate = RATE_RE.search(line) if re.search(r"(?i)\b(tax|vat|gst)\b", line) else None
        if rate:
            tax_rate, rate_src = Decimal(rate.group(1)) / 100, line
        if amount is None:
            continue
        if re.search(r"sub[\s\-]?total", low):
            subtotal, sub_src = amount, line
        elif re.search(r"\b(tax|vat|gst)\b", low) and not re.search(r"\btotal\b", low):
            tax_amount, tax_src = amount, line
        elif re.search(r"\b(total|amount due|balance due|total due)\b", low):
            total, total_src = amount, line
    out["subtotal"] = _field(str(subtotal) if subtotal is not None else None, 0.9, sub_src)
    out["tax_amount"] = _field(str(tax_amount) if tax_amount is not None else None, 0.9, tax_src)
    out["tax_rate"] = _field(str(tax_rate) if tax_rate is not None else None, 0.85, rate_src)
    out["total"] = _field(str(total) if total is not None else None, 0.92, total_src)

    included = TAX_INCLUDED_RE.search(text)
    out["tax_included_in_prices"] = _field(True, 0.85, included.group(0)) if included else _field(False, 0.8, None)

    acct = first(ACCOUNT_RE, 0.9)
    if acct["value"]:
        digits = re.sub(r"\D", "", acct["value"])
        acct = _field(digits[-4:], 0.9, acct["source_text"]) if len(digits) >= 4 else _field()
    out["bank_account_last4"] = acct
    out["bank_routing"] = first(ROUTING_RE, 0.9)

    remit = next((l for l in lines if REMIT_RE.search(l)), None)
    out["remit_notes"] = _field(remit, 0.85, remit)

    out["line_items"] = [item for item in (parse_line_item(l) for l in lines) if item]
    return out


def empty_extraction(schema: type[BaseModel]) -> dict:
    return {name: _field() for name in schema.model_fields if name != "line_items"} | {"line_items": []}


class OfflineClient:
    provider = "offline"
    model = "heuristic-v1"

    def __init__(self, fixtures_dir: Path = FIXTURES_DIR):
        self.fixtures_dir = fixtures_dir

    def _fixture(self, doc_name: Optional[str]) -> Optional[dict]:
        if not doc_name:
            return None
        path = self.fixtures_dir / f"{Path(doc_name).stem}.json"
        return json.loads(path.read_text()) if path.exists() else None

    def extract(self, text, images, prompt, schema, doc_name=None) -> dict:
        if images and not (text and text.strip()):
            # No vision model offline: replay a recorded extraction for bundled scans, else nothing.
            return self._fixture(doc_name) or empty_extraction(schema)
        return extract_from_text(text or "")

    def generate_text(self, prompt: str) -> str:
        raise LLMUnavailable("Offline provider does not generate free text")
