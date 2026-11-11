import hashlib
import json
import logging
from typing import Optional

from ..llm import LLMError
from ..llm.cache import ResponseCache, cache_key
from . import CODE_LABELS, RunContext, StageResult, jsonable

log = logging.getLogger(__name__)

EXPLAIN_PROMPT_VERSION = "explain-v1"

EXPLAIN_PROMPT = """Write a short explanation (3 to 5 sentences) of an invoice decision for a non-technical accounts-payable manager.
Rules: use only the facts in the JSON below; mention every reason with severity "review" or "block"; do not speculate or add advice
beyond the suggested action; use plain English (no codes, no jargon such as "fuzzy" or "SKU"); include the specific numbers
(amounts, PO numbers, percentages). Start with the decision. Return plain text only, no bullet points or headings.

FACTS:
"""


def generate_text(ctx: RunContext, prompt: str) -> Optional[str]:
    """LLM free text with caching; None when the provider can't or fails, so callers fall back to templates."""
    client = ctx.llm
    if client is None or client.provider == "offline":
        return None
    cache = ResponseCache()
    key = cache_key(hashlib.sha256(prompt.encode()).hexdigest(), client.provider, client.model, EXPLAIN_PROMPT_VERSION)
    if ctx.config.llm.cache_enabled:
        hit = cache.get(key)
        if hit and hit.get("text"):
            return hit["text"]
    try:
        text = client.generate_text(prompt).strip()
    except LLMError as exc:
        log.warning("LLM text generation failed, using template: %s", exc)
        return None
    if not text:
        return None
    if ctx.config.llm.cache_enabled:
        cache.put(key, {"text": text})
    return text


def _facts(ctx: RunContext) -> dict:
    inv = ctx.invoice
    return jsonable(
        {
            "decision": ctx.decision,
            "vendor": ctx.vendor["name"] if ctx.vendor else inv.vendor_name,
            "vendor_in_master": bool(ctx.vendor),
            "invoice_number": inv.invoice_number,
            "invoice_date": inv.invoice_date,
            "invoice_total": inv.total,
            "pre_tax_amount": inv.pretax_subtotal,
            "currency": ctx.currency,
            "po": ctx.po["po_number"] if ctx.po else None,
            "po_selection": ctx.po_match.get("method"),
            "po_budget": ctx.budget or None,
            "payment_due_date": ctx.payment_due_date,
            "reasons": [
                {"severity": c.severity, "message": c.message} for c in ctx.findings if c.severity in ("review", "block", "warning")
            ],
            "notes": [c.message for c in ctx.findings if c.severity == "info"],
            "checks_passed": [c.message for c in ctx.checks if c.severity == "pass"],
            "suggested_action": ctx.actions.get("primary"),
        }
    )


def template_explanation(ctx: RunContext) -> str:
    inv = ctx.invoice
    vendor = ctx.vendor["name"] if ctx.vendor else (inv.vendor_name or "an unidentified vendor")
    what = f"Invoice {inv.invoice_number}" if inv.invoice_number else "This invoice"
    amount = f" for {ctx.money(inv.total)}" if inv.total is not None else ""
    head = f"{what} from {vendor}{amount}"
    reviews = [c for c in ctx.findings if c.severity == "review"]
    blocks = [c for c in ctx.findings if c.severity == "block"]
    infos = [c for c in ctx.findings if c.severity == "info"]

    if ctx.decision == "APPROVE":
        parts = [f"{head} was approved automatically."]
        if ctx.po:
            exact = all(m["variance_pct"] in (None, 0) for m in ctx.line_matches if m["price_checked"])
            if ctx.po["is_blanket"]:
                parts.append(f"It bills against blanket purchase order {ctx.po['po_number']} and fits within the remaining budget.")
            elif exact:
                parts.append(f"It matches purchase order {ctx.po['po_number']} line for line at the agreed prices.")
            else:
                parts.append(f"It matches purchase order {ctx.po['po_number']}, with price differences inside the allowed tolerance.")
        parts.append("The vendor is active, the bank details agree with our records and no duplicate was found.")
        parts += [c.message for c in infos if c.code != "CURRENCY_ASSUMED"]
        if ctx.payment_due_date:
            terms = ctx.vendor["payment_terms_days"] if ctx.vendor else 30
            parts.append(f"Payment is due on {ctx.payment_due_date.strftime('%B %-d, %Y')} under {terms}-day terms.")
        return " ".join(parts)

    if ctx.decision == "REJECT":
        parts = [f"{head} was rejected."] + [c.message for c in blocks]
        if reviews:
            labels = list(dict.fromkeys(CODE_LABELS.get(c.code, c.code.lower()) for c in reviews))
            parts.append(f"Other issues would also need review if it were resubmitted: {', '.join(labels)}.")
    else:
        n = len(reviews)
        parts = [f"{head} is on hold for review because {n} issue{'s' if n != 1 else ''} need{'s' if n == 1 else ''} a person to check {'it' if n == 1 else 'them'}."]
        parts += [c.message for c in reviews]
    if ctx.actions.get("primary"):
        parts.append(f"Suggested next step: {ctx.actions['primary']}")
    return " ".join(parts)


def run(ctx: RunContext) -> StageResult:
    llm_text = generate_text(ctx, EXPLAIN_PROMPT + json.dumps(_facts(ctx), indent=1))
    ctx.explanation = llm_text or template_explanation(ctx)
    source = f"{ctx.llm.provider}/{ctx.llm.model}" if llm_text else "deterministic template"
    words = len(ctx.explanation.split())
    return StageResult(f"Explanation written by {source} ({words} words)", {"source": source, "explanation": ctx.explanation})
