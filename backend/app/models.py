from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Vendor(SQLModel, table=True):
    vendor_id: str = Field(primary_key=True)
    name: str
    aliases_json: str = "[]"
    tax_id: Optional[str] = None
    bank_account_last4: Optional[str] = None
    bank_routing: Optional[str] = None
    country: str = "US"
    currency: str = "USD"
    status: str = "active"
    payment_terms_days: int = 30


class PurchaseOrder(SQLModel, table=True):
    po_number: str = Field(primary_key=True)
    vendor_id: str = Field(foreign_key="vendor.vendor_id", index=True)
    issue_date: str
    currency: str = "USD"
    total_amount: str
    status: str = "open"


class POLine(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    po_number: str = Field(foreign_key="purchaseorder.po_number", index=True)
    line_no: int
    sku: Optional[str] = None
    description: str
    quantity: str
    unit_price: str
    uom: str = "ea"


class GoodsReceipt(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    po_number: str = Field(index=True)
    line_no: int
    received_qty: str
    received_date: str


class Run(SQLModel, table=True):
    id: str = Field(primary_key=True)
    created_at: str = Field(default_factory=utcnow_iso, index=True)
    finished_at: Optional[str] = None
    source: str = "upload"
    file_name: str
    file_sha256: Optional[str] = Field(default=None, index=True)
    file_path: str
    status: str = "queued"
    current_stage: Optional[str] = None
    decision: Optional[str] = None
    original_decision: Optional[str] = None
    decision_overridden: bool = False
    vendor_id: Optional[str] = None
    vendor_name: Optional[str] = None
    po_number: Optional[str] = Field(default=None, index=True)
    invoice_number: Optional[str] = None
    invoice_total: Optional[str] = None
    currency: Optional[str] = None
    doc_type: Optional[str] = None
    extraction_json: Optional[str] = None
    validation_json: Optional[str] = None
    matching_json: Optional[str] = None
    rules_json: Optional[str] = None
    explanation_text: Optional[str] = None
    suggested_action: Optional[str] = None
    error_message: Optional[str] = None
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    provider_note: Optional[str] = None
    duration_ms: Optional[int] = None
    rerun_of: Optional[str] = None
    superseded_by: Optional[str] = None


class RunStep(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(foreign_key="run.id", index=True)
    stage: str
    status: str = "started"
    started_at: str = Field(default_factory=utcnow_iso)
    finished_at: Optional[str] = None
    duration_ms: Optional[int] = None
    summary: Optional[str] = None
    detail_json: Optional[str] = None


class InvoiceFingerprint(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(foreign_key="run.id", index=True)
    vendor_id: Optional[str] = Field(default=None, index=True)
    invoice_number_norm: Optional[str] = None
    invoice_date: Optional[str] = None
    total_amount: Optional[str] = None
    exact_hash: str
    created_at: str = Field(default_factory=utcnow_iso)


class POConsumption(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    po_number: str = Field(index=True)
    run_id: str = Field(index=True)
    amount: str
    created_at: str = Field(default_factory=utcnow_iso)
    reason: str = "auto_approve"


class AuditEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(index=True)
    at: str = Field(default_factory=utcnow_iso)
    actor: str = "system"
    action: str
    note: Optional[str] = None
