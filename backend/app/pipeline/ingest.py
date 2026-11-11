import hashlib

import pymupdf
from sqlmodel import select

from .. import db
from ..models import Run
from ..settings import UPLOADS_DIR
from . import RunContext, StageError, StageResult


def run(ctx: RunContext) -> StageResult:
    if not ctx.file_path.exists():
        raise StageError(f"File not found: {ctx.file_name}")
    data = ctx.file_path.read_bytes()
    ctx.file_size = len(data)
    ctx.sha256 = hashlib.sha256(data).hexdigest()

    if b"%PDF-" not in data[:1024]:
        raise StageError(f"'{ctx.file_name}' is not a PDF. Only PDF invoices can be processed.")
    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            if doc.needs_pass:
                raise StageError("The PDF is password-protected and cannot be read.")
            ctx.page_count = doc.page_count
    except StageError:
        raise
    except Exception as exc:
        raise StageError(f"The PDF could not be opened ({exc}). It may be corrupted.") from exc
    if ctx.page_count == 0:
        raise StageError("The PDF has no pages.")

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    stored = UPLOADS_DIR / f"{ctx.sha256}.pdf"
    if not stored.exists():
        stored.write_bytes(data)
    ctx.stored_path = stored

    with db.session() as s:
        prior = s.exec(
            select(Run)
            .where(Run.file_sha256 == ctx.sha256, Run.id != ctx.run_id, Run.decision.is_not(None))
            .order_by(Run.created_at)
        ).first()
    ctx.prior_same_file_run_id = prior.id if prior else None

    kb = ctx.file_size / 1024
    summary = f"PDF received: {ctx.page_count} page{'s' if ctx.page_count != 1 else ''}, {kb:,.1f} KB, sha256 {ctx.sha256[:12]}…"
    if prior:
        summary += " (identical file seen before)"
    return StageResult(
        summary,
        {
            "file_name": ctx.file_name,
            "pages": ctx.page_count,
            "size_bytes": ctx.file_size,
            "sha256": ctx.sha256,
            "source": ctx.source,
            "identical_file_run": ctx.prior_same_file_run_id,
        },
    )
