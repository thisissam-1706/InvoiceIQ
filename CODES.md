# Finding codes

Every check in the pipeline reports a **finding code**. The app shows the *Display name* below; the raw code
appears only as small grey text on the Run Detail page, for debugging.

This file is generated from the `ctx.add(...)` / `ctx.passed(...)` calls and from `DISPLAY_LABELS` in
`backend/app/pipeline/__init__.py`. Regenerate it with `python backend/scripts/gen_codes_doc.py`.

**Effect on decision:** any `block` finding gives **REJECT**; otherwise any `review` finding gives **HOLD**;
otherwise **APPROVE**. `warning` and `info` findings are shown but do not change the decision by themselves
(an admin can still list any code under *Never auto-approve* in Settings to force HOLD). `pass` means the check succeeded.

## validate

| Code | Display name | What it means | Severity | Pipeline stage | Effect on decision (APPROVE/HOLD/REJECT) |
|---|---|---|---|---|---|
| `ARITHMETIC_MISMATCH` | Invoice amounts don't add up | The line amounts, subtotal, tax and total on the invoice do not agree with each other. | review | validate | HOLD |
| `FUTURE_DATED` | Invoice dated in the future | The invoice date is later than today. | review | validate | HOLD |
| `LOW_EXTRACTION_CONFIDENCE` | Some fields were hard to read | One or more key fields were read with low confidence and should be checked against the PDF. | review | validate | HOLD |
| `MISSING_INVOICE_DATE` | Invoice date not found | No readable invoice date was found on the document. | review | validate | HOLD |
| `MISSING_INVOICE_NUMBER` | Invoice number not found | No invoice number could be read from the document. | review | validate | HOLD |
| `MISSING_TOTAL` | Invoice total not found | No invoice total could be read from the document. | review | validate | HOLD |
| `MISSING_VENDOR_NAME` | Vendor name not found | No vendor name could be read from the document. | review | validate | HOLD |
| `STALE_INVOICE` | Invoice is unusually old | The invoice date is older than the accepted window. | warning | validate | None (shown only) |
| `ARITHMETIC_OK` | Invoice amounts add up | Line amounts, subtotal, tax and total are consistent with each other. | pass | validate | None (check passed) |
| `EXTRACTION_CONFIDENCE_OK` | All fields read clearly | All key fields were read with enough confidence. | pass | validate | None (check passed) |
| `INVOICE_DATE_PLAUSIBLE` | Invoice date looks reasonable | The invoice date is within the accepted window. | pass | validate | None (check passed) |
| `INVOICE_DATE_PRESENT` | Invoice date found | An invoice date was read from the document. | pass | validate | None (check passed) |
| `INVOICE_NUMBER_PRESENT` | Invoice number found | An invoice number was read from the document. | pass | validate | None (check passed) |
| `TOTAL_PRESENT` | Invoice total found | An invoice total was read from the document. | pass | validate | None (check passed) |
| `VENDOR_NAME_PRESENT` | Vendor name found | A vendor name was read from the document. | pass | validate | None (check passed) |

## vendor_match

| Code | Display name | What it means | Severity | Pipeline stage | Effect on decision (APPROVE/HOLD/REJECT) |
|---|---|---|---|---|---|
| `VENDOR_INACTIVE` | Vendor is inactive | The vendor is marked inactive in the vendor master, so invoices from them are not paid. | block | vendor_match | REJECT |
| `BANK_DETAILS_MISMATCH` | Bank details differ from records | The bank details printed on the invoice differ from those on file for this vendor, a common fraud pattern. | review (critical) | vendor_match | HOLD |
| `TAX_ID_MISMATCH` | Tax ID differs from records | The tax ID on the invoice does not match the one on file for this vendor. | review | vendor_match | HOLD |
| `VENDOR_FUZZY_MATCH` | Vendor name only loosely matches | The vendor name is similar to, but not the same as, a vendor in the vendor master. | review | vendor_match | HOLD |
| `VENDOR_NOT_FOUND` | Vendor not in vendor list | The vendor on the invoice does not match any vendor in the vendor master. | review | vendor_match | HOLD |
| `CURRENCY_ASSUMED` | Currency assumed | The invoice shows no currency, so the vendor's usual currency was assumed. | info | vendor_match | None (shown only) |
| `BANK_DETAILS_ABSENT` | No bank details on invoice | The invoice shows no bank details, so payment goes to the account on file. | pass | vendor_match | None (check passed) |
| `BANK_DETAILS_MATCH` | Bank details match records | The bank details on the invoice match those on file for this vendor. | pass | vendor_match | None (check passed) |
| `TAX_ID_MATCH` | Tax ID matches records | The tax ID on the invoice matches the one on file for this vendor. | pass | vendor_match | None (check passed) |
| `VENDOR_ACTIVE` | Vendor is active | The matched vendor is active in the vendor master. | pass | vendor_match | None (check passed) |
| `VENDOR_MATCHED` | Vendor recognised | The vendor on the invoice was matched to a vendor in the vendor master. | pass | vendor_match | None (check passed) |

## po_match

| Code | Display name | What it means | Severity | Pipeline stage | Effect on decision (APPROVE/HOLD/REJECT) |
|---|---|---|---|---|---|
| `PO_CLOSED` | Purchase order is closed | The purchase order is closed or cancelled, so no more invoices can be paid against it. | block | po_match | REJECT |
| `PO_BUDGET_EXCEEDED` | Purchase order budget exceeded | This invoice would take the purchase order over its remaining budget. | review | po_match | HOLD |
| `PO_INFERRED` | Purchase order guessed, not quoted | The invoice has no PO number, so the system picked the most likely open PO. A person should confirm it. | review | po_match | HOLD |
| `PO_MISSING` | No purchase order | The invoice has no PO number and no open PO could be matched with confidence. | review | po_match | HOLD |
| `PO_NOT_FOUND` | Purchase order not found | The invoice quotes a purchase order number that does not exist. | review | po_match | HOLD |
| `PO_VENDOR_MISMATCH` | PO belongs to another vendor | The purchase order quoted on the invoice was issued to a different vendor. | review | po_match | HOLD |
| `QTY_EXCEEDS_PO` | Quantity above purchase order | The invoice bills more units than were ordered on the purchase order. | review | po_match | HOLD |
| `QTY_EXCEEDS_RECEIVED` | Quantity above goods received | The invoice bills more units than the warehouse has received. | review | po_match | HOLD |
| `UNMATCHED_LINE` | Lines not on the purchase order | One or more invoice lines do not correspond to any line on the purchase order. | review | po_match | HOLD |
| `PO_PARTIAL_CONSUMPTION` | Purchase order partly used | This invoice uses up part of the purchase order budget; some remains. | info | po_match | None (shown only) |
| `ALL_LINES_MATCHED` | All lines matched to PO | Every invoice line matches a line on the purchase order. | pass | po_match | None (check passed) |
| `PO_BUDGET_OK` | Within purchase order budget | The invoice fits within the remaining budget of the purchase order. | pass | po_match | None (check passed) |
| `PO_FOUND` | Purchase order found | The purchase order quoted on the invoice exists and belongs to this vendor. | pass | po_match | None (check passed) |
| `QTY_WITHIN_PO_AND_RECEIPTS` | Quantities within PO and receipts | Billed quantities do not exceed what was ordered or received. | pass | po_match | None (check passed) |

## duplicates

| Code | Display name | What it means | Severity | Pipeline stage | Effect on decision (APPROVE/HOLD/REJECT) |
|---|---|---|---|---|---|
| `DUPLICATE_INVOICE` | Duplicate invoice | This invoice, or one with the same vendor and number, has already been processed. | block | duplicates | REJECT |
| `POSSIBLE_DUPLICATE` | Possible duplicate invoice | This invoice looks very similar to an earlier one from the same vendor. | review | duplicates | HOLD |
| `RESUBMISSION` | Resubmitted after rejection | This invoice was rejected earlier for another reason and has been submitted again. | info | duplicates | None (shown only) |
| `NO_DUPLICATE` | No duplicate found | No earlier invoice matches this one. | pass | duplicates | None (check passed) |

## rules

| Code | Display name | What it means | Severity | Pipeline stage | Effect on decision (APPROVE/HOLD/REJECT) |
|---|---|---|---|---|---|
| `AMOUNT_ABOVE_AUTO_LIMIT` | Above auto-approval limit | The amount is above the limit for automatic approval and needs manual sign-off. | review | rules | HOLD |
| `PRICE_VARIANCE_EXCEEDS_TOL` | Price above allowed tolerance | A unit price differs from the purchase order by more than the allowed tolerance. | review | rules | HOLD |
| `TOTAL_VARIANCE_EXCEEDS_TOL` | Total outside allowed tolerance | The invoice total differs from the expected total by more than the allowed amount. | review | rules | HOLD |
| `PRICE_VARIANCE_WITHIN_TOL` | Price differs, within tolerance | A unit price differs from the purchase order but is within the allowed tolerance. | info | rules | None (shown only) |
| `PRICES_MATCH_PO` | Prices match purchase order | All unit prices match the purchase order exactly. | pass | rules | None (check passed) |
| `TOTAL_WITHIN_TOL` | Total within allowed tolerance | The invoice total is close enough to the expected total. | pass | rules | None (check passed) |
| `WITHIN_AUTO_LIMIT` | Within auto-approval limit | The amount is within the limit for automatic approval. | pass | rules | None (check passed) |
