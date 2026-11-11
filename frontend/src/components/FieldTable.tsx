import { Extraction, ExtractedField } from "../api";
import { ScanIcon } from "./Icons";

const FIELDS: [string, string][] = [
  ["vendor_name", "Vendor"],
  ["vendor_tax_id", "Vendor tax ID"],
  ["invoice_number", "Invoice #"],
  ["invoice_date", "Invoice date"],
  ["due_date", "Due date"],
  ["po_reference", "PO reference"],
  ["reference_notes", "Other reference"],
  ["currency", "Currency"],
  ["subtotal", "Subtotal"],
  ["tax_amount", "Tax"],
  ["tax_rate", "Tax rate"],
  ["tax_included_in_prices", "Tax included"],
  ["total", "Total"],
  ["bank_account_last4", "Bank acct (last 4)"],
  ["bank_routing", "Bank routing"],
  ["remit_notes", "Remit notes"],
];

const REQUIRED = new Set(["vendor_name", "invoice_number", "invoice_date", "total"]);

function display(name: string, f: ExtractedField): string {
  if (f.value === null) return "—";
  if (typeof f.value === "boolean") return f.value ? "yes" : "no";
  if (name === "tax_rate") return `${(Number(f.value) * 100).toFixed(2).replace(/\.?0+$/, "")}%`;
  if (name === "bank_account_last4") return `•••• ${f.value}`;
  return String(f.value);
}

export default function FieldTable({ extraction, minConfidence }: { extraction: Extraction | null; minConfidence: number }) {
  if (!extraction) return <div className="px-4 py-6 text-sm text-slate-400">Fields appear after AI extraction.</div>;
  const { fields, meta } = extraction;
  const scanned = meta.mode.startsWith("vision");

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-4 py-2.5 text-xs text-slate-500">
        {scanned && (
          <span className="inline-flex items-center gap-1 rounded-md bg-violet-50 px-2 py-0.5 font-medium text-violet-700 ring-1 ring-inset ring-violet-600/20">
            <ScanIcon className="h-3.5 w-3.5" /> Scanned document · vision extraction
          </span>
        )}
        <span>
          {meta.fields_found}/{meta.fields_total} fields · avg confidence {meta.avg_confidence.toFixed(2)}
          {meta.cached && " · cached"}
        </span>
        {meta.confidence_cap !== null && <span className="text-violet-600">confidence capped at {meta.confidence_cap}</span>}
      </div>
      <table className="w-full">
        <tbody className="divide-y divide-slate-100">
          {FIELDS.map(([name, label]) => {
            const f = fields[name] as ExtractedField | undefined;
            if (!f) return null;
            const missing = f.value === null;
            const low = !missing && f.confidence < minConfidence;
            const flagged = low || (missing && REQUIRED.has(name));
            return (
              <tr key={name} className={flagged ? "bg-amber-50" : ""} title={f.source_text ? `Source: “${f.source_text}”` : "No source snippet"}>
                <td className="w-[38%] px-4 py-1.5 text-xs text-slate-500">
                  {label}
                  {REQUIRED.has(name) && <span className="text-rose-400">*</span>}
                </td>
                <td className={`px-2 py-1.5 text-[13px] ${missing ? "text-slate-400" : "text-slate-900"} ${flagged ? "font-medium text-amber-800" : ""}`}>
                  <span className="line-clamp-2 break-words">{display(name, f)}</span>
                </td>
                <td className="w-24 px-4 py-1.5">
                  {!missing && (
                    <div className="flex items-center gap-1.5">
                      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
                        <div
                          className={`h-full rounded-full ${f.confidence >= 0.85 ? "bg-emerald-500" : f.confidence >= minConfidence ? "bg-amber-400" : "bg-rose-500"}`}
                          style={{ width: `${Math.round(f.confidence * 100)}%` }}
                        />
                      </div>
                      <span className="w-7 text-right text-[11px] tabular-nums text-slate-500">{f.confidence.toFixed(2)}</span>
                    </div>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {!!fields.line_items?.length && (
        <div className="border-t border-slate-100 px-4 py-2 text-xs text-slate-500">
          {fields.line_items.length} line item{fields.line_items.length === 1 ? "" : "s"} extracted (see line match table)
        </div>
      )}
    </div>
  );
}
