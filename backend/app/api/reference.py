import json
from decimal import Decimal

from fastapi import APIRouter
from sqlmodel import select

from .. import db
from ..models import GoodsReceipt, POConsumption, POLine, PurchaseOrder, Run, Vendor
from ..pipeline import q2

router = APIRouter(prefix="/api/reference", tags=["reference"])


def vendor_out(v: Vendor) -> dict:
    return {
        "vendor_id": v.vendor_id,
        "name": v.name,
        "aliases": json.loads(v.aliases_json or "[]"),
        "tax_id": v.tax_id,
        "bank_account_last4": v.bank_account_last4,
        "bank_routing": v.bank_routing,
        "country": v.country,
        "currency": v.currency,
        "status": v.status,
        "payment_terms_days": v.payment_terms_days,
    }


@router.get("/vendors")
def list_vendors() -> list[dict]:
    with db.session() as s:
        return [vendor_out(v) for v in s.exec(select(Vendor).order_by(Vendor.vendor_id)).all()]


def po_consumed(s, po_number: str) -> Decimal:
    rows = s.exec(select(POConsumption).where(POConsumption.po_number == po_number)).all()
    return sum((Decimal(r.amount) for r in rows), Decimal("0"))


@router.get("/pos")
def list_pos() -> list[dict]:
    with db.session() as s:
        vendors = {v.vendor_id: v for v in s.exec(select(Vendor)).all()}
        out = []
        for po in s.exec(select(PurchaseOrder).order_by(PurchaseOrder.po_number)).all():
            lines = s.exec(select(POLine).where(POLine.po_number == po.po_number).order_by(POLine.line_no)).all()
            receipts = {
                r.line_no: r.received_qty
                for r in s.exec(select(GoodsReceipt).where(GoodsReceipt.po_number == po.po_number)).all()
            }
            consumption = s.exec(select(POConsumption).where(POConsumption.po_number == po.po_number)).all()
            consumed_by = {c.run_id: c for c in consumption}
            consumed = sum((Decimal(c.amount) for c in consumption), Decimal("0"))
            total = Decimal(po.total_amount)
            runs = s.exec(select(Run).where(Run.po_number == po.po_number).order_by(Run.created_at)).all()
            vendor = vendors.get(po.vendor_id)
            out.append(
                {
                    "po_number": po.po_number,
                    "vendor_id": po.vendor_id,
                    "vendor_name": vendor.name if vendor else None,
                    "issue_date": po.issue_date,
                    "currency": po.currency,
                    "status": po.status,
                    "total_amount": str(q2(total)),
                    "consumed": str(q2(consumed)),
                    "remaining": str(q2(total - consumed)),
                    "lines": [
                        {
                            "line_no": l.line_no,
                            "sku": l.sku,
                            "description": l.description,
                            "quantity": l.quantity,
                            "unit_price": l.unit_price,
                            "uom": l.uom,
                            "line_total": str(q2(Decimal(l.quantity) * Decimal(l.unit_price))),
                            "received_qty": receipts.get(l.line_no),
                        }
                        for l in lines
                    ],
                    "runs": [
                        {
                            "run_id": r.id,
                            "file_name": r.file_name,
                            "invoice_number": r.invoice_number,
                            "invoice_total": r.invoice_total,
                            "decision": r.decision,
                            "decision_overridden": r.decision_overridden,
                            "status": r.status,
                            "consumed_amount": consumed_by[r.id].amount if r.id in consumed_by else None,
                        }
                        for r in runs
                    ],
                }
            )
        return out
