import { LineMatch, money, pct } from "../api";

function varianceClass(v: number, tol: number): string {
  if (v === 0) return "text-slate-500";
  return Math.abs(v) <= tol ? "text-amber-600" : "font-semibold text-rose-600";
}

function qty(value: string | null): string {
  if (value === null) return "—";
  const n = Number(value);
  return Number.isInteger(n) ? n.toLocaleString() : String(n);
}

export default function LineMatchTable({ lines, currency, tolerance }: { lines: LineMatch[]; currency: string | null; tolerance: number }) {
  if (!lines.length) return <div className="px-4 py-5 text-sm text-slate-400">No invoice lines were paired to a PO.</div>;
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full">
        <thead className="border-b border-slate-200 bg-slate-50/60">
          <tr>
            <th className="th">Invoice line ↔ PO line</th>
            <th className="th text-right">Qty</th>
            <th className="th text-right">Billed before</th>
            <th className="th text-right">Received</th>
            <th className="th text-right">Invoice price</th>
            <th className="th text-right">PO price</th>
            <th className="th text-right">Variance</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {lines.map((m) => {
            const v = m.variance_pct === null ? null : Number(m.variance_pct);
            const service = m.uom === "lot" || m.uom === "month";
            return (
              <tr key={`${m.invoice_line}-${m.po_line_no}`}>
                <td className="td">
                  <div className="font-medium text-slate-800">{m.description}</div>
                  <div className="text-xs text-slate-500">
                    ↔ PO line {m.po_line_no}: {m.po_description}{" "}
                    <span className="text-slate-400">({m.match_method === "sku" ? `SKU ${m.po_sku}` : `text match ${Math.round(m.match_score)}`})</span>
                  </div>
                </td>
                <td className="td text-right tabular-nums">
                  {qty(m.invoice_qty)} <span className="text-xs text-slate-400">/ {qty(m.po_qty)} {m.uom}</span>
                </td>
                <td className="td text-right tabular-nums text-slate-500">{qty(m.already_billed_qty)}</td>
                <td className="td text-right tabular-nums text-slate-500">{service ? <span className="text-xs">n/a ({m.uom})</span> : qty(m.received_qty)}</td>
                <td className="td text-right tabular-nums">{money(m.invoice_unit_price, currency)}</td>
                <td className="td text-right tabular-nums text-slate-500">{money(m.po_unit_price, currency)}</td>
                <td className={`td text-right tabular-nums ${m.price_checked && v !== null ? varianceClass(v, tolerance) : "text-slate-400"}`}>
                  {!m.price_checked ? <span className="text-xs">budget only</span> : v === null ? "—" : v === 0 ? "0.0%" : pct(v)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function BudgetBar({
  total,
  consumedBefore,
  thisInvoice,
  currency,
  label,
}: {
  total: number;
  consumedBefore: number;
  thisInvoice: number;
  currency: string | null;
  label?: string;
}) {
  const scale = Math.max(total, consumedBefore + thisInvoice);
  const before = (Math.min(consumedBefore, scale) / scale) * 100;
  const mine = (thisInvoice / scale) * 100;
  const limit = (total / scale) * 100;
  const after = consumedBefore + thisInvoice;
  const over = after - total;
  const fits = over <= 0.005;

  return (
    <div>
      {label && <div className="mb-1.5 text-xs font-medium text-slate-600">{label}</div>}
      <div className="relative h-4 w-full overflow-hidden rounded-full bg-slate-100">
        <div className="absolute inset-y-0 left-0 bg-slate-400" style={{ width: `${before}%` }} />
        <div className={`absolute inset-y-0 ${fits ? "bg-indigo-500" : "bg-rose-500"}`} style={{ left: `${before}%`, width: `${mine}%` }} />
        {!fits && <div className="absolute inset-y-0 w-0.5 bg-slate-900" style={{ left: `calc(${limit}% - 1px)` }} title="PO total" />}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">
        <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-slate-400" />Consumed before {money(consumedBefore, currency)}</span>
        <span className="flex items-center gap-1.5"><span className={`h-2 w-2 rounded-sm ${fits ? "bg-indigo-500" : "bg-rose-500"}`} />This invoice {money(thisInvoice, currency)}</span>
        <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-slate-100 ring-1 ring-slate-300" />PO total {money(total, currency)}</span>
        <span className={`ml-auto font-semibold ${fits ? "text-slate-700" : "text-rose-600"}`}>
          {fits ? `${money(total - after, currency)} remaining` : `Over by ${money(over, currency)} (${((after / total) * 100).toFixed(0)}%)`}
        </span>
      </div>
    </div>
  );
}
