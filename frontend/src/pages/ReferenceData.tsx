import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, money, PurchaseOrder, Vendor } from "../api";
import { Spinner } from "../components/Icons";
import StatusBadge from "../components/StatusBadge";

function Progress({ consumed, total }: { consumed: number; total: number }) {
  const ratio = total ? consumed / total : 0;
  const color = ratio > 1.0001 ? "bg-rose-500" : ratio >= 0.9999 ? "bg-emerald-500" : "bg-indigo-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-40 overflow-hidden rounded-full bg-slate-100">
        <div className={`h-full ${color}`} style={{ width: `${Math.min(100, ratio * 100)}%` }} />
      </div>
      <span className="w-12 text-right text-xs tabular-nums text-slate-500">{(ratio * 100).toFixed(0)}%</span>
    </div>
  );
}

function POCard({ po }: { po: PurchaseOrder }) {
  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
        <div className="flex items-center gap-3">
          <span className="font-mono text-sm font-semibold">{po.po_number}</span>
          <span className={`rounded px-1.5 py-px text-[10px] font-semibold uppercase ${po.status === "open" ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>{po.status}</span>
          <span className="text-sm text-slate-600">{po.vendor_name}</span>
          <span className="text-xs text-slate-400">issued {po.issue_date}</span>
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-x-5 gap-y-1 text-sm">
          <span>Total <b className="tabular-nums">{money(po.total_amount, po.currency)}</b></span>
          <span>Consumed <b className="tabular-nums">{money(po.consumed, po.currency)}</b></span>
          <span>Remaining <b className={`tabular-nums ${Number(po.remaining) < 0 ? "text-rose-600" : ""}`}>{money(po.remaining, po.currency)}</b></span>
          <Progress consumed={Number(po.consumed)} total={Number(po.total_amount)} />
        </div>
      </div>
      <div className="grid grid-cols-[minmax(0,3fr)_minmax(0,2fr)] divide-x divide-slate-100">
        <div className="min-w-0 overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr>
              <th className="th">#</th>
              <th className="th">SKU</th>
              <th className="th">Description</th>
              <th className="th text-right">Qty</th>
              <th className="th text-right">Unit</th>
              <th className="th text-right">Line total</th>
              <th className="th text-right">Received</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {po.lines.map((l) => (
              <tr key={l.line_no}>
                <td className="td text-slate-400">{l.line_no}</td>
                <td className="td font-mono text-xs">{l.sku}</td>
                <td className="td">{l.description}</td>
                <td className="td text-right tabular-nums">{Number(l.quantity).toLocaleString()} <span className="text-xs text-slate-400">{l.uom}</span></td>
                <td className="td text-right tabular-nums">{money(l.unit_price, po.currency)}</td>
                <td className="td text-right tabular-nums">{money(l.line_total, po.currency)}</td>
                <td className="td text-right tabular-nums text-slate-500">{l.received_qty ? Number(l.received_qty).toLocaleString() : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
        <div className="min-w-0 px-4 py-2">
          <div className="mb-1 text-xs font-medium text-slate-500">Linked invoices</div>
          {po.runs.length === 0 ? (
            <div className="py-2 text-sm text-slate-400">None yet.</div>
          ) : (
            <ul className="divide-y divide-slate-100">
              {po.runs.map((r) => (
                <li key={r.run_id}>
                  <Link to={`/runs/${r.run_id}`} className="flex items-center justify-between gap-2 py-1.5 text-sm hover:text-indigo-700">
                    <span className="truncate">
                      <span className="font-mono text-xs">{r.invoice_number ?? "no #"}</span>{" "}
                      <span className="text-xs text-slate-400">{r.file_name}</span>
                    </span>
                    <span className="flex shrink-0 items-center gap-2">
                      <span className="max-w-[9rem] truncate text-xs tabular-nums text-slate-600" title={money(r.invoice_total, po.currency)}>
                        {r.consumed_amount ? `−${money(r.consumed_amount, po.currency)}` : money(r.invoice_total, po.currency)}
                      </span>
                      <StatusBadge decision={r.decision} status={r.status} overridden={r.decision_overridden} />
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

export default function ReferenceData() {
  const [tab, setTab] = useState<"vendors" | "pos">("pos");
  const [vendors, setVendors] = useState<Vendor[] | null>(null);
  const [pos, setPos] = useState<PurchaseOrder[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.vendors(), api.pos()])
      .then(([v, p]) => {
        setVendors(v);
        setPos(p);
      })
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <div className="mx-auto max-w-[1280px] space-y-5 px-8 py-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Reference data</h1>
        <p className="text-sm text-slate-500">The procurement system the agent matches against: vendor master, purchase orders and the PO ledger.</p>
      </header>
      <div className="flex gap-1 border-b border-slate-200">
        {(["pos", "vendors"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium ${tab === t ? "border-indigo-600 text-indigo-700" : "border-transparent text-slate-500 hover:text-slate-800"}`}
          >
            {t === "pos" ? `Purchase orders${pos ? ` (${pos.length})` : ""}` : `Vendors${vendors ? ` (${vendors.length})` : ""}`}
          </button>
        ))}
      </div>
      {error && <div className="text-sm text-rose-600">{error}</div>}
      {!vendors || !pos ? (
        <div className="flex items-center gap-2 text-sm text-slate-500"><Spinner /> Loading…</div>
      ) : tab === "pos" ? (
        <div className="space-y-4">{pos.map((p) => <POCard key={p.po_number} po={p} />)}</div>
      ) : (
        <div className="card overflow-hidden">
          <table className="min-w-full">
            <thead className="border-b border-slate-200 bg-slate-50/60">
              <tr>
                <th className="th">ID</th>
                <th className="th">Name</th>
                <th className="th">Aliases</th>
                <th className="th">Tax ID</th>
                <th className="th">Bank account</th>
                <th className="th">Routing</th>
                <th className="th">Terms</th>
                <th className="th">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {vendors.map((v) => (
                <tr key={v.vendor_id}>
                  <td className="td font-mono text-xs">{v.vendor_id}</td>
                  <td className="td font-medium text-slate-900">{v.name}</td>
                  <td className="td text-xs text-slate-500">{v.aliases.join(", ")}</td>
                  <td className="td font-mono text-xs">{v.tax_id}</td>
                  <td className="td font-mono text-xs">•••• {v.bank_account_last4}</td>
                  <td className="td font-mono text-xs">{v.bank_routing}</td>
                  <td className="td">Net {v.payment_terms_days}</td>
                  <td className="td">
                    <span className={`rounded px-1.5 py-px text-[11px] font-semibold ${v.status === "active" ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700"}`}>{v.status}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
