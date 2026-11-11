import os

os.environ["LLM_PROVIDER"] = "offline"

from datetime import date  # noqa: E402
from decimal import Decimal  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Optional  # noqa: E402

import pytest  # noqa: E402

from backend.app import db  # noqa: E402
from backend.app.llm import OfflineClient  # noqa: E402
from backend.app.models import InvoiceFingerprint, Run  # noqa: E402
from backend.app.pipeline import InvoiceLine, NormalisedInvoice, RunContext  # noqa: E402
from backend.app.schemas import InvoiceExtraction  # noqa: E402
from backend.app.settings import AppConfig  # noqa: E402


@pytest.fixture
def fresh_db(tmp_path):
    db.configure(tmp_path / "test.db")
    db.init_db()
    db.reseed_reference()
    yield
    db.configure(tmp_path / "unused.db")


@pytest.fixture
def config() -> AppConfig:
    cfg = AppConfig()
    cfg.demo.stage_delay_ms = 0
    return cfg


def line(desc: str, qty, unit, sku: Optional[str] = None, amount=None) -> InvoiceLine:
    q, u = Decimal(str(qty)), Decimal(str(unit))
    a = Decimal(str(amount)) if amount is not None else (q * u).quantize(Decimal("0.01"))
    return InvoiceLine(description=desc, sku=sku, quantity=q, unit_price=u, amount=a, unit_price_pretax=u)


def make_ctx(config: AppConfig, run_id: str = "test-run", extraction: Optional[dict] = None, **invoice) -> RunContext:
    inv = NormalisedInvoice(**invoice)
    if inv.pretax_subtotal is None:
        inv.pretax_subtotal = inv.subtotal if inv.subtotal is not None else inv.line_sum
    ctx = RunContext(
        run_id=run_id,
        file_path=Path("/dev/null"),
        file_name="test.pdf",
        source="batch",
        config=config,
        llm=OfflineClient(),
        sha256=f"sha-{run_id}",
        doc_type="digital",
    )
    ctx.invoice = inv
    ctx.extraction = InvoiceExtraction.model_validate(extraction or {})
    return ctx


def codes(ctx: RunContext) -> set[str]:
    return {c.code for c in ctx.findings}


def add_prior_run(
    run_id: str,
    decision: str,
    vendor_id: str,
    number_norm: Optional[str],
    total: str,
    invoice_date: date,
    sha: Optional[str] = None,
    rules_json: Optional[str] = None,
) -> None:
    with db.session() as s:
        s.add(
            Run(
                id=run_id,
                file_name=f"{run_id}.pdf",
                file_path="/dev/null",
                status="completed",
                decision=decision,
                invoice_number=number_norm,
                vendor_id=vendor_id,
                file_sha256=sha or f"sha-{run_id}",
                rules_json=rules_json,
            )
        )
        s.commit()
        s.add(
            InvoiceFingerprint(
                run_id=run_id,
                vendor_id=vendor_id,
                invoice_number_norm=number_norm,
                invoice_date=invoice_date.isoformat(),
                total_amount=total,
                exact_hash=sha or f"sha-{run_id}",
            )
        )
        s.commit()
