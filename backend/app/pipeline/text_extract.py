import re

import pdfplumber
import pymupdf

from ..llm.offline import TABLES_MARKER
from . import RunContext, StageResult

DIGITAL_MIN_CHARS_PER_PAGE = 80
RENDER_DPI = 200


def _meaningful_chars(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9]", text))


def run(ctx: RunContext) -> StageResult:
    page_texts: list[str] = []
    table_rows: list[str] = []
    with pdfplumber.open(ctx.stored_path) as pdf:
        for page in pdf.pages:
            page_texts.append(page.extract_text() or "")
            for table in page.extract_tables() or []:
                for row in table:
                    cells = [(c or "").replace("\n", " ").strip() for c in row]
                    if any(cells):
                        table_rows.append(" | ".join(cells))

    pages = max(1, len(page_texts))
    chars = sum(_meaningful_chars(t) for t in page_texts)
    ctx.doc_type = "digital" if chars / pages >= DIGITAL_MIN_CHARS_PER_PAGE else "scanned"
    ctx.text = "\n".join(page_texts)
    ctx.llm_text = ctx.text + (f"\n\n{TABLES_MARKER}\n" + "\n".join(table_rows) if table_rows else "")

    if ctx.doc_type == "scanned":
        with pymupdf.open(ctx.stored_path) as doc:
            ctx.images = [page.get_pixmap(dpi=RENDER_DPI).tobytes("png") for page in doc]
        summary = f"Scanned PDF (no text layer), {len(ctx.images)} page{'s' if len(ctx.images) != 1 else ''} rendered for vision"
    else:
        summary = f"Digital PDF, {pages} page{'s' if pages != 1 else ''}, {len(ctx.text):,} chars, {len(table_rows)} table rows"

    return StageResult(
        summary,
        {
            "doc_type": ctx.doc_type,
            "pages": pages,
            "text_chars": len(ctx.text),
            "meaningful_chars_per_page": round(chars / pages, 1),
            "table_rows": len(table_rows),
            "rendered_images": len(ctx.images),
            "text_preview": ctx.text[:600],
        },
    )
