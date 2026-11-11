import json
import re
from typing import Optional

from rapidfuzz import fuzz
from sqlmodel import select

from .. import db
from ..models import Vendor
from . import RunContext, StageResult
from .normalise import MONTH_FIRST_COUNTRIES, parse_date

MATCH_THRESHOLD = 90
FUZZY_THRESHOLD = 75
_SUFFIXES = {"inc", "llc", "ltd", "co", "corp", "corporation", "company", "limited", "plc", "the"}


def normalise_vendor_name(name: str) -> str:
    tokens = re.sub(r"[^\w\s]", " ", name.lower()).split()
    return " ".join(t for t in tokens if t not in _SUFFIXES)


def _digits(s: Optional[str]) -> str:
    return re.sub(r"\D", "", s or "")


def vendor_dict(v: Vendor) -> dict:
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


def best_vendor(name: Optional[str], tax_id: Optional[str], vendors: list[dict]) -> tuple[Optional[dict], float, str]:
    """Returns (vendor, score 0-100, method)."""
    if tax_id:
        for v in vendors:
            if v["tax_id"] and _digits(v["tax_id"]) == _digits(tax_id):
                return v, 100.0, "tax_id"
    if not name:
        return None, 0.0, "none"
    query = normalise_vendor_name(name)
    best, best_score = None, 0.0
    for v in vendors:
        for candidate in [v["name"], *v["aliases"]]:
            score = fuzz.token_sort_ratio(query, normalise_vendor_name(candidate))
            if score > best_score:
                best, best_score = v, score
    return best, best_score, "fuzzy_name"


def run(ctx: RunContext) -> StageResult:
    inv = ctx.invoice
    with db.session() as s:
        vendors = [vendor_dict(v) for v in s.exec(select(Vendor)).all()]

    vendor, score, method = best_vendor(inv.vendor_name, inv.vendor_tax_id, vendors)
    ctx.vendor_match = {"method": method, "score": round(score, 1), "candidate": vendor["name"] if vendor else None}

    if vendor is None or score < FUZZY_THRESHOLD:
        ctx.vendor = None
        ctx.vendor_match["status"] = "not_found"
        name = inv.vendor_name or "the vendor"
        ctx.add(
            "VENDOR_NOT_FOUND", "review",
            f"'{name}' is not in the vendor master (closest match scored {score:.0f}/100). Unknown vendors cannot be paid until they are onboarded.",
            data={"vendor_name": inv.vendor_name, "best_score": round(score, 1), "closest": vendor["name"] if vendor else None},
        )
        return StageResult(f"Vendor '{name}' not found in master (best score {score:.0f})", ctx.vendor_match)

    ctx.vendor = vendor
    if score >= MATCH_THRESHOLD:
        ctx.vendor_match["status"] = "matched"
        how = "tax ID" if method == "tax_id" else f"name similarity {score:.0f}/100"
        ctx.passed("VENDOR_MATCHED", f"Matched vendor {vendor['name']} ({vendor['vendor_id']}) by {how}.")
    else:
        ctx.vendor_match["status"] = "fuzzy"
        ctx.add(
            "VENDOR_FUZZY_MATCH", "review",
            f"The vendor name '{inv.vendor_name}' only loosely matches {vendor['name']} ({score:.0f}/100). Confirm it is the same company.",
            data={"candidate": vendor["vendor_id"], "score": round(score, 1)},
        )

    if vendor["status"] != "active":
        ctx.add(
            "VENDOR_INACTIVE", "block",
            f"{vendor['name']} is marked '{vendor['status']}' in the vendor master. Invoices from inactive vendors are not paid.",
            data={"status": vendor["status"]},
        )
    else:
        ctx.passed("VENDOR_ACTIVE", f"{vendor['name']} is an active vendor.")

    bank_diffs = []
    if inv.bank_last4 and vendor["bank_account_last4"] and inv.bank_last4 != vendor["bank_account_last4"]:
        bank_diffs.append(f"account ending {inv.bank_last4} (master: {vendor['bank_account_last4']})")
    if inv.bank_routing and vendor["bank_routing"] and inv.bank_routing != _digits(vendor["bank_routing"]):
        bank_diffs.append(f"routing {inv.bank_routing} (master: {vendor['bank_routing']})")
    if bank_diffs:
        notice = f" The invoice also says: \"{inv.remit_notes.rstrip(' :.')}\"." if inv.remit_notes else ""
        ctx.add(
            "BANK_DETAILS_MISMATCH", "review",
            f"The remit-to bank details on the invoice differ from the vendor master: {'; '.join(bank_diffs)}.{notice} "
            "Bank-change requests on invoices are a common payment-fraud pattern and must be verified by calling the vendor "
            "on a number already on file, not one printed on the invoice.",
            critical=True,
            data={"invoice_last4": inv.bank_last4, "master_last4": vendor["bank_account_last4"], "invoice_routing": inv.bank_routing, "master_routing": vendor["bank_routing"]},
        )
    elif inv.bank_last4 or inv.bank_routing:
        ctx.passed("BANK_DETAILS_MATCH", f"Remit-to bank details match the vendor master (account ending {vendor['bank_account_last4']}).")
    else:
        ctx.passed("BANK_DETAILS_ABSENT", "No bank details printed on the invoice; payment goes to the account on file.")

    if inv.vendor_tax_id and vendor["tax_id"] and _digits(inv.vendor_tax_id) != _digits(vendor["tax_id"]):
        ctx.add(
            "TAX_ID_MISMATCH", "review",
            f"The tax ID on the invoice ({inv.vendor_tax_id}) does not match {vendor['name']}'s tax ID on file ({vendor['tax_id']}).",
        )
    elif inv.vendor_tax_id:
        ctx.passed("TAX_ID_MATCH", f"Tax ID {inv.vendor_tax_id} matches the vendor master.")

    if inv.date_ambiguous and inv.invoice_date_raw:
        month_first = vendor["country"] in MONTH_FIRST_COUNTRIES
        inv.invoice_date, reading, _ = parse_date(inv.invoice_date_raw, month_first)
        inv.date_reading = f"{reading} ({vendor['country']} vendor)"
        inv.due_date, _, _ = parse_date(inv.due_date_raw, month_first)

    if not inv.currency:
        inv.currency = vendor["currency"]
        inv.currency_assumed = True
        ctx.add("CURRENCY_ASSUMED", "info", f"No currency printed; assumed the vendor's currency ({vendor['currency']}).")

    how = "tax ID" if method == "tax_id" else f"fuzzy name {score:.0f}"
    return StageResult(
        f"Matched {vendor['name']} ({vendor['vendor_id']}) by {how}; status {vendor['status']}"
        + ("; BANK DETAILS DIFFER" if bank_diffs else ""),
        {**ctx.vendor_match, "vendor": vendor, "date_reading": inv.date_reading},
    )
