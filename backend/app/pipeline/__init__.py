import dataclasses
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

from ..settings import AppConfig

STAGES = [
    "ingest",
    "text_extract",
    "llm_extract",
    "normalise",
    "validate",
    "vendor_match",
    "po_match",
    "duplicates",
    "rules",
    "decision",
    "explain",
]

SEVERITY_RANK = {"pass": 0, "info": 1, "warning": 2, "review": 3, "block": 4}

CENT = Decimal("0.01")

CODE_LABELS = {
    "MISSING_INVOICE_NUMBER": "missing invoice number",
    "MISSING_INVOICE_DATE": "missing invoice date",
    "MISSING_VENDOR_NAME": "missing vendor name",
    "MISSING_TOTAL": "missing total",
    "ARITHMETIC_MISMATCH": "the invoice does not add up",
    "LOW_EXTRACTION_CONFIDENCE": "low-confidence fields",
    "FUTURE_DATED": "future-dated invoice",
    "STALE_INVOICE": "old invoice",
    "VENDOR_NOT_FOUND": "vendor not in master",
    "VENDOR_FUZZY_MATCH": "vendor name only loosely matches",
    "VENDOR_INACTIVE": "inactive vendor",
    "BANK_DETAILS_MISMATCH": "bank details differ from master",
    "TAX_ID_MISMATCH": "tax ID mismatch",
    "CURRENCY_ASSUMED": "currency assumed",
    "PO_NOT_FOUND": "PO not found",
    "PO_VENDOR_MISMATCH": "PO belongs to another vendor",
    "PO_CLOSED": "PO closed",
    "PO_INFERRED": "PO inferred, not quoted",
    "PO_MISSING": "no PO",
    "QTY_EXCEEDS_PO": "quantity above the PO",
    "QTY_EXCEEDS_RECEIVED": "quantity above goods received",
    "UNMATCHED_LINE": "lines not on the PO",
    "PO_BUDGET_EXCEEDED": "PO budget exceeded",
    "PO_PARTIAL_CONSUMPTION": "PO partially consumed",
    "DUPLICATE_INVOICE": "duplicate invoice",
    "POSSIBLE_DUPLICATE": "possible duplicate",
    "RESUBMISSION": "resubmission of a rejected invoice",
    "PRICE_VARIANCE_WITHIN_TOL": "price difference within tolerance",
    "PRICE_VARIANCE_EXCEEDS_TOL": "price above tolerance",
    "TOTAL_VARIANCE_EXCEEDS_TOL": "total outside tolerance",
    "AMOUNT_ABOVE_AUTO_LIMIT": "above auto-approval limit",
    "LLM_FALLBACK_OFFLINE": "read by the offline extractor (AI unavailable)",
}


# Display-only names for the UI and CODES.md. CODE_LABELS above is spliced into sentences by
# explain.py and must stay as lowercase fragments; use DISPLAY_LABELS for anything shown as a label.
DISPLAY_LABELS: dict[str, dict[str, str]] = {
    "LLM_FALLBACK_OFFLINE": {"title": "Read by offline extractor", "description": "The AI model was overloaded, so a basic text extractor read this invoice. It is always held for a person to check against the PDF."},
    "MISSING_INVOICE_NUMBER": {"title": "Invoice number not found", "description": "No invoice number could be read from the document."},
    "INVOICE_NUMBER_PRESENT": {"title": "Invoice number found", "description": "An invoice number was read from the document."},
    "MISSING_INVOICE_DATE": {"title": "Invoice date not found", "description": "No readable invoice date was found on the document."},
    "INVOICE_DATE_PRESENT": {"title": "Invoice date found", "description": "An invoice date was read from the document."},
    "MISSING_VENDOR_NAME": {"title": "Vendor name not found", "description": "No vendor name could be read from the document."},
    "VENDOR_NAME_PRESENT": {"title": "Vendor name found", "description": "A vendor name was read from the document."},
    "MISSING_TOTAL": {"title": "Invoice total not found", "description": "No invoice total could be read from the document."},
    "TOTAL_PRESENT": {"title": "Invoice total found", "description": "An invoice total was read from the document."},
    "ARITHMETIC_MISMATCH": {"title": "Invoice amounts don't add up", "description": "The line amounts, subtotal, tax and total on the invoice do not agree with each other."},
    "ARITHMETIC_OK": {"title": "Invoice amounts add up", "description": "Line amounts, subtotal, tax and total are consistent with each other."},
    "LOW_EXTRACTION_CONFIDENCE": {"title": "Some fields were hard to read", "description": "One or more key fields were read with low confidence and should be checked against the PDF."},
    "EXTRACTION_CONFIDENCE_OK": {"title": "All fields read clearly", "description": "All key fields were read with enough confidence."},
    "FUTURE_DATED": {"title": "Invoice dated in the future", "description": "The invoice date is later than today."},
    "STALE_INVOICE": {"title": "Invoice is unusually old", "description": "The invoice date is older than the accepted window."},
    "INVOICE_DATE_PLAUSIBLE": {"title": "Invoice date looks reasonable", "description": "The invoice date is within the accepted window."},
    "VENDOR_NOT_FOUND": {"title": "Vendor not in vendor list", "description": "The vendor on the invoice does not match any vendor in the vendor master."},
    "VENDOR_MATCHED": {"title": "Vendor recognised", "description": "The vendor on the invoice was matched to a vendor in the vendor master."},
    "VENDOR_FUZZY_MATCH": {"title": "Vendor name only loosely matches", "description": "The vendor name is similar to, but not the same as, a vendor in the vendor master."},
    "VENDOR_INACTIVE": {"title": "Vendor is inactive", "description": "The vendor is marked inactive in the vendor master, so invoices from them are not paid."},
    "VENDOR_ACTIVE": {"title": "Vendor is active", "description": "The matched vendor is active in the vendor master."},
    "BANK_DETAILS_MISMATCH": {"title": "Bank details differ from records", "description": "The bank details printed on the invoice differ from those on file for this vendor, a common fraud pattern."},
    "BANK_DETAILS_MATCH": {"title": "Bank details match records", "description": "The bank details on the invoice match those on file for this vendor."},
    "BANK_DETAILS_ABSENT": {"title": "No bank details on invoice", "description": "The invoice shows no bank details, so payment goes to the account on file."},
    "TAX_ID_MISMATCH": {"title": "Tax ID differs from records", "description": "The tax ID on the invoice does not match the one on file for this vendor."},
    "TAX_ID_MATCH": {"title": "Tax ID matches records", "description": "The tax ID on the invoice matches the one on file for this vendor."},
    "CURRENCY_ASSUMED": {"title": "Currency assumed", "description": "The invoice shows no currency, so the vendor's usual currency was assumed."},
    "PO_NOT_FOUND": {"title": "Purchase order not found", "description": "The invoice quotes a purchase order number that does not exist."},
    "PO_VENDOR_MISMATCH": {"title": "PO belongs to another vendor", "description": "The purchase order quoted on the invoice was issued to a different vendor."},
    "PO_FOUND": {"title": "Purchase order found", "description": "The purchase order quoted on the invoice exists and belongs to this vendor."},
    "PO_CLOSED": {"title": "Purchase order is closed", "description": "The purchase order is closed or cancelled, so no more invoices can be paid against it."},
    "PO_INFERRED": {"title": "Purchase order guessed, not quoted", "description": "The invoice has no PO number, so the system picked the most likely open PO. A person should confirm it."},
    "PO_MISSING": {"title": "No purchase order", "description": "The invoice has no PO number and no open PO could be matched with confidence."},
    "QTY_EXCEEDS_PO": {"title": "Quantity above purchase order", "description": "The invoice bills more units than were ordered on the purchase order."},
    "QTY_EXCEEDS_RECEIVED": {"title": "Quantity above goods received", "description": "The invoice bills more units than the warehouse has received."},
    "QTY_WITHIN_PO_AND_RECEIPTS": {"title": "Quantities within PO and receipts", "description": "Billed quantities do not exceed what was ordered or received."},
    "UNMATCHED_LINE": {"title": "Lines not on the purchase order", "description": "One or more invoice lines do not correspond to any line on the purchase order."},
    "ALL_LINES_MATCHED": {"title": "All lines matched to PO", "description": "Every invoice line matches a line on the purchase order."},
    "PO_BUDGET_EXCEEDED": {"title": "Purchase order budget exceeded", "description": "This invoice would take the purchase order over its remaining budget."},
    "PO_PARTIAL_CONSUMPTION": {"title": "Purchase order partly used", "description": "This invoice uses up part of the purchase order budget; some remains."},
    "PO_BUDGET_OK": {"title": "Within purchase order budget", "description": "The invoice fits within the remaining budget of the purchase order."},
    "DUPLICATE_INVOICE": {"title": "Duplicate invoice", "description": "This invoice, or one with the same vendor and number, has already been processed."},
    "POSSIBLE_DUPLICATE": {"title": "Possible duplicate invoice", "description": "This invoice looks very similar to an earlier one from the same vendor."},
    "RESUBMISSION": {"title": "Resubmitted after rejection", "description": "This invoice was rejected earlier for another reason and has been submitted again."},
    "NO_DUPLICATE": {"title": "No duplicate found", "description": "No earlier invoice matches this one."},
    "PRICE_VARIANCE_WITHIN_TOL": {"title": "Price differs, within tolerance", "description": "A unit price differs from the purchase order but is within the allowed tolerance."},
    "PRICE_VARIANCE_EXCEEDS_TOL": {"title": "Price above allowed tolerance", "description": "A unit price differs from the purchase order by more than the allowed tolerance."},
    "PRICES_MATCH_PO": {"title": "Prices match purchase order", "description": "All unit prices match the purchase order exactly."},
    "TOTAL_VARIANCE_EXCEEDS_TOL": {"title": "Total outside allowed tolerance", "description": "The invoice total differs from the expected total by more than the allowed amount."},
    "TOTAL_WITHIN_TOL": {"title": "Total within allowed tolerance", "description": "The invoice total is close enough to the expected total."},
    "AMOUNT_ABOVE_AUTO_LIMIT": {"title": "Above auto-approval limit", "description": "The amount is above the limit for automatic approval and needs manual sign-off."},
    "WITHIN_AUTO_LIMIT": {"title": "Within auto-approval limit", "description": "The amount is within the limit for automatic approval."},
}



def humanise_code(code: str) -> str:
    """Fallback display name for a code with no DISPLAY_LABELS entry: 'SOME_CODE' -> 'Some code'."""
    text = code.replace("_", " ").strip().lower()
    return text[:1].upper() + text[1:]


def code_title(code: str) -> str:
    entry = DISPLAY_LABELS.get(code)
    return entry["title"] if entry else humanise_code(code)


def code_info(code: str) -> dict[str, str]:
    """{'title', 'description'} for any code, with a humanised fallback."""
    entry = DISPLAY_LABELS.get(code)
    return dict(entry) if entry else {"title": humanise_code(code), "description": ""}


class StageError(Exception):
    """A stage failed for a reason worth showing the user verbatim."""


def to_decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).replace(",", "").replace("$", "").strip())
    except InvalidOperation:
        return None


def q2(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def money_eq(a: Decimal, b: Decimal, tol: Decimal = CENT) -> bool:
    return abs(q2(a) - q2(b)) <= tol


def fmt_money(value: Optional[Decimal], currency: Optional[str] = "USD") -> str:
    if value is None:
        return "n/a"
    symbol = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹"}.get((currency or "USD").upper())
    sign = "-" if value < 0 else ""
    amount = f"{abs(q2(value)):,.2f}"
    return f"{sign}{symbol}{amount}" if symbol else f"{sign}{amount} {currency}"


def fmt_pct(value: Decimal) -> str:
    pct = (value * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{'+' if pct > 0 else ''}{pct}%"


def pct_text(fraction: Decimal) -> str:
    """0.02 -> '2%', 0.025 -> '2.5%'."""
    return f"{(Decimal(fraction) * 100).normalize():f}%"


def sentence(text: str) -> str:
    text = text.strip()
    while text.endswith(".."):
        text = text[:-1]
    return text if text.endswith((".", "!", "?")) else text + "."


def jsonable(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, BaseModel):
        return jsonable(obj.model_dump())
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [jsonable(v) for v in obj]
    return obj


@dataclass
class Check:
    code: str
    severity: str
    message: str
    stage: str = ""
    field: Optional[str] = None
    critical: bool = False
    data: dict = dataclasses.field(default_factory=dict)

    @property
    def is_finding(self) -> bool:
        return self.severity != "pass"


@dataclass
class StageResult:
    summary: str
    detail: dict = field(default_factory=dict)


@dataclass
class InvoiceLine:
    description: str
    sku: Optional[str]
    quantity: Optional[Decimal]
    unit_price: Optional[Decimal]
    amount: Optional[Decimal]
    unit_price_pretax: Optional[Decimal] = None


@dataclass
class NormalisedInvoice:
    vendor_name: Optional[str] = None
    vendor_tax_id: Optional[str] = None
    vendor_address: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_number_norm: Optional[str] = None
    invoice_date: Optional[date] = None
    invoice_date_raw: Optional[str] = None
    date_reading: Optional[str] = None
    date_ambiguous: bool = False
    due_date: Optional[date] = None
    due_date_raw: Optional[str] = None
    po_reference_raw: Optional[str] = None
    po_number: Optional[str] = None
    reference_notes: Optional[str] = None
    currency: Optional[str] = None
    currency_assumed: bool = False
    subtotal: Optional[Decimal] = None
    tax_amount: Optional[Decimal] = None
    tax_rate: Optional[Decimal] = None
    total: Optional[Decimal] = None
    tax_mode: str = "separate"
    tax_note: str = ""
    pretax_subtotal: Optional[Decimal] = None
    tax_effective: Decimal = Decimal("0")
    lines: list[InvoiceLine] = field(default_factory=list)
    bank_last4: Optional[str] = None
    bank_routing: Optional[str] = None
    remit_notes: Optional[str] = None

    @property
    def line_sum(self) -> Optional[Decimal]:
        amounts = [l.amount for l in self.lines if l.amount is not None]
        return sum(amounts, Decimal("0")) if amounts else None


@dataclass
class RunContext:
    run_id: str
    file_path: Path
    file_name: str
    source: str
    config: AppConfig
    llm: Any = None
    current_stage: str = ""
    sha256: Optional[str] = None
    file_size: int = 0
    page_count: int = 0
    stored_path: Optional[Path] = None
    prior_same_file_run_id: Optional[str] = None
    doc_type: Optional[str] = None
    text: str = ""
    llm_text: str = ""
    images: list[bytes] = field(default_factory=list)
    extraction: Any = None
    extraction_meta: dict = field(default_factory=dict)
    invoice: Optional[NormalisedInvoice] = None
    checks: list[Check] = field(default_factory=list)
    vendor: Optional[dict] = None
    vendor_match: dict = field(default_factory=dict)
    po: Optional[dict] = None
    po_match: dict = field(default_factory=dict)
    line_matches: list[dict] = field(default_factory=list)
    budget: dict = field(default_factory=dict)
    duplicate: dict = field(default_factory=dict)
    decision: Optional[str] = None
    actions: dict = field(default_factory=dict)
    payment_due_date: Optional[date] = None
    explanation: Optional[str] = None

    def add(self, code: str, severity: str, message: str, **kw) -> Check:
        check = Check(code=code, severity=severity, message=message, stage=self.current_stage, **kw)
        self.checks.append(check)
        return check

    def passed(self, code: str, message: str, **kw) -> Check:
        return self.add(code, "pass", message, **kw)

    @property
    def findings(self) -> list[Check]:
        return [c for c in self.checks if c.is_finding]

    def stage_checks(self, stage: str) -> list[Check]:
        return [c for c in self.checks if c.stage == stage]

    @property
    def currency(self) -> str:
        if self.invoice and self.invoice.currency:
            return self.invoice.currency
        if self.vendor:
            return self.vendor.get("currency") or "USD"
        return "USD"

    def money(self, value: Optional[Decimal]) -> str:
        return fmt_money(value, self.currency)
