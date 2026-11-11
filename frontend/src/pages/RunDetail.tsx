import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, Budget, money, RunDetail as Detail, STAGE_LABELS, STAGES } from "../api";
import DecisionCard from "../components/DecisionCard";
import FieldTable from "../components/FieldTable";
import { Spinner, XIcon } from "../components/Icons";
import LineMatchTable, { BudgetBar } from "../components/LineMatchTable";
import PdfPreview from "../components/PdfPreview";
import RuleChecklist from "../components/RuleChecklist";
import StageTimeline from "../components/StageTimeline";
import StatusBadge, { SourceBadge } from "../components/StatusBadge";
import { useRunStream } from "../hooks/useRunStream";

function Section({ title, children, right }: { title: string; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <section className="card overflow-hidden">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2.5">
        <h2 className="card-title">{title}</h2>
        {right}
      </div>
      {children}
    </section>
  );
}

function hasBudget(b: Budget | Record<string, never> | undefined): b is Budget {
  return !!b && "po_total" in b;
}

function MatchingPanel({ detail }: { detail: Detail }) {
  const m = detail.matching;
  if (!m) return <div className="px-4 py-6 text-sm text-slate-400">Matching results appear after the vendor and PO stages.</div>;
  const currency = detail.run.currency;
  const tolerance = Number(detail.rules?.config_snapshot?.tolerance?.unit_price_pct ?? 0.02);
  const vm = m.vendor_match;
  const candidates = m.po_match.candidates ?? [];

  return (
    <div className="divide-y divide-slate-100">
      <div className="grid grid-cols-2 gap-4 px-4 py-3">
        <div>
          <div className="text-xs font-medium text-slate-500">Vendor</div>
          {m.vendor ? (
            <>
              <div className="mt-0.5 text-sm font-semibold text-slate-900">
                {m.vendor.name} <span className="font-normal text-slate-400">{m.vendor.vendor_id}</span>
              </div>
              <div className="text-xs text-slate-600">
                {vm.method === "tax_id" ? "Matched on tax ID (exact)" : `Name similarity ${Math.round(vm.score)}/100`} · status{" "}
                <span className={m.vendor.status === "active" ? "text-emerald-700" : "font-semibold text-rose-700"}>{m.vendor.status}</span> · terms Net{" "}
                {m.vendor.payment_terms_days}
              </div>
            </>
          ) : (
            <div className="mt-0.5 text-sm text-rose-700">
              Not in vendor master{vm.candidate ? ` (closest: ${vm.candidate}, ${Math.round(vm.score)}/100)` : ""}
            </div>
          )}
        </div>
        <div>
          <div className="text-xs font-medium text-slate-500">Purchase order</div>
          {m.po ? (
            <>
              <div className="mt-0.5 flex items-center gap-2 text-sm font-semibold text-slate-900">
                {m.po.po_number}
                <span className={`rounded px-1.5 py-px text-[10px] font-semibold uppercase ${m.po_match.method === "inferred" ? "bg-amber-100 text-amber-800" : "bg-slate-100 text-slate-600"}`}>
                  {m.po_match.method}
                  {m.po_match.score !== undefined && ` · ${m.po_match.score.toFixed(2)}`}
                </span>
                {m.po.is_blanket && <span className="rounded bg-slate-100 px-1.5 py-px text-[10px] font-semibold uppercase text-slate-600">blanket</span>}
              </div>
              <div className="text-xs text-slate-600">
                {m.po_match.method === "explicit" ? `Quoted on invoice as “${m.po_match.reference}”` : `Inferred from ${candidates.length} open PO(s)`} · {m.po.status}
              </div>
            </>
          ) : (
            <div className="mt-0.5 text-sm text-amber-700">No PO selected</div>
          )}
        </div>
      </div>

      {candidates.length > 0 && (
        <div className="px-4 py-3">
          <div className="mb-1.5 text-xs font-medium text-slate-500">PO inference scoring (0.6 × line match + 0.4 × amount fit)</div>
          <table className="w-full text-xs">
            <tbody>
              {candidates.map((c) => (
                <tr key={c.po_number}>
                  <td className="py-0.5 font-mono text-slate-700">{c.po_number}</td>
                  <td className="py-0.5 text-slate-500">lines {c.line_match_score.toFixed(2)}</td>
                  <td className="py-0.5 text-slate-500">amount {c.amount_proximity_score.toFixed(2)}</td>
                  <td className="w-1/3 py-0.5">
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 flex-1 rounded-full bg-slate-100">
                        <div className={`h-full rounded-full ${c.score >= 0.8 ? "bg-indigo-500" : "bg-slate-300"}`} style={{ width: `${c.score * 100}%` }} />
                      </div>
                      <span className="w-8 text-right font-semibold tabular-nums">{c.score.toFixed(2)}</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {m.po && <LineMatchTable lines={m.line_matches} currency={currency} tolerance={tolerance} />}

      {hasBudget(m.budget) && (
        <div className="px-4 py-4">
          <BudgetBar
            label={`PO budget: ${m.po?.po_number} · ${(Number(m.budget.pct_consumed_after) * 100).toFixed(1)}% consumed if paid`}
            total={Number(m.budget.po_total)}
            consumedBefore={Number(m.budget.consumed_before)}
            thisInvoice={Number(m.budget.this_invoice)}
            currency={currency}
          />
        </div>
      )}

      {m.duplicate.run_id && (
        <div className="px-4 py-3 text-sm">
          <span className="font-medium text-rose-700">Duplicate signal:</span>{" "}
          <span className="text-slate-600">{m.duplicate.match?.replace(/_/g, " ")} → </span>
          <Link to={`/runs/${m.duplicate.run_id}`} className="font-medium text-indigo-600 hover:underline">
            open original run {m.duplicate.run_id.slice(0, 8)}
          </Link>
        </div>
      )}
    </div>
  );
}

function NormalisationNotes({ detail }: { detail: Detail }) {
  const inv = detail.validation?.invoice;
  if (!inv) return null;
  const rows: [string, string | null][] = [
    ["Invoice # (normalised)", inv.invoice_number_norm],
    ["Date read as", inv.invoice_date ? `${inv.invoice_date} (“${inv.invoice_date_raw}”, ${inv.date_reading})` : null],
    ["Tax handling", inv.tax_note],
    ["Pre-tax amount vs PO", money(inv.pretax_subtotal, detail.run.currency)],
  ];
  return (
    <div className="space-y-1 border-t border-slate-100 px-4 py-3 text-xs">
      {rows.map(([k, v]) => (
        <div key={k} className="grid grid-cols-[38%_1fr] gap-2">
          <span className="text-slate-500">{k}</span>
          <span className="text-slate-700">{v ?? "—"}</span>
        </div>
      ))}
    </div>
  );
}

export default function RunDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { detail, stages, error, refresh } = useRunStream(id);
  const [rerunning, setRerunning] = useState(false);
  const [rerunError, setRerunError] = useState<string | null>(null);

  if (error && !detail) return <div className="p-8 text-sm text-rose-600">Could not load run: {error}</div>;
  if (!detail || !id) {
    return (
      <div className="flex items-center gap-2 p-8 text-sm text-slate-500">
        <Spinner /> Loading run…
      </div>
    );
  }

  const { run } = detail;
  const active = run.status === "queued" || run.status === "running";
  // Between stages (during the demo delay) nothing is "running"; show the next stage instead of "starting".
  const running = STAGES.find((s) => stages[s]?.state === "running") ?? (Object.keys(stages).length ? STAGES.find((s) => !stages[s]) : undefined);
  const minConfidence = detail.rules?.config_snapshot?.extraction?.min_confidence ?? 0.7;
  const canRerun = !active && run.decision !== "APPROVE" && !run.superseded_by;

  const rerun = async () => {
    setRerunning(true);
    setRerunError(null);
    try {
      const created = await api.rerun(run.id);
      navigate(`/runs/${created.run_id}`);
    } catch (e) {
      setRerunError(e instanceof Error ? e.message : String(e));
    } finally {
      setRerunning(false);
    }
  };

  return (
    <div className="mx-auto max-w-[1440px] px-8 py-6">
      <header className="mb-5 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <Link to="/" className="text-xs font-medium text-slate-500 hover:text-slate-800">← Dashboard</Link>
          <h1 className="mt-1 truncate text-xl font-semibold tracking-tight">{run.file_name}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <span className="font-mono">run {run.id.slice(0, 8)}</span>
            <span>·</span>
            <span>{new Date(run.created_at).toLocaleString()}</span>
            <SourceBadge source={run.source} />
            {detail.llm_provider && <span>· {detail.llm_provider}/{detail.llm_model}</span>}
            {run.rerun_of && <Link to={`/runs/${run.rerun_of}`} className="text-indigo-600 hover:underline">· re-run of {run.rerun_of.slice(0, 8)}</Link>}
            {run.superseded_by && <Link to={`/runs/${run.superseded_by}`} className="font-medium text-indigo-600 hover:underline">· superseded by {run.superseded_by.slice(0, 8)}</Link>}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          {canRerun && (
            <button className="btn-secondary" onClick={rerun} disabled={rerunning} title="Process the same file again with the current settings">
              {rerunning && <Spinner className="h-3.5 w-3.5" />} Re-run
            </button>
          )}
          {active ? (
            <div className="flex items-center gap-2 rounded-lg bg-indigo-50 px-3 py-1.5 text-sm font-medium text-indigo-700 ring-1 ring-inset ring-indigo-600/20">
              <Spinner className="h-4 w-4" />
              {run.status === "queued" && !running ? "Queued…" : `Processing: ${running ? STAGE_LABELS[running] : "starting"}`}
            </div>
          ) : (
            <StatusBadge decision={run.decision} status={run.status} overridden={run.decision_overridden} size="lg" />
          )}
        </div>
      </header>
      {rerunError && <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-700">{rerunError}</div>}
      {detail.extraction?.meta.fallback_from && (
        <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-800">
          Offline fallback: {detail.extraction.meta.fallback_from} was unavailable ({detail.extraction.meta.fallback_reason}), so the basic offline extractor read this invoice. It is held for review: check the fields against the PDF.
        </div>
      )}
      {detail.provider_note && (
        <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-800">{detail.provider_note}</div>
      )}

      <div className="grid grid-cols-[minmax(0,3fr)_minmax(0,2fr)] items-start gap-5">
        <div className="space-y-5">
          {run.status === "failed" && (
            <div className="flex gap-3 rounded-xl border-2 border-rose-300 bg-white px-5 py-4">
              <XIcon className="mt-0.5 h-5 w-5 shrink-0 text-rose-600" />
              <div>
                <div className="font-semibold text-slate-900">Processing failed: system error, not a business decision</div>
                <div className="mt-1 text-sm text-slate-700">{run.error_message}</div>
                <div className="mt-1 text-xs text-slate-500">Nothing was approved or rejected. Fix the cause and use Re-run.</div>
              </div>
            </div>
          )}

          {run.status === "completed" && <DecisionCard detail={detail} onChanged={refresh} />}

          <Section title="Pipeline" right={<span className="text-xs text-slate-400">{active ? "live" : `finished in ${((run.duration_ms ?? 0) / 1000).toFixed(1)} s`}</span>}>
            <div className="px-4 pt-4">
              <StageTimeline stages={stages} />
            </div>
          </Section>

          <Section title="Checks">
            <RuleChecklist checks={detail.checks} />
          </Section>

          <Section title="Matching">
            <MatchingPanel detail={detail} />
          </Section>
        </div>

        <div className="sticky top-6 space-y-5">
          <Section
            title="Original document"
            right={
              <a href={api.fileUrl(run.id)} target="_blank" rel="noreferrer" className="text-xs font-medium text-indigo-600 hover:underline">
                Open PDF
              </a>
            }
          >
            <PdfPreview url={api.fileUrl(run.id)} fileName={run.file_name} />
          </Section>

          <Section title="Extracted fields">
            <FieldTable extraction={detail.extraction} minConfidence={minConfidence} />
            <NormalisationNotes detail={detail} />
          </Section>

          <Section title="Audit trail">
            {detail.audit.length === 0 ? (
              <div className="px-4 py-4 text-sm text-slate-400">No events yet.</div>
            ) : (
              <ul className="divide-y divide-slate-100">
                {detail.audit.map((a, i) => (
                  <li key={i} className="flex gap-3 px-4 py-2 text-xs">
                    <span className="w-16 shrink-0 tabular-nums text-slate-400">{new Date(a.at).toLocaleTimeString()}</span>
                    <span className={`w-16 shrink-0 font-medium ${a.actor === "reviewer" ? "text-indigo-700" : "text-slate-500"}`}>{a.actor}</span>
                    <div className="min-w-0">
                      <div className="font-medium text-slate-700">{a.action.replace(/_/g, " ")}</div>
                      {a.note && <div className="text-slate-500">{a.note}</div>}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Section>
        </div>
      </div>
    </div>
  );
}
