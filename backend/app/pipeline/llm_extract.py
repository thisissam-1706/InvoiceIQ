import json
import re
from typing import Optional

from pydantic import ValidationError

from ..llm import LLMError
from ..llm.cache import ResponseCache, cache_key
from ..schemas import InvoiceExtraction
from . import RunContext, StageError, StageResult

EXTRACTION_PROMPT_VERSION = "v1"

EXTRACTION_PROMPT_V1 = """You are extracting data from a vendor invoice for an accounts-payable system.

Rules:
- Extract only what is printed on the invoice. Never invent or infer values. Use null when a value is absent or unreadable.
- po_reference: copy a purchase-order number ONLY if it is explicitly labelled as a PO / purchase order or is obviously formatted as one (e.g. "PO-2026-0101"). Any other order reference text goes into reference_notes.
- Amounts are plain numbers: no currency symbols, no thousands separators (4250.00, not "$4,250.00").
- tax_rate is a fraction (8% -> 0.08). tax_included_in_prices is true only if the invoice says prices/total include tax.
- bank_account_last4: only the last 4 digits of the remit-to bank account. bank_routing: routing/ABA/IFSC code as printed.
- remit_notes: any text about payment or bank details changing; otherwise null.
- For every field give a confidence between 0 and 1. Use 1.0 only when the value is clearly printed. Lower it for blurry, partial or ambiguous text.
- source_text is the short snippet (under 80 characters) of the invoice where you found the value, copied verbatim.
- line_items: one entry per billed line, in printed order.

Return a single JSON object with exactly this shape:
{
  "vendor_name": F, "vendor_tax_id": F, "vendor_address": F, "invoice_number": F, "invoice_date": F,
  "due_date": F, "po_reference": F, "reference_notes": F, "currency": F, "subtotal": F, "tax_amount": F,
  "tax_rate": F, "tax_included_in_prices": F, "total": F, "bank_account_last4": F, "bank_routing": F,
  "remit_notes": F,
  "line_items": [{"description": str, "sku": str|null, "quantity": number|null, "unit_price": number|null, "amount": number|null}]
}
where every F is {"value": <string|number|boolean|null>, "confidence": <0..1>, "source_text": <string|null>}.
Dates are copied as printed (do not reformat). Return JSON only."""

SCANNED_CONFIDENCE_CAP = 0.85
UNVERIFIED_SNIPPET_CONFIDENCE = 0.5


def _squash(s: str) -> str:
    return re.sub(r"[\s,$]", "", s).lower()


def _call_with_retry(ctx: RunContext, text: Optional[str], images: Optional[list[bytes]]) -> tuple[dict, int]:
    prompt = EXTRACTION_PROMPT_V1
    last_error = ""
    for attempt in (1, 2):
        try:
            raw = ctx.llm.extract(text, images, prompt, InvoiceExtraction, doc_name=ctx.file_name)
            InvoiceExtraction.model_validate(raw)
            return raw, attempt
        except (ValidationError, ValueError) as exc:
            last_error = str(exc)[:1500]
            prompt = (
                EXTRACTION_PROMPT_V1
                + "\n\nYour previous answer failed validation with this error:\n"
                + last_error
                + "\nReturn corrected JSON that matches the shape exactly."
            )
        except LLMError as exc:
            raise StageError(str(exc)) from exc
    raise StageError(f"Extraction could not produce valid structured data ({last_error.splitlines()[0] if last_error else 'unknown error'})")


def _adjust_confidence(ctx: RunContext, extraction: InvoiceExtraction) -> list[dict]:
    adjustments = []
    haystack = _squash(ctx.text) if ctx.doc_type == "digital" else ""
    for name in InvoiceExtraction.field_names():
        f = getattr(extraction, name)
        before = f.confidence
        if ctx.doc_type == "scanned":
            f.confidence = min(f.confidence, SCANNED_CONFIDENCE_CAP)
        elif f.value is not None and f.source_text:
            # Hallucination guard: the cited snippet (or at least the value) must exist in the text layer.
            found = _squash(f.source_text) in haystack or _squash(str(f.value)) in haystack
            if not found:
                f.confidence = min(f.confidence, UNVERIFIED_SNIPPET_CONFIDENCE)
        if f.confidence != before:
            adjustments.append({"field": name, "from": round(before, 2), "to": round(f.confidence, 2)})
    return adjustments


def run(ctx: RunContext) -> StageResult:
    client = ctx.llm
    scanned = ctx.doc_type == "scanned"
    text = None if scanned else ctx.llm_text
    images = ctx.images if scanned else None

    cache = ResponseCache()
    use_cache = ctx.config.llm.cache_enabled and client.provider != "offline"
    key = cache_key(ctx.sha256, client.provider, client.model, EXTRACTION_PROMPT_VERSION)
    raw = cache.get(key) if use_cache else None
    cached = raw is not None
    attempts = 0
    if raw is None:
        raw, attempts = _call_with_retry(ctx, text, images)
        if use_cache:
            cache.put(key, raw)

    extraction = InvoiceExtraction.model_validate(raw)
    adjustments = _adjust_confidence(ctx, extraction)
    ctx.extraction = extraction

    fields = InvoiceExtraction.field_names()
    present = [n for n in fields if getattr(extraction, n).value is not None]
    confidences = [getattr(extraction, n).confidence for n in present]
    avg = sum(confidences) / len(confidences) if confidences else 0.0
    ctx.extraction_meta = {
        "provider": client.provider,
        "model": client.model,
        "mode": "vision" if scanned else "text",
        "cached": cached,
        "attempts": attempts,
        "prompt_version": EXTRACTION_PROMPT_VERSION,
        "fields_found": len(present),
        "fields_total": len(fields),
        "line_items": len(extraction.line_items),
        "avg_confidence": round(avg, 3),
        "confidence_adjustments": adjustments,
        "confidence_cap": SCANNED_CONFIDENCE_CAP if scanned else None,
    }

    via = f"{client.provider}/{client.model}" + (" vision" if scanned else "")
    if scanned and client.provider == "offline" and present:
        via = "recorded vision extraction (offline mode)"
        ctx.extraction_meta["mode"] = "vision (recorded)"
    summary = (
        f"Extracted {len(present)} fields, {len(extraction.line_items)} line items, avg confidence {avg:.2f} via {via}"
        + (" (cached)" if cached else "")
    )
    if scanned and not present:
        summary = f"No fields could be read from the scanned pages via {via}"
    return StageResult(summary, {**ctx.extraction_meta, "extraction": json.loads(extraction.model_dump_json())})
