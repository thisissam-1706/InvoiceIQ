# InvoiceIQ: 5-minute demo script

## Pre-demo checklist

1. `./run.sh` and open `http://localhost:8000`. Check that the sidebar footer shows the provider you expect (e.g. `gemini · gemini-2.5-flash`).
2. If you are using a real LLM, **warm the cache**: run `python backend/scripts/run_batch.py --provider gemini` once (it resets the data). Every sample is then cached, so the live demo does not wait on the API.
3. **Reset the demo data**: Settings → Reset demo data → confirm.
4. Settings: stage delay **350 ms**, unit price tolerance **0.02**. Save.
5. Close other tabs and notifications. Use a 1440-px-wide window, with New Run open in one tab and the Dashboard in another.
6. Keep the run order handy: **01 → 03 → 04 → 05 → 06 → 07 → 09**.

## Script

**0:00–0:30 Framing.**
"An AP clerk gets hundreds of vendor PDFs a week: clean ones, scans, and the occasional bad one on a Friday afternoon. InvoiceIQ processes each invoice end to end. The design principle is simple: *AI reads the invoice, rules make the decision, and every step is visible.*"

**0:30–1:30 Happy path (01).**
- New Run → *01 Happy path* → **Run**. Narrate the timeline as it fills: ingest, text extraction, AI field extraction, normalisation, validation, vendor match by tax ID, PO match, duplicate check, rules, decision, explanation.
- Point at the PDF next to the extracted fields and their confidence bars.
- Scroll to Matching: every line pairs by SKU with 0.0% variance.
- Read the APPROVED explanation and the payment due date. Reference Data → PO-2026-0101 is now 100% consumed and linked to this invoice.

**1:30–2:15 Edge case: split PO overrun (03, 04, 05).**
- Run 03, then 04 (both approve, and the PO ledger climbs to 96%). Then run **05**.
- The PO budget bar crosses 100% in red: "$12,000 PO, $11,500 already consumed, this bill $1,200, **over by $700**." The decision is HOLD with a concrete action: "raise a change order for $700.00 or request a revised invoice."

**2:15–2:50 Edge case: disguised duplicate (06).**
- Run 06. The layout is different, the number is written "INV 1001" and the date is "Oct 3, 2026", yet normalisation reduces both to `INV1001` for the same vendor.
- The result is **REJECTED**, with a link to the original run (Matching → "open original run").

**2:50–3:40 Edge case: scanned invoice without a PO (07).**
- Run 07. Text extraction reports "Scanned PDF (no text layer)", and the fields carry the **Scanned document · vision extraction** badge with confidences capped at 0.85.
- Matching: "PO inference scoring". PO-2026-0104 scores 1.00 (line match 1.00, amount fit 1.00).
- Explain the policy: "We found the PO, but the vendor never quoted it, so a person confirms. Inferred POs are never auto-approved."

**3:40–4:20 Edge case: bank details changed (09).**
- Run 09. Every check passes except one: the remit-to account ends **8834** against **2250** on file, with "Please note our new bank details". It is flagged **critical**.
- "This is the classic invoice-fraud pattern, so it never auto-approves. Notice there is no vendor email draft: the action is to call the number already on file."
- Click **Approve…**, type "Called Greenleaf on file number; change confirmed by J. Ruiz", and confirm. The badge becomes **APPROVED (override)**, the audit trail shows the reviewer note, and the PO is consumed.

**4:20–5:00 Dashboard and settings.**
- Dashboard: the stat tiles, the cumulative decisions chart, top finding codes, and the needs-attention list (oldest HOLD first).
- Settings: change the unit price tolerance from 0.02 to 0.05 and save. Open run 05 or 07: their *Tolerance & rules* step still says ±2%, because each run snapshots the config it used.
- Close with what production would add: IMAP or Gmail intake, ERP connectors for vendors, POs and receipts, reviewer roles and approval limits, vendor-specific extraction templates, and learning from overrides.

## Likely interviewer questions

**Why not let the LLM decide?**
Payment decisions need to be deterministic, explainable and auditable. The LLM does what it is good at: reading messy documents and writing plain English. Python rules make the call, every rule shows up as a pass or fail row, and the config used is snapshotted per run.

**How are hallucinations handled?**
In layers:
- The output must validate against a Pydantic schema, with one retry that shows the model its error.
- For digital PDFs, every field cites a source snippet. If that snippet is not in the text layer, the field's confidence drops to 0.5. Scans are capped at 0.85.
- Required fields below 0.70 hold the invoice.
- Arithmetic is re-checked independently, and everything is matched against master data, so an invented PO or amount fails a hard check.
- The explanation prompt allows only the supplied facts.

**What happens at 10,000 invoices a month?**
That is about 500 a working day, and the single worker handles it easily; the LLM call dominates at a few seconds each. Beyond that:
- Move to Postgres with row-level locking on PO consumption.
- Run N workers, partitioned by vendor or PO so budget checks stay serial per PO.
- Batch LLM calls, and keep the response cache.
- Watch the auto-approve rate and the top finding codes to tune tolerances per vendor.

**How would you add a new rule?**
Add a function in the relevant stage (usually `pipeline/rules.py`) that calls `ctx.add(code, severity, message, data=...)` or `ctx.passed(...)`. Give it a label in `CODE_LABELS` and an action in `decision.ACTIONS`, then add a unit test that includes the boundary. The decision logic, UI checklist, explanation, stats and Settings checkbox pick it up automatically.

**What if the vendor sends a credit note?**
Today it would be extracted with a negative total and held, because its arithmetic and PO budget do not fit an invoice. Properly supporting it means:
- Add a `document_type` field to the extraction schema.
- Link the credit note to the original invoice by reference.
- Release the PO consumption instead of adding to it.
- Hold whenever the original cannot be found.
