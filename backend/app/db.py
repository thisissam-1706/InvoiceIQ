import csv
import json
from decimal import Decimal
from pathlib import Path

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, delete, select

from .models import (
    AuditEvent,
    GoodsReceipt,
    InvoiceFingerprint,
    POConsumption,
    POLine,
    PurchaseOrder,
    Run,
    RunStep,
    Vendor,
)
from .settings import REFERENCE_DIR, load_env

_engine = None


def configure(db_path: Path | str | None = None):
    """(Re)create the engine; tests point this at a temporary file."""
    global _engine
    path = Path(db_path) if db_path else load_env().db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    _engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

    @event.listens_for(_engine, "connect")
    def _pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        # WAL lets the API read while the worker thread writes.
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    return _engine


def get_engine():
    if _engine is None:
        configure()
    return _engine


def session() -> Session:
    return Session(get_engine(), expire_on_commit=False)


def init_db() -> None:
    SQLModel.metadata.create_all(get_engine())


def reset_runtime_data() -> None:
    with session() as s:
        for model in (AuditEvent, POConsumption, InvoiceFingerprint, RunStep, Run):
            s.exec(delete(model))
        s.commit()


def _read_csv(path: Path) -> list[dict]:
    with path.open(newline="") as fh:
        return [{k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()} for row in csv.DictReader(fh)]


def check_po_totals(pos: list[dict], lines: list[dict]) -> None:
    """Fail loudly if any PO's lines do not sum exactly to its header total."""
    problems = []
    for po in pos:
        line_sum = sum(
            (Decimal(l["quantity"]) * Decimal(l["unit_price"]) for l in lines if l["po_number"] == po["po_number"]),
            Decimal("0"),
        )
        if line_sum != Decimal(po["total_amount"]):
            problems.append(f"{po['po_number']}: lines sum to {line_sum}, header says {po['total_amount']}")
    if problems:
        raise ValueError("Purchase order totals do not reconcile:\n  " + "\n  ".join(problems))


def reseed_reference(reference_dir: Path = REFERENCE_DIR) -> dict[str, int]:
    vendors = _read_csv(reference_dir / "vendors.csv")
    pos = _read_csv(reference_dir / "purchase_orders.csv")
    lines = _read_csv(reference_dir / "po_lines.csv")
    receipts = _read_csv(reference_dir / "goods_receipts.csv")
    check_po_totals(pos, lines)

    init_db()
    with session() as s:
        for model in (GoodsReceipt, POLine, PurchaseOrder, Vendor):
            s.exec(delete(model))
        s.commit()
        for v in vendors:
            s.add(
                Vendor(
                    vendor_id=v["vendor_id"],
                    name=v["name"],
                    aliases_json=json.dumps([a for a in v["aliases"].split("|") if a]),
                    tax_id=v["tax_id"] or None,
                    bank_account_last4=v["bank_account_last4"] or None,
                    bank_routing=v["bank_ifsc_or_routing"] or None,
                    country=v["country"],
                    currency=v["currency"],
                    status=v["status"],
                    payment_terms_days=int(v["payment_terms_days"]),
                )
            )
        s.commit()
        for p in pos:
            s.add(PurchaseOrder(**p))
        s.commit()
        for l in lines:
            s.add(POLine(**{**l, "line_no": int(l["line_no"])}))
        for r in receipts:
            s.add(GoodsReceipt(**{**r, "line_no": int(r["line_no"])}))
        s.commit()
    return {"vendors": len(vendors), "purchase_orders": len(pos), "po_lines": len(lines), "goods_receipts": len(receipts)}


def reference_is_seeded() -> bool:
    with session() as s:
        return s.exec(select(Vendor)).first() is not None
