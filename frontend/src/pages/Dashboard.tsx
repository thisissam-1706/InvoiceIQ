import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, clockTime, codeTitle, compactMoney, Decision, duration, money, RunFilters, RunList, Stats } from "../api";
import { Spinner } from "../components/Icons";
import StatTile from "../components/StatTile";
import StatusBadge, { SourceBadge } from "../components/StatusBadge";

type Chip = "ALL" | Decision | "FAILED";
const CHIPS: { key: Chip; label: string }[] = [
  { key: "ALL", label: "All" },
  { key: "APPROVE", label: "Approve" },
  { key: "HOLD", label: "Hold" },
  { key: "REJECT", label: "Reject" },
  { key: "FAILED", label: "Failed" },
];

const COLORS = { APPROVE: "#10b981", HOLD: "#f59e0b", REJECT: "#f43f5e", FAILED: "#94a3b8" };

function filtersFor(chip: Chip, q: string): RunFilters {
  const f: RunFilters = { q: q || undefined, limit: 100 };
  if (chip === "FAILED") f.status = "failed";
  else if (chip !== "ALL") f.decision = chip;
  return f;
}

const TICK_LINE_CHARS = 24;

/** Y-axis label for the findings chart: wraps onto two lines at a word boundary (titles are <= 35 chars),
 * with the full text in a native tooltip as a safety net. */
function FindingTick({ x, y, payload }: { x?: number; y?: number; payload?: { value: string } }) {
  const text = payload?.value ?? "";
  const lines: string[] = [];
  let line = "";
  for (const word of text.split(" ")) {
    if (line && `${line} ${word}`.length > TICK_LINE_CHARS) {
      lines.push(line);
      line = word;
    } else {
      line = line ? `${line} ${word}` : word;
    }
  }
  if (line) lines.push(line);
  const shown = lines.slice(0, 2);
  if (lines.length > 2) shown[1] = `${shown[1]}…`;
  return (
    <text x={x} y={y} textAnchor="end" fontSize={11} fill="#475569">
      <title>{text}</title>
      {shown.map((l, i) => (
        <tspan key={i} x={x} dy={i === 0 ? (shown.length > 1 ? -2 : 4) : 13}>
          {l}
        </tspan>
      ))}
    </text>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [stats, setStats] = useState<Stats | null>(null);
  const [runs, setRuns] = useState<RunList | null>(null);
  const [chip, setChip] = useState<Chip>("ALL");
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, r] = await Promise.all([api.stats(), api.runs(filtersFor(chip, q))]);
      setStats(s);
      setRuns(r);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [chip, q]);

  useEffect(() => {
    load();
  }, [load]);

  const busy = (stats?.in_progress ?? 0) > 0 || !!runs?.items.some((r) => r.status === "queued" || r.status === "running");
  useEffect(() => {
    if (!busy) return;
    const t = window.setInterval(load, 3000);
    return () => window.clearInterval(t);
  }, [busy, load]);

  const trend = useMemo(() => {
    const counts = { APPROVE: 0, HOLD: 0, REJECT: 0, FAILED: 0 };
    return (stats?.recent ?? [])
      .filter((r) => r.status === "completed" || r.status === "failed")
      .map((r, i) => {
        const key = r.status === "failed" ? "FAILED" : (r.decision as Decision);
        counts[key] += 1;
        return { run: `#${i + 1}`, file: r.file_name, ...counts };
      });
  }, [stats]);

  if (error && !stats) {
    return <div className="p-8 text-sm text-rose-600">Could not load the dashboard: {error}</div>;
  }
  if (!stats || !runs) {
    return (
      <div className="flex items-center gap-2 p-8 text-sm text-slate-500">
        <Spinner /> Loading dashboard…
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[1280px] space-y-5 px-8 py-6">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Dashboard</h1>
          <p className="text-sm text-slate-500">Every invoice run, its decision and why.</p>
        </div>
        <div className="flex items-center gap-3">
          {busy && (
            <span className="flex items-center gap-1.5 text-xs text-indigo-600">
              <Spinner className="h-3.5 w-3.5" /> {stats.in_progress} processing
            </span>
          )}
          <Link to="/new" className="btn-primary">New run</Link>
        </div>
      </header>

      <section className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatTile label="Invoices processed" value={stats.processed} hint={stats.failed ? `${stats.failed} failed` : `${stats.total_runs} runs total`} />
        <StatTile label="Auto-approved" value={`${Math.round(stats.auto_approve_rate * 100)}%`} hint={`${stats.auto_approved} of ${stats.processed}`} tone="emerald" />
        <StatTile label="On hold" value={stats.on_hold} hint="awaiting a reviewer" tone="amber" />
        <StatTile label="Rejected" value={stats.rejected} hint={stats.overridden ? `${stats.overridden} overridden` : "blocked by policy"} tone="rose" />
        <StatTile label="Total value processed" value={compactMoney(stats.total_value)} fullValue={money(stats.total_value)} hint="invoice totals" />
        <StatTile label="Avg processing time" value={duration(stats.avg_duration_ms)} hint="per invoice, end to end" />
      </section>

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="card min-w-0 p-4 lg:col-span-2">
          <div className="card-title">Decisions over the last {trend.length || 0} runs (cumulative)</div>
          {trend.length ? (
            <div className="mt-2 h-48">
              <ResponsiveContainer>
                <BarChart data={trend} margin={{ top: 8, right: 8, bottom: 0, left: -20 }}>
                  <CartesianGrid vertical={false} stroke="#e2e8f0" />
                  <XAxis dataKey="run" tick={{ fontSize: 11, fill: "#64748b" }} tickLine={false} axisLine={false} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "#64748b" }} tickLine={false} axisLine={false} />
                  <Tooltip
                    cursor={{ fill: "#f1f5f9" }}
                    contentStyle={{ fontSize: 12, borderRadius: 8, borderColor: "#e2e8f0" }}
                    labelFormatter={(label, payload) => `${label} · ${payload?.[0]?.payload?.file ?? ""}`}
                  />
                  <Legend iconType="square" iconSize={8} wrapperStyle={{ fontSize: 11 }} />
                  {(["APPROVE", "HOLD", "REJECT", "FAILED"] as const).map((k) => (
                    <Bar key={k} dataKey={k} stackId="d" fill={COLORS[k]} maxBarSize={28} />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="flex h-48 items-center justify-center text-sm text-slate-400">No runs yet. Start one from New Run.</div>
          )}
        </div>
        <div className="card min-w-0 p-4">
          <div className="card-title">Top findings</div>
          {stats.top_findings.length ? (
            <div className="mt-2 h-48">
              <ResponsiveContainer>
                <BarChart data={stats.top_findings} layout="vertical" margin={{ top: 4, right: 16, bottom: 0, left: 0 }}>
                  <XAxis type="number" allowDecimals={false} hide />
                  <YAxis type="category" dataKey="title" width={190} tick={<FindingTick />} tickLine={false} axisLine={false} interval={0} />
                  <Tooltip
                    cursor={{ fill: "#f1f5f9" }}
                    contentStyle={{ fontSize: 12, borderRadius: 8 }}
                    labelStyle={{ fontWeight: 600 }}
                    formatter={(v) => [v, "Invoices"]}
                  />
                  <Bar dataKey="count" fill="#6366f1" radius={[0, 4, 4, 0]} maxBarSize={18} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="flex h-48 items-center justify-center text-sm text-slate-400">No findings yet.</div>
          )}
        </div>
      </section>

      <section className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="card overflow-hidden">
          <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
            <div className="flex gap-1">
              {CHIPS.map((c) => (
                <button
                  key={c.key}
                  onClick={() => setChip(c.key)}
                  className={`rounded-full px-3 py-1 text-xs font-medium ${chip === c.key ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}
                >
                  {c.label}
                </button>
              ))}
            </div>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search file, vendor, invoice #, PO…" className="input w-64" />
          </div>
          {runs.items.length === 0 ? (
            <div className="px-4 py-12 text-center text-sm text-slate-400">
              {stats.total_runs ? "No runs match this filter." : "No invoices processed yet."}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full">
                <thead className="border-b border-slate-200 bg-slate-50/60">
                  <tr>
                    <th className="th">Time · took</th>
                    <th className="th">File</th>
                    <th className="th">Vendor · Invoice #</th>
                    <th className="th">PO</th>
                    <th className="th text-right">Amount</th>
                    <th className="th">Decision</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {runs.items.map((r) => (
                    <tr key={r.id} onClick={() => navigate(`/runs/${r.id}`)} className={`cursor-pointer hover:bg-slate-50 ${r.superseded_by ? "opacity-50" : ""}`}>
                      <td className="td whitespace-nowrap tabular-nums text-slate-500">
                        <div>{clockTime(r.created_at)}</div>
                        <div className="text-[11px] text-slate-400">{duration(r.duration_ms)}</div>
                      </td>
                      <td className="td max-w-[200px]">
                        <div className="truncate font-medium text-slate-800" title={r.file_name}>{r.file_name}</div>
                        <div className="mt-0.5 flex gap-1">
                          <SourceBadge source={r.source} />
                          {r.superseded_by && <span className="text-[11px] text-slate-400">superseded</span>}
                        </div>
                      </td>
                      <td className="td max-w-[190px]">
                        <div className="truncate" title={r.vendor_name ?? undefined}>{r.vendor_name ?? "—"}</div>
                        <div className="truncate font-mono text-[11px] text-slate-500">{r.invoice_number ?? "no invoice #"}</div>
                      </td>
                      <td className="td whitespace-nowrap font-mono text-xs">{r.po_number ?? "—"}</td>
                      <td className="td max-w-[150px] text-right tabular-nums">
                        <div className="truncate" title={money(r.invoice_total, r.currency)}>{money(r.invoice_total, r.currency)}</div>
                      </td>
                      <td className="td">
                        <StatusBadge decision={r.decision} status={r.status} overridden={r.decision_overridden} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <aside className="card overflow-hidden">
          <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
            <div className="card-title">Needs attention</div>
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800">{stats.needs_attention.length}</span>
          </div>
          {stats.needs_attention.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-slate-400">Nothing on hold.</div>
          ) : (
            <ul className="divide-y divide-slate-100">
              {stats.needs_attention.map((h) => (
                <li key={h.id}>
                  <Link to={`/runs/${h.id}`} className="block px-4 py-3 hover:bg-slate-50">
                    <div className="flex items-center justify-between gap-2">
                      <span className="min-w-0 truncate text-sm font-medium text-slate-800" title={h.vendor_name ?? h.file_name}>{h.vendor_name ?? h.file_name}</span>
                      <span className="max-w-[45%] shrink-0 truncate text-sm tabular-nums text-slate-600" title={money(h.invoice_total, h.currency)}>{money(h.invoice_total, h.currency)}</span>
                    </div>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {h.findings.map((f) => (
                        <span key={f.code} title={f.description || f.code} className="rounded bg-amber-50 px-1.5 py-px text-[11px] text-amber-800 ring-1 ring-inset ring-amber-600/20">{codeTitle(f.code, f.title)}</span>
                      ))}
                    </div>
                    {h.primary_action && <div className="mt-1 line-clamp-2 text-xs text-slate-500">{h.primary_action}</div>}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </aside>
      </section>
    </div>
  );
}
