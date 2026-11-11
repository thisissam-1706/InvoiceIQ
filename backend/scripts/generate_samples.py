"""Builds the 13 demo invoices (four layouts, two fake scans) plus a manifest."""

import io
import json
import random
import sys
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pymupdf  # noqa: E402
from PIL import Image, ImageChops, ImageFilter  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import letter  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402
from reportlab.platypus import Table, TableStyle  # noqa: E402

from backend.app.settings import SAMPLES_DIR  # noqa: E402

PAGE_W, PAGE_H = letter
INK = colors.HexColor("#1f2937")
MUTED = colors.HexColor("#6b7280")
RULE = colors.HexColor("#d1d5db")

# Single source of truth for expected outcomes; run_batch.py and the e2e test import this.
EXPECTED: dict[str, dict] = {
    "01_acme_clean.pdf": {"decision": "APPROVE", "codes": []},
    "02_nimbus_tax_separate.pdf": {"decision": "APPROVE", "codes": ["PRICE_VARIANCE_WITHIN_TOL"]},
    "03_brightline_part1.pdf": {"decision": "APPROVE", "codes": []},
    "04_brightline_part2.pdf": {"decision": "APPROVE", "codes": ["PO_PARTIAL_CONSUMPTION"]},
    "05_brightline_part3_overrun.pdf": {"decision": "HOLD", "codes": ["PO_BUDGET_EXCEEDED"]},
    "06_acme_duplicate_reformatted.pdf": {"decision": "REJECT", "codes": ["DUPLICATE_INVOICE"]},
    "07_delta_scanned_no_po.pdf": {"decision": "HOLD", "codes": ["PO_INFERRED"]},
    "08_delta_scanned_missing_fields.pdf": {"decision": "HOLD", "codes": ["MISSING_INVOICE_NUMBER", "MISSING_TOTAL"]},
    "09_greenleaf_bank_changed.pdf": {"decision": "HOLD", "codes": ["BANK_DETAILS_MISMATCH"]},
    "10_unknown_vendor.pdf": {"decision": "HOLD", "codes": ["VENDOR_NOT_FOUND"]},
    "11_delta_price_overcharge.pdf": {"decision": "HOLD", "codes": ["PRICE_VARIANCE_EXCEEDS_TOL"]},
    "12_acme_math_error.pdf": {"decision": "HOLD", "codes": ["ARITHMETIC_MISMATCH"]},
    "13_orion_inactive_vendor.pdf": {"decision": "REJECT", "codes": ["VENDOR_INACTIVE"]},
}

BUYER = ["Harbor & Pine Retail Co.", "Attn: Accounts Payable", "500 Market Street", "San Francisco, CA 94105"]

VENDORS = {
    "acme": {
        "name": "Acme Office Supplies Inc.",
        "address": ["1200 Commerce Way, Suite 400", "Columbus, OH 43215"],
        "phone": "(614) 555-0180",
        "tax": ("Tax ID", "12-3456789"),
        "bank": ("First Ohio Bank", "021000021", "****4421"),
    },
    "nimbus": {
        "name": "Nimbus Cloud Services Ltd.",
        "address": ["88 Skyline Avenue, Floor 12", "San Jose, CA 95113"],
        "phone": "(408) 555-0127",
        "tax": ("EIN", "45-1122334"),
        "bank": ("Pacific Western Bank", "121000248", "XXXXXX3098"),
    },
    "brightline": {
        "name": "Brightline Logistics LLC",
        "address": ["4500 Freight Road", "Newark, NJ 07114"],
        "phone": "(973) 555-0142",
        "tax": ("Tax ID", "98-7654321"),
        "bank": ("Garden State Bank", "026009593", "****7710"),
    },
    "delta": {
        "name": "Delta Industrial Parts Co.",
        "address": ["77 Foundry Lane", "Pittsburgh, PA 15222"],
        "phone": "(412) 555-0199",
        "tax": ("EIN", "77-5544332"),
        "bank": ("Allegheny Trust", "011000138", "****6612"),
    },
    "greenleaf": {
        "name": "Greenleaf Catering Co.",
        "address": ["19 Orchard Street", "Austin, TX 78701"],
        "phone": "(512) 555-0163",
        "tax": ("Tax ID", "31-9988776"),
        "bank": ("Coastal Federal Credit Union", "314074269", "****8834"),
    },
    "zenith": {
        "name": "Zenith Print House",
        "address": ["301 Press Avenue", "Chicago, IL 60607"],
        "phone": "(312) 555-0111",
        "tax": ("Tax ID", "83-2210457"),
        "bank": ("Lakeshore Bank", "071000013", "****5521"),
    },
    "orion": {
        "name": "Orion Security Systems",
        "address": ["9 Sentinel Plaza", "Denver, CO 80202"],
        "phone": "(303) 555-0135",
        "tax": ("EIN", "66-4433221"),
        "bank": ("Front Range Bank", "111000025", "****9001"),
    },
}

ACME_LINES = [
    ("ACM-PPR-A4", "A4 copy paper, 80gsm, box of 5 reams", 50, "box", "42.00"),
    ("ACM-TNR-HP26", "HP 26A toner cartridge", 10, "ea", "115.00"),
    ("ACM-CHR-ERG", "Ergonomic mesh office chair", 2, "ea", "500.00"),
]
DELTA_LINES = [
    ("DLT-BRG-6204", "Ball bearing 6204-2RS", 400, "ea", "4.34"),
    ("DLT-BLT-M10", "Hex bolt M10x40, zinc", 2000, "ea", "0.62"),
    ("DLT-GSK-NBR", "NBR gasket 50mm", 300, "ea", "19.88"),
]


@dataclass
class Invoice:
    file: str
    scenario: str
    description: str
    layout: str
    vendor: str
    number_label: str
    number: Optional[str]
    date_label: str
    date: str
    due_label: str
    due: str
    lines: list[tuple]
    po_label: str = "PO Number"
    po: Optional[str] = None
    ref: Optional[str] = None
    tax_mode: str = "separate"  # separate | exempt | included
    tax_rate: Decimal = Decimal("0")
    subtotal_override: Optional[Decimal] = None
    notes: list[str] = field(default_factory=list)
    bank_notice: Optional[str] = None
    scanned: bool = False
    blank_totals: bool = False
    headline: bool = False

    @property
    def line_amounts(self) -> list[Decimal]:
        return [(Decimal(q) * Decimal(u)).quantize(Decimal("0.01")) for _, _, q, _, u in self.lines]

    @property
    def subtotal(self) -> Decimal:
        return self.subtotal_override if self.subtotal_override is not None else sum(self.line_amounts, Decimal("0"))

    @property
    def tax(self) -> Decimal:
        if self.tax_mode == "included":
            gross = self.subtotal
            return (gross - gross / (1 + self.tax_rate)).quantize(Decimal("0.01"), ROUND_HALF_UP)
        return (self.subtotal * self.tax_rate).quantize(Decimal("0.01"), ROUND_HALF_UP)

    @property
    def total(self) -> Decimal:
        return self.subtotal if self.tax_mode == "included" else self.subtotal + self.tax


def money(value: Decimal, symbol: str = "") -> str:
    return f"{symbol}{value:,.2f}"


def qty(q) -> str:
    return f"{q:,}" if isinstance(q, int) else str(q)


def pct(rate: Decimal) -> str:
    return f"{(rate * 100).normalize():f}%"


def totals_rows(inv: Invoice, symbol: str = "") -> list[tuple[str, str]]:
    if inv.tax_mode == "included":
        return [
            (f"Total (incl. {pct(inv.tax_rate)} sales tax)", money(inv.total, symbol)),
            (f"Includes {pct(inv.tax_rate)} sales tax of", money(inv.tax, symbol)),
        ]
    tax_label = "Sales tax (freight exempt)" if inv.tax_mode == "exempt" else f"Sales Tax ({pct(inv.tax_rate)})"
    return [("Subtotal", money(inv.subtotal, symbol)), (tax_label, money(inv.tax, symbol))]


def total_label(inv: Invoice) -> Optional[str]:
    return None if inv.tax_mode == "included" else {"A": "Total Due (USD)", "B": "Invoice Total USD", "C": "Amount Due", "D": "Total USD"}[inv.layout]


def text(c: canvas.Canvas, x: float, y: float, s: str, size: float = 9, font: str = "Helvetica", color=INK, align: str = "left"):
    c.setFont(font, size)
    c.setFillColor(color)
    {"left": c.drawString, "right": c.drawRightString, "center": c.drawCentredString}[align](x, y, s)


def draw_table(c: canvas.Canvas, data: list[list[str]], widths: list[float], x: float, y_top: float, style: list) -> float:
    table = Table(data, colWidths=widths)
    table.setStyle(TableStyle(style))
    _, h = table.wrapOn(c, sum(widths), 400)
    table.drawOn(c, x, y_top - h)
    return y_top - h


def draw_totals(c: canvas.Canvas, inv: Invoice, x_label: float, x_value: float, y: float, symbol: str = "", step: float = 15) -> float:
    rows = totals_rows(inv, symbol)
    label = total_label(inv)
    if label:
        rows.append((label, money(inv.total, symbol)))
    for i, (lab, val) in enumerate(rows):
        bold = i == len(rows) - 1 and label is not None or (inv.tax_mode == "included" and i == 0)
        font = "Helvetica-Bold" if bold else "Helvetica"
        text(c, x_label, y, lab, 9.5, font, align="right")
        if inv.blank_totals:
            c.setFillColor(colors.HexColor("#4b5563"))
            c.rect(x_value - 70, y - 3, 72, 12, stroke=0, fill=1)
        else:
            text(c, x_value, y, val, 9.5, font, align="right")
        y -= step
    return y


def bank_lines(inv: Invoice) -> list[str]:
    bank, routing, acct = VENDORS[inv.vendor]["bank"]
    return [f"Remit to: {bank}  |  Routing No. {routing}  |  Account No. {acct}"]


def layout_a(c: canvas.Canvas, inv: Invoice) -> None:
    """Classic: name top-left, meta block top-right, gridded table."""
    v = VENDORS[inv.vendor]
    text(c, 50, 742, v["name"], 18, "Helvetica-Bold")
    text(c, PAGE_W - 50, 742, "INVOICE", 22, "Helvetica-Bold", colors.HexColor("#374151"), "right")
    left = v["address"] + [f"Phone {v['phone']}", f"{v['tax'][0]}: {v['tax'][1]}"]
    right = [
        f"{inv.number_label}: {inv.number or ''}",
        f"{inv.date_label}: {inv.date}",
        f"{inv.due_label}: {inv.due}",
        f"{inv.po_label}: {inv.po}" if inv.po else (f"Ref: {inv.ref}" if inv.ref else ""),
    ]
    y = 720
    for l, r in zip(left, right):
        text(c, 50, y, l, 9.5, color=MUTED)
        text(c, PAGE_W - 50, y, r, 9.5, align="right")
        y -= 14
    y -= 14
    text(c, 50, y, "BILL TO", 8, "Helvetica-Bold", MUTED)
    for line in BUYER:
        y -= 13
        text(c, 50, y, line, 9.5)
    data = [["SKU", "Description", "Qty", "UOM", "Unit Price", "Amount"]]
    for (sku, desc, q, uom, unit), amt in zip(inv.lines, inv.line_amounts):
        data.append([sku or "", desc, qty(q), uom, money(Decimal(unit)), money(amt)])
    y = draw_table(
        c, data, [80, 222, 45, 40, 60, 65], 50, y - 26,
        [
            ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#9ca3af")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb")),
            ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5),
            ("FONT", (0, 1), (-1, -1), "Helvetica", 8.5),
            ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ],
    )
    y = draw_totals(c, inv, PAGE_W - 140, PAGE_W - 50, y - 22)
    y -= 30
    c.setStrokeColor(RULE)
    c.line(50, y + 12, PAGE_W - 50, y + 12)
    for line in bank_lines(inv) + [f"Payment terms: Net {VENDORS_TERMS[inv.vendor]}. Thank you for your business."] + inv.notes:
        text(c, 50, y, line, 8.5, color=MUTED)
        y -= 13


def layout_b(c: canvas.Canvas, inv: Invoice) -> None:
    """Modern: coloured header band, striped borderless table, '$' amounts."""
    v = VENDORS[inv.vendor]
    band = colors.HexColor("#1e3a5f")
    c.setFillColor(band)
    c.rect(0, PAGE_H - 95, PAGE_W, 95, stroke=0, fill=1)
    text(c, 45, PAGE_H - 50, v["name"], 19, "Helvetica-Bold", colors.white)
    text(c, PAGE_W - 45, PAGE_H - 50, "TAX INVOICE", 13, "Helvetica-Bold", colors.HexColor("#c7d2fe"), "right")
    text(c, 45, PAGE_H - 72, "  ·  ".join(v["address"] + [v["phone"]]), 8.5, color=colors.HexColor("#dbeafe"))
    y = PAGE_H - 130
    text(c, 45, y, "BILLED TO", 8, "Helvetica-Bold", MUTED)
    meta = [
        f"{inv.number_label} {inv.number or ''}",
        f"{inv.date_label} {inv.date}",
        f"{inv.due_label} {inv.due}",
        f"{inv.po_label} {inv.po}" if inv.po else (f"Ref: {inv.ref}" if inv.ref else ""),
        f"{v['tax'][0]} {v['tax'][1]}",
    ]
    for i, line in enumerate(BUYER + [""]):
        yy = y - 14 * (i + 1)
        text(c, 45, yy, line, 9.5)
        if i < len(meta):
            text(c, PAGE_W - 45, yy, meta[i], 9.5, align="right")
    y -= 14 * (len(BUYER) + 2) + 10
    data = [["Item Code", "Description", "Qty", "Rate", "Amount"]]
    for (sku, desc, q, _uom, unit), amt in zip(inv.lines, inv.line_amounts):
        data.append([sku or "", desc, qty(q), money(Decimal(unit), "$"), money(amt, "$")])
    stripes = [("BACKGROUND", (0, r), (-1, r), colors.HexColor("#f1f5f9")) for r in range(2, len(data), 2)]
    y = draw_table(
        c, data, [90, 240, 50, 70, 72], 45, y,
        [
            ("BACKGROUND", (0, 0), (-1, 0), band),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5),
            ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
            ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
            ("LINEBELOW", (0, -1), (-1, -1), 0.8, band),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ] + stripes,
    )
    y = draw_totals(c, inv, PAGE_W - 150, PAGE_W - 45, y - 24, "$", 16)
    y -= 34
    bank, routing, acct = v["bank"]
    for line in [f"Payment by ACH to {bank}, ABA {routing}, Acct No. {acct}", "Questions about this invoice? Reply to billing with the invoice number."] + inv.notes:
        text(c, 45, y, line, 8.5, color=MUTED)
        y -= 13


def layout_c(c: canvas.Canvas, inv: Invoice) -> None:
    """Letterhead: centred header, text-only table with rules, notes paragraph."""
    v = VENDORS[inv.vendor]
    mid = PAGE_W / 2
    text(c, mid, 745, v["name"], 17, "Times-Bold", align="center")
    text(c, mid, 728, "  ·  ".join(v["address"] + [v["phone"]]), 9, "Times-Roman", MUTED, "center")
    text(c, mid, 714, f"{v['tax'][0]} {v['tax'][1]}", 9, "Times-Roman", MUTED, "center")
    c.setStrokeColor(INK)
    c.setLineWidth(1.2)
    c.line(60, 702, PAGE_W - 60, 702)
    text(c, 60, 680, "Bill To:", 9.5, "Times-Bold")
    meta = [
        f"{inv.number_label}: {inv.number or ''}",
        f"{inv.date_label}: {inv.date}",
        f"{inv.due_label}: {inv.due}",
        f"{inv.po_label}: {inv.po}" if inv.po else (f"Order Ref: {inv.ref}" if inv.ref else ""),
    ]
    for i, line in enumerate(BUYER):
        yy = 666 - 13 * i
        text(c, 60, yy, line, 9.5, "Times-Roman")
        text(c, PAGE_W - 60, yy, meta[i], 9.5, "Times-Roman", align="right")
    data = [["Description", "Qty", "Unit", "Price", "Amount"]]
    for (_sku, desc, q, uom, unit), amt in zip(inv.lines, inv.line_amounts):
        data.append([desc, qty(q), uom, money(Decimal(unit)), money(amt)])
    y = draw_table(
        c, data, [262, 45, 40, 70, 75], 60, 600,
        [
            ("FONT", (0, 0), (-1, 0), "Times-Bold", 9.5),
            ("FONT", (0, 1), (-1, -1), "Times-Roman", 9.5),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK),
            ("LINEBELOW", (0, -1), (-1, -1), 0.5, RULE),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ],
    )
    y = draw_totals(c, inv, PAGE_W - 150, PAGE_W - 60, y - 22)
    y -= 26
    if inv.notes:
        text(c, 60, y, "Notes", 9.5, "Times-Bold")
        for note in inv.notes:
            y -= 13
            text(c, 60, y, note, 9.5, "Times-Roman")
        y -= 22
    bank, routing, acct = v["bank"]
    text(c, 60, y, f"Wire/ACH to {bank}: Routing No. {routing}, Account No. {acct}", 9, "Times-Roman", MUTED)


def layout_d(c: canvas.Canvas, inv: Invoice) -> None:
    """Compact: vendor block top-right, boxed meta strip, dark table header."""
    v = VENDORS[inv.vendor]
    c.setFillColor(colors.HexColor("#0f766e"))
    c.circle(72, 752, 20, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.circle(72, 752, 9, stroke=0, fill=1)
    y = 768
    text(c, PAGE_W - 50, y, v["name"], 14, "Helvetica-Bold", align="right")
    for line in v["address"] + [v["phone"], f"{v['tax'][0]} {v['tax'][1]}"]:
        y -= 13
        text(c, PAGE_W - 50, y, line, 8.5, color=MUTED, align="right")
    text(c, 50, 680, "Invoice", 26, "Helvetica-Bold", colors.HexColor("#0f766e"))
    boxes = [
        f"{inv.number_label}: {inv.number or ''}",
        f"{inv.date_label}: {inv.date}",
        f"{inv.po_label}: {inv.po}" if inv.po else f"Ref: {inv.ref or ''}",
    ]
    bw = (PAGE_W - 100) / 3
    c.setStrokeColor(colors.HexColor("#94a3b8"))
    for i, label in enumerate(boxes):
        c.rect(50 + i * bw, 636, bw, 26, stroke=1, fill=0)
        text(c, 58 + i * bw, 645, label, 9.5, "Helvetica-Bold")
    text(c, 50, 618, f"Terms: Net {VENDORS_TERMS.get(inv.vendor, 30)}   {inv.due_label}: {inv.due}", 9)
    text(c, 50, 596, "Customer:", 8, "Helvetica-Bold", MUTED)
    text(c, 100, 596, ", ".join(BUYER[:1] + BUYER[2:]), 9)
    data = [["#", "Item", "Description", "Qty", "UOM", "Unit", "Total"]]
    for i, ((sku, desc, q, uom, unit), amt) in enumerate(zip(inv.lines, inv.line_amounts), 1):
        data.append([str(i), sku or "", desc, qty(q), uom, money(Decimal(unit)), money(amt)])
    y = draw_table(
        c, data, [20, 80, 200, 50, 35, 55, 72], 50, 578,
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#134e4a")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5),
            ("FONT", (0, 1), (-1, -1), "Helvetica", 8.5),
            ("LINEBELOW", (0, 1), (-1, -1), 0.4, RULE),
            ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ],
    )
    y = draw_totals(c, inv, PAGE_W - 140, PAGE_W - 50, y - 22)
    y -= 30
    if inv.bank_notice:
        c.setFillColor(colors.HexColor("#fef3c7"))
        c.rect(50, y - 24, PAGE_W - 100, 38, stroke=0, fill=1)
        text(c, 58, y, inv.bank_notice, 9.5, "Helvetica-Bold")
        y -= 15
        text(c, 58, y, "  ".join(bank_lines(inv)[0].split("  |  ")[1:]) + f"  ({VENDORS[inv.vendor]['bank'][0]})", 9.5)
        y -= 30
    else:
        text(c, 50, y, bank_lines(inv)[0], 8.5, color=MUTED)
        y -= 14
    for note in inv.notes:
        text(c, 50, y, note, 8.5, color=MUTED)
        y -= 13


VENDORS_TERMS = {"acme": 30, "nimbus": 30, "brightline": 45, "delta": 60, "greenleaf": 15, "zenith": 30, "orion": 30}
LAYOUTS: dict[str, Callable[[canvas.Canvas, Invoice], None]] = {"A": layout_a, "B": layout_b, "C": layout_c, "D": layout_d}

INVOICES = [
    Invoice(
        "01_acme_clean.pdf", "Happy path", "Clean digital invoice that matches its PO line for line.",
        "A", "acme", "Invoice #", "INV-1001", "Invoice Date", "2026-10-03", "Due Date", "2026-11-02", ACME_LINES,
        po="PO-2026-0101",
    ),
    Invoice(
        "02_nimbus_tax_separate.pdf", "Within tolerance", "Compute billed 0.5% above PO price; 8% tax shown separately.",
        "B", "nimbus", "Inv No.", "NC-88213", "Date of Issue", "10/07/2026", "Payment Due", "11/06/2026",
        [("NMB-CMP-STD", "Cloud compute, standard tier, monthly", 3, "month", "1005.00"),
         ("NMB-SUP-PRM", "Premium support, monthly", 3, "month", "200.00")],
        po_label="Purchase Order", po="PO-2026-0103", tax_rate=Decimal("0.08"),
    ),
    Invoice(
        "03_brightline_part1.pdf", "Split PO, part 1", "First partial bill against a $12,000 blanket freight PO.",
        "C", "brightline", "Bill Number", "BL-5501", "Bill Date", "Oct 8, 2026", "Due By", "Nov 22, 2026",
        [(None, "LTL freight services, Q4 lanes - partial billing", 1, "lot", "6000.00")],
        po_label="Customer PO", po="PO-2026-0102", tax_mode="exempt", notes=["Partial billing 1 of N against blanket order."],
    ),
    Invoice(
        "04_brightline_part2.pdf", "Split PO, part 2", "Second partial bill; cumulative $11,500 of $12,000.",
        "C", "brightline", "Bill Number", "BL-5502", "Bill Date", "Oct 15, 2026", "Due By", "Nov 29, 2026",
        [(None, "LTL freight services, Q4 lanes - partial billing", 1, "lot", "5500.00")],
        po_label="Customer PO", po="PO-2026-0102", tax_mode="exempt", notes=["Partial billing 2 of N against blanket order."],
    ),
    Invoice(
        "05_brightline_part3_overrun.pdf", "Edge case: cumulative overbilling", "Third partial bill pushes the PO to $12,700 of $12,000.",
        "C", "brightline", "Bill Number", "BL-5503", "Bill Date", "Oct 22, 2026", "Due By", "Dec 6, 2026",
        [(None, "LTL freight services, Q4 lanes - partial billing", 1, "lot", "1200.00")],
        po_label="Customer PO", po="PO-2026-0102", tax_mode="exempt", notes=["Partial billing 3 of N against blanket order."],
        headline=True,
    ),
    Invoice(
        "06_acme_duplicate_reformatted.pdf", "Edge case: disguised duplicate", "Invoice 01 resent in a new layout as 'INV 1001' with a different date format.",
        "D", "acme", "Invoice No", "INV 1001", "Date", "Oct 3, 2026", "Due Date", "Nov 2, 2026", ACME_LINES,
        po_label="PO", po="PO-2026-0101", headline=True,
    ),
    Invoice(
        "07_delta_scanned_no_po.pdf", "Edge case: scanned + implied PO", "Image-only scan with no PO number, only 'Ref: bearing order Sept'.",
        "D", "delta", "Invoice No", "DLT-INV-3307", "Date", "Oct 1, 2026", "Due Date", "Nov 30, 2026", DELTA_LINES,
        ref="bearing order Sept", scanned=True, headline=True,
    ),
    Invoice(
        "08_delta_scanned_missing_fields.pdf", "Missing critical data", "Scanned invoice with no invoice number and the totals area blanked out.",
        "D", "delta", "Invoice No", None, "Date", "Oct 5, 2026", "Due Date", "Dec 4, 2026", DELTA_LINES,
        po_label="PO", po="PO-2026-0104", scanned=True, blank_totals=True,
    ),
    Invoice(
        "09_greenleaf_bank_changed.pdf", "Edge case: bank detail fraud signal", "Amounts match the PO exactly, but remit-to bank changed to an account ending 8834.",
        "D", "greenleaf", "Invoice No", "GL-2024", "Date", "06 Oct 2026", "Due Date", "21 Oct 2026",
        [("GLF-LUN-BOX", "Boxed lunch, team offsite", 50, "ea", "25.00"), ("GLF-BEV-PKG", "Beverage package", 1, "lot", "600.00")],
        po_label="PO", po="PO-2026-0105", bank_notice="Please note our new bank details for all future payments:", headline=True,
    ),
    Invoice(
        "10_unknown_vendor.pdf", "Vendor not in master", "Print shop that has never been onboarded; no PO.",
        "C", "zenith", "Invoice Number", "ZP-77", "Invoice Date", "Oct 12, 2026", "Due By", "Nov 11, 2026",
        [(None, "Business cards, premium matte, 500 pack", 20, "pack", "45.00"),
         (None, "Tri-fold brochures, full colour", 1000, "ea", "0.85")],
        ref="Phone order, marketing team", tax_rate=Decimal("0.0825"),
    ),
    Invoice(
        "11_delta_price_overcharge.pdf", "Price variance beyond tolerance", "Gaskets billed at $21.10 against a PO price of $19.88 (+6.1%).",
        "B", "delta", "Inv No.", "DLT-INV-3310", "Date of Issue", "10/14/2026", "Payment Due", "12/13/2026",
        DELTA_LINES[:2] + [("DLT-GSK-NBR", "NBR gasket 50mm", 300, "ea", "21.10")],
        po_label="Purchase Order", po="PO-2026-0104",
    ),
    Invoice(
        "12_acme_math_error.pdf", "Arithmetic inconsistency", "Subtotal printed as $4,520.00 but the lines add up to $4,250.00.",
        "A", "acme", "Invoice #", "INV-1009", "Invoice Date", "2026-10-16", "Due Date", "2026-11-15", ACME_LINES,
        po="PO-2026-0101", subtotal_override=Decimal("4520.00"),
    ),
    Invoice(
        "13_orion_inactive_vendor.pdf", "Inactive vendor", "Vendor is marked inactive in the master; prices include 5% tax.",
        "B", "orion", "Inv No.", "ORN-118", "Date of Issue", "10/09/2026", "Payment Due", "11/08/2026",
        [("ORN-CAM-4K", "4K security camera install", 10, "ea", "525.00")],
        po_label="Purchase Order", po="PO-2026-0107", tax_mode="included", tax_rate=Decimal("0.05"),
    ),
]


def render_pdf(inv: Invoice) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter, invariant=1)
    c.setTitle(f"Invoice {inv.number or ''}".strip())
    c.setAuthor(VENDORS[inv.vendor]["name"])
    LAYOUTS[inv.layout](c, inv)
    c.showPage()
    c.save()
    return buf.getvalue()


def fake_scan(pdf_bytes: bytes, seed: int) -> bytes:
    """Rasterise, tilt, add noise and blur, then wrap as an image-only PDF."""
    rng = random.Random(seed)
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    pix = doc[0].get_pixmap(dpi=150, colorspace=pymupdf.csGRAY)
    img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    angle = rng.uniform(0.5, 1.5) * rng.choice([-1, 1])
    img = img.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=255)
    img = ImageChops.add(img, Image.effect_noise(img.size, 18), scale=1.0, offset=-128)
    img = img.filter(ImageFilter.GaussianBlur(0.7))
    img = img.point(lambda p: max(0, min(255, int(p * 0.93 + 10))))
    out = io.BytesIO()
    img.save(out, "PDF", resolution=150)
    return out.getvalue()


def manifest() -> list[dict]:
    return [
        {
            "file": inv.file,
            "scenario": inv.scenario,
            "description": inv.description,
            "expected_decision": EXPECTED[inv.file]["decision"],
            "expected_codes": EXPECTED[inv.file]["codes"],
            "headline": inv.headline,
            "scanned": inv.scanned,
        }
        for inv in INVOICES
    ]


def main(out_dir: Path = SAMPLES_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for i, inv in enumerate(INVOICES):
        pdf = render_pdf(inv)
        if inv.scanned:
            pdf = fake_scan(pdf, seed=1000 + i)
        path = out_dir / inv.file
        path.write_bytes(pdf)
        written.append(path)
    (out_dir / "manifest.json").write_text(json.dumps(manifest(), indent=2))
    return written


if __name__ == "__main__":
    files = main()
    print(f"Wrote {len(files)} sample invoices to {SAMPLES_DIR}")
