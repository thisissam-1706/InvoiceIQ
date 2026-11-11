import { useState } from "react";
import { duration, JsonObject, JsonValue, Stage, STAGE_LABELS, STAGES } from "../api";
import { StageView } from "../hooks/useRunStream";
import { CheckIcon, ChevronIcon, Spinner, XIcon } from "./Icons";

// Bulky payloads that have their own panels elsewhere on the page.
const HIDDEN_KEYS = new Set(["extraction", "config_snapshot", "vendor", "line_matches"]);
const PREFORMATTED_KEYS = new Set(["text_preview", "explanation"]);

function humanKey(key: string): string {
  return key.replace(/_/g, " ").replace(/\bpct\b/, "%").replace(/^./, (c) => c.toUpperCase());
}

function Scalar({ value }: { value: JsonValue }) {
  if (value === null) return <span className="text-slate-400">—</span>;
  if (typeof value === "boolean") return <span>{value ? "yes" : "no"}</span>;
  if (typeof value === "object") return <span className="font-mono text-[11px] text-slate-600">{JSON.stringify(value)}</span>;
  return <span className="break-all">{String(value)}</span>;
}

function ObjectTable({ rows }: { rows: JsonObject[] }) {
  const cols = Array.from(new Set(rows.flatMap((r) => Object.keys(r)))).filter((c) => c !== "data" && c !== "stage").slice(0, 6);
  return (
    <div className="overflow-x-auto rounded-md border border-slate-200">
      <table className="min-w-full text-xs">
        <thead className="bg-slate-50">
          <tr>{cols.map((c) => <th key={c} className="px-2 py-1 text-left font-medium text-slate-500">{humanKey(c)}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((r, i) => (
            <tr key={i}>{cols.map((c) => <td key={c} className="px-2 py-1 align-top text-slate-700"><Scalar value={r[c] ?? null} /></td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DetailView({ detail }: { detail: JsonObject }) {
  const entries = Object.entries(detail).filter(([k]) => !HIDDEN_KEYS.has(k));
  if (!entries.length) return <div className="text-xs text-slate-400">No details.</div>;
  return (
    <div className="space-y-2">
      {entries.map(([key, value]) => {
        if (PREFORMATTED_KEYS.has(key) && typeof value === "string") {
          return (
            <div key={key}>
              <div className="mb-1 text-[11px] font-medium text-slate-500">{humanKey(key)}</div>
              <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded-md bg-slate-50 p-2 font-mono text-[11px] text-slate-700">{value}</pre>
            </div>
          );
        }
        if (Array.isArray(value) && value.length && value.every((v) => v && typeof v === "object" && !Array.isArray(v))) {
          return (
            <div key={key}>
              <div className="mb-1 text-[11px] font-medium text-slate-500">{humanKey(key)}</div>
              <ObjectTable rows={value as JsonObject[]} />
            </div>
          );
        }
        if (value && typeof value === "object" && !Array.isArray(value)) {
          return (
            <div key={key}>
              <div className="mb-1 text-[11px] font-medium text-slate-500">{humanKey(key)}</div>
              <div className="rounded-md border border-slate-100 bg-slate-50/60 px-2 py-1">
                <DetailView detail={value as JsonObject} />
              </div>
            </div>
          );
        }
        return (
          <div key={key} className="grid grid-cols-[150px_1fr] gap-2 text-xs">
            <div className="text-slate-500">{humanKey(key)}</div>
            <div className="text-slate-800"><Scalar value={value} /></div>
          </div>
        );
      })}
    </div>
  );
}

function StageRow({ stage, view, index, isLast }: { stage: Stage; view: StageView | undefined; index: number; isLast: boolean }) {
  const [open, setOpen] = useState(false);
  const [raw, setRaw] = useState(false);
  const state = view?.state ?? "pending";

  const dot = {
    pending: <div className="h-6 w-6 rounded-full border-2 border-slate-200 bg-white" />,
    running: (
      <div className="flex h-6 w-6 items-center justify-center rounded-full bg-indigo-600 text-white ring-4 ring-indigo-100">
        <Spinner className="h-3.5 w-3.5" />
      </div>
    ),
    completed: (
      <div className="flex h-6 w-6 items-center justify-center rounded-full bg-emerald-500 text-white">
        <CheckIcon className="h-3.5 w-3.5" />
      </div>
    ),
    failed: (
      <div className="flex h-6 w-6 items-center justify-center rounded-full bg-rose-500 text-white">
        <XIcon className="h-3.5 w-3.5" />
      </div>
    ),
  }[state];

  const hasDetail = !!view && (state === "completed" || state === "failed") && Object.keys(view.detail).length > 0;

  return (
    <li className="relative flex gap-3 pb-4">
      {!isLast && <div className={`absolute left-3 top-7 -ml-px h-[calc(100%-1.5rem)] w-0.5 ${state === "completed" ? "bg-emerald-200" : "bg-slate-200"}`} />}
      <div className="relative z-10 shrink-0">{dot}</div>
      <div className="min-w-0 flex-1 pt-0.5">
        <button
          type="button"
          disabled={!hasDetail}
          onClick={() => setOpen((o) => !o)}
          className="group flex w-full items-start justify-between gap-3 text-left"
        >
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-[11px] tabular-nums text-slate-400">{String(index + 1).padStart(2, "0")}</span>
              <span className={`text-sm font-medium ${state === "pending" ? "text-slate-400" : "text-slate-900"}`}>{STAGE_LABELS[stage]}</span>
              {hasDetail && <ChevronIcon className={`h-3.5 w-3.5 text-slate-400 transition-transform ${open ? "rotate-90" : ""}`} />}
            </div>
            <div className={`mt-0.5 text-[13px] ${state === "failed" ? "text-rose-700" : "text-slate-600"}`}>
              {state === "running" ? <span className="text-indigo-600">Running…</span> : view?.summary}
            </div>
          </div>
          {view?.durationMs !== null && view?.durationMs !== undefined && (
            <span className="shrink-0 pt-0.5 text-xs tabular-nums text-slate-400">{duration(view.durationMs)}</span>
          )}
        </button>
        {open && view && (
          <div className="mt-2 rounded-lg border border-slate-200 bg-white p-3">
            <div className="mb-2 flex justify-end">
              <button type="button" onClick={() => setRaw((r) => !r)} className="text-[11px] font-medium text-indigo-600 hover:underline">
                {raw ? "Formatted" : "Raw JSON"}
              </button>
            </div>
            {raw ? (
              <pre className="max-h-80 overflow-auto rounded-md bg-slate-900 p-3 font-mono text-[11px] leading-relaxed text-slate-100">
                {JSON.stringify(view.detail, null, 2)}
              </pre>
            ) : (
              <DetailView detail={view.detail} />
            )}
          </div>
        )}
      </div>
    </li>
  );
}

export default function StageTimeline({ stages }: { stages: Partial<Record<Stage, StageView>> }) {
  return (
    <ol>
      {STAGES.map((stage, i) => (
        <StageRow key={stage} stage={stage} view={stages[stage]} index={i} isLast={i === STAGES.length - 1} />
      ))}
    </ol>
  );
}
