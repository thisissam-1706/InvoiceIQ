# Assumptions and policy choices

Each entry gives the choice, then one line on why.

## Decision making

- **The LLM extracts; rules decide.** The model only fills a validated schema and writes the explanation. Approve, hold and reject come from deterministic Python. *Why:* decisions must be reproducible, auditable and immune to prompt drift.
- **Severity → decision:** any `block` → REJECT, else any `review` → HOLD, else APPROVE. `info` and `warning` never change the outcome. *Why:* one simple, explainable rule an AP manager can learn in a minute.
- **`never_auto_approve_on`** (default: `BANK_DETAILS_MISMATCH`, `PO_INFERRED`, `VENDOR_FUZZY_MATCH`) forces at least HOLD even if a finding's severity were downgraded. *Why:* these are the cases where a wrong auto-approval costs real money.
- **Inferred POs are never auto-approved.** A strong inference (score ≥ 0.80 and ≥ 0.15 ahead of the runner-up) selects the PO, so matching can continue, but the result is a HOLD. *Why:* the vendor did not claim that PO; a person must confirm it.
- **Bank-detail changes always hold** and are flagged `critical`. The suggested action is to call the vendor on the number in the vendor master. No vendor email is drafted for this case. *Why:* changed remit-to details on an invoice is the classic payment-fraud pattern, and replying to the invoice's own contact details would go to the fraudster.
- **A failed run is not a decision.** System errors (non-PDF, unreadable file, LLM failure) mark the run `failed` with the error, and the UI shows it as FAILED rather than HOLD. *Why:* a business hold and a broken pipeline need different people.

## Matching and money

- **Money is `Decimal`, stored as strings.** Rounding to 2 dp (`ROUND_HALF_UP`) happens only at comparison and display. A ±0.01 tolerance is used for arithmetic checks. *Why:* no float drift; one-cent rounding on printed invoices is normal.
- **PO consumption is pre-tax.** POs are issued pre-tax, so the invoice's pre-tax amount is what counts against them. When prices include tax and a rate is shown, tax is backed out as `amount / (1 + rate)`, also per unit for price comparison. *Why:* comparing a tax-inclusive total to a pre-tax PO would flag every taxed invoice.
- **Only APPROVE (or override-to-approve) consumes PO budget.** *Why:* held or rejected invoices have not been paid.
- **Blanket POs** are POs with a single `lot` line (PO-2026-0102). They skip per-unit price and quantity checks and use the budget check only, with `po_overrun_pct` (default 0%) as the allowed overrun. *Why:* partial billing of a lump-sum PO has no meaningful unit price.
- **Itemised PO budget slack.** For POs with real line items, the budget check allows the same slack as the total tolerance (`min(total_abs, total_pct × PO total)`, $25 by default). *Why:* otherwise a price difference already accepted by the ±2% unit-price tolerance (sample 02: +$15 on a $3,600 PO) would be penalised twice as a budget overrun.
- **Quantity checks** compare invoiced + previously billed quantity against the ordered quantity and, for physical goods, the received quantity. **Service and blanket lines (`uom` of `lot` or `month`) skip the goods-receipt check.** *Why:* services are not "received" into a warehouse.
- **Tolerance defaults:** unit price ±2% per line. Total within `min($25, 1% of expected)`. No blanket-PO overrun. Auto-approve limit $50,000. Minimum field confidence 0.70. Boundaries are inclusive: exactly 2.00% is within tolerance. *Why:* common AP defaults, kept conservative for a demo, and all editable in Settings.
- **Each run stores a snapshot of the config it used** (in `rules_json`). *Why:* history stays explainable after settings change.
- **Vendor matching:** an exact tax ID match wins. Otherwise fuzzy `token_sort_ratio` against the name and aliases after stripping suffixes such as Inc/LLC/Ltd/Co. ≥ 90 is a match, 75–89 holds as `VENDOR_FUZZY_MATCH`, < 75 is `VENDOR_NOT_FOUND` (route to onboarding). *Why:* a tax ID is an identifier; names are not.
- **Line pairing** goes by SKU first, then fuzzy description (`token_set_ratio` ≥ 80), with greedy best-first assignment. *Why:* simple, deterministic, and good enough for invoices with a handful of lines.

## Dates and data quality

- **Date ambiguity:** ISO and month-name dates are unambiguous. For `nn/nn/yyyy` where both parts are ≤ 12, the vendor's country decides: US/CA/PH read month-first, all others day-first. Normalisation runs before vendor matching, so it reads US-style by default and vendor matching re-resolves once the country is known. The reading chosen is recorded on the run. *Why:* the country is the only reliable signal, and it is unknown until the vendor is matched.
- **Currency:** taken from the invoice. If none is printed, the vendor's currency is used and `CURRENCY_ASSUMED` (info) is recorded. *Why:* all vendors in the master bill in one currency; the assumption stays visible.
- **Confidence adjustment:** scanned documents are capped at 0.85 per field. For digital PDFs, a field whose cited snippet (or value) cannot be found in the text layer drops to 0.5. *Why:* vision output is less certain, and a snippet missing from the text is a hallucination signal.
- **Missing total:** the line items are summed and offered as a *suggested* total in the message and the vendor email. The invoice is never paid on it automatically. *Why:* the vendor must confirm the amount owed.
- **Future-dated** means more than 3 days ahead of today (review). **Stale** means older than 180 days (warning only).

## Duplicates and resubmissions

- **Duplicate checks, in order:** identical file hash → same vendor + normalised invoice number → near-duplicate (same vendor and total, dates within 7 days, number similarity ≥ 85). The first two block; near-duplicates hold.
- **Rejected invoices do not block a resubmission.** Only non-rejected earlier runs count as duplicates. A resubmission of an invoice rejected for some other reason is allowed and flagged `RESUBMISSION` (info). *Why:* a vendor fixing a rejected invoice should not be stuck behind it.
- **Re-run** reprocesses a HOLD, REJECT or failed run with the current settings. The old run is marked *superseded* and drops out of duplicate checks and the needs-attention list. Approved runs cannot be re-run. *Why:* re-running an approved run would double-consume the PO; reset the demo data instead.

## System

- **A single background worker** processes runs one at a time from an in-memory queue. *Why:* PO consumption and duplicate detection read and write shared state. One worker removes race conditions without locks or a job system. On restart, queued runs are re-queued and runs that were mid-flight are marked failed (re-runnable).
- **The inbox folder simulates email.** `backend/data/inbox/` is polled every 3 s. A file is taken once its size is unchanged across two polls, then moved to `inbox/processed/` with a timestamp prefix. *Why:* a real deployment would connect to IMAP or the Gmail API and drop attachments into the same queue; the folder keeps the demo local.
- **The LLM provider sits behind one interface** (`extract`, `generate_text`). Gemini is the default (`gemini-2.5-flash`). If the configured model name is rejected with a 404, the client tries the closest Flash models (`gemini-2.0-flash`, `gemini-flash-latest`). A provider with no API key degrades to the offline extractor, with a visible note. *Why:* a live demo should never show a blank screen because of a missing key.
- **Offline mode replays recorded vision output for the two bundled scans.** The offline extractor cannot read images. For `07_…` and `08_…` it returns the JSON in `backend/tests/fixtures/`, written to match what a vision model returns for those pages. Any other scan gets empty fields and is held. *Why:* the tests and the no-key demo still exercise the full scanned path. The UI labels it "recorded vision extraction (offline mode)".
- **Explanations and vendor emails** are written by the LLM when one is available, constrained to the supplied facts. Otherwise they come from deterministic templates. Vendor emails are drafts only and never sent. *Why:* the wording can be AI-polished; sending stays a human decision.
- **Phase 4 was not verified with a real key** in this build environment: no Gemini or OpenAI key was available. The Gemini path was exercised with an invalid key to confirm clear error handling (the run fails at `llm_extract` with the API's message). Run `python backend/scripts/run_batch.py --provider gemini` once a key is in `.env`.
- **No authentication.** The reviewer in the audit trail is recorded as `reviewer`. *Why:* out of scope for a local, single-user demo; real roles would come from SSO.
