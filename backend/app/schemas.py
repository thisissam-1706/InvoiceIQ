import re
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

_NUMBER_JUNK = re.compile(r"[,$€£₹\s]|USD|EUR|GBP|INR", re.IGNORECASE)


def _clean_decimal(v: Any) -> Any:
    if isinstance(v, str):
        cleaned = _NUMBER_JUNK.sub("", v).rstrip("%")
        if cleaned in ("", "-", "null", "None", "N/A"):
            return None
        if cleaned.startswith("(") and cleaned.endswith(")"):
            cleaned = "-" + cleaned[1:-1]
        try:
            return Decimal(cleaned)
        except InvalidOperation:
            return v
    if isinstance(v, float):
        return Decimal(str(v))
    return v


def _clean_confidence(v: Any) -> Any:
    if isinstance(v, (int, float)) and 1 < v <= 100:
        return v / 100
    return 0.0 if v is None else v


class _FieldBase(BaseModel):
    confidence: float = Field(0.0, ge=0, le=1)
    source_text: Optional[str] = None

    _conf = field_validator("confidence", mode="before")(_clean_confidence)


class StrField(_FieldBase):
    value: Optional[str] = None

    @field_validator("value", mode="before")
    @classmethod
    def _blank_is_none(cls, v: Any) -> Any:
        if v is None:
            return None
        v = str(v).strip()
        return v or None


class DecimalField(_FieldBase):
    value: Optional[Decimal] = None

    _clean = field_validator("value", mode="before")(_clean_decimal)


class BoolField(_FieldBase):
    value: Optional[bool] = None


class ExtractedLine(BaseModel):
    description: str = ""
    sku: Optional[str] = None
    quantity: Optional[Decimal] = None
    unit_price: Optional[Decimal] = None
    amount: Optional[Decimal] = None

    _clean = field_validator("quantity", "unit_price", "amount", mode="before")(_clean_decimal)

    @field_validator("description", mode="before")
    @classmethod
    def _desc(cls, v: Any) -> str:
        return "" if v is None else str(v).strip()


class InvoiceExtraction(BaseModel):
    vendor_name: StrField = Field(default_factory=StrField)
    vendor_tax_id: StrField = Field(default_factory=StrField)
    vendor_address: StrField = Field(default_factory=StrField)
    invoice_number: StrField = Field(default_factory=StrField)
    invoice_date: StrField = Field(default_factory=StrField)
    due_date: StrField = Field(default_factory=StrField)
    po_reference: StrField = Field(default_factory=StrField)
    reference_notes: StrField = Field(default_factory=StrField)
    currency: StrField = Field(default_factory=StrField)
    subtotal: DecimalField = Field(default_factory=DecimalField)
    tax_amount: DecimalField = Field(default_factory=DecimalField)
    tax_rate: DecimalField = Field(default_factory=DecimalField)
    tax_included_in_prices: BoolField = Field(default_factory=BoolField)
    total: DecimalField = Field(default_factory=DecimalField)
    bank_account_last4: StrField = Field(default_factory=StrField)
    bank_routing: StrField = Field(default_factory=StrField)
    remit_notes: StrField = Field(default_factory=StrField)
    line_items: list[ExtractedLine] = Field(default_factory=list)

    @classmethod
    def field_names(cls) -> list[str]:
        return [n for n in cls.model_fields if n != "line_items"]


# --- API ---------------------------------------------------------------

Decision = Literal["APPROVE", "HOLD", "REJECT"]


class OverrideRequest(BaseModel):
    decision: Literal["APPROVE", "REJECT"]
    note: str = Field(min_length=1, max_length=2000)

    @field_validator("note")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("A note is required for an override")
        return v.strip()


class ResetRequest(BaseModel):
    confirm: bool = False


class RunCreated(BaseModel):
    run_id: str
    file_name: str


class RunSummary(BaseModel):
    id: str
    created_at: str
    finished_at: Optional[str]
    source: str
    file_name: str
    status: str
    current_stage: Optional[str]
    decision: Optional[str]
    original_decision: Optional[str]
    decision_overridden: bool
    vendor_id: Optional[str]
    vendor_name: Optional[str]
    po_number: Optional[str]
    invoice_number: Optional[str]
    invoice_total: Optional[str]
    currency: Optional[str]
    doc_type: Optional[str]
    duration_ms: Optional[int]
    error_message: Optional[str]
    rerun_of: Optional[str]
    superseded_by: Optional[str]


class RunList(BaseModel):
    items: list[RunSummary]
    total: int


class StepOut(BaseModel):
    stage: str
    status: str
    started_at: str
    finished_at: Optional[str]
    duration_ms: Optional[int]
    summary: Optional[str]
    detail: dict[str, Any]


class AuditOut(BaseModel):
    at: str
    actor: str
    action: str
    note: Optional[str]


class RunDetail(BaseModel):
    run: RunSummary
    steps: list[StepOut]
    extraction: Optional[dict[str, Any]]
    validation: Optional[dict[str, Any]]
    matching: Optional[dict[str, Any]]
    rules: Optional[dict[str, Any]]
    checks: list[dict[str, Any]]
    explanation: Optional[str]
    actions: Optional[dict[str, Any]]
    audit: list[AuditOut]
    llm_provider: Optional[str]
    llm_model: Optional[str]
    provider_note: Optional[str]
