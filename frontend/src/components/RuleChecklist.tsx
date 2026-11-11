import { CheckOut, codeTitle, Severity, STAGE_LABELS } from "../api";
import { AlertIcon, CheckIcon, InfoIcon, StopIcon } from "./Icons";

const STYLE: Record<Severity, { icon: JSX.Element; row: string; tag: string; label: string }> = {
  pass: { icon: <CheckIcon className="h-4 w-4 text-emerald-600" />, row: "", tag: "bg-emerald-50 text-emerald-700", label: "pass" },
  info: { icon: <InfoIcon className="h-4 w-4 text-sky-600" />, row: "", tag: "bg-sky-50 text-sky-700", label: "info" },
  warning: { icon: <AlertIcon className="h-4 w-4 text-yellow-600" />, row: "", tag: "bg-yellow-50 text-yellow-800", label: "warn" },
  review: { icon: <AlertIcon className="h-4 w-4 text-amber-600" />, row: "bg-amber-50/50", tag: "bg-amber-100 text-amber-800", label: "review" },
  block: { icon: <StopIcon className="h-4 w-4 text-rose-600" />, row: "bg-rose-50/50", tag: "bg-rose-100 text-rose-700", label: "block" },
};

const ORDER: Record<Severity, number> = { block: 0, review: 1, warning: 2, info: 3, pass: 4 };

export default function RuleChecklist({ checks }: { checks: CheckOut[] }) {
  if (!checks.length) return <div className="px-4 py-6 text-sm text-slate-400">Checks appear here once validation runs.</div>;
  const sorted = [...checks].sort((a, b) => ORDER[a.severity] - ORDER[b.severity]);
  const counts = checks.reduce<Record<string, number>>((acc, c) => ({ ...acc, [c.severity]: (acc[c.severity] ?? 0) + 1 }), {});

  return (
    <div>
      <div className="flex flex-wrap gap-1.5 border-b border-slate-100 px-4 py-2.5">
        {(["block", "review", "warning", "info", "pass"] as Severity[]).map(
          (s) =>
            counts[s] ? (
              <span key={s} className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${STYLE[s].tag}`}>
                {counts[s]} {STYLE[s].label}
              </span>
            ) : null,
        )}
      </div>
      <ul className="divide-y divide-slate-100">
        {sorted.map((c, i) => (
          <li key={`${c.code}-${i}`} className={`flex gap-3 px-4 py-2.5 ${STYLE[c.severity].row}`}>
            <div className="pt-0.5">{STYLE[c.severity].icon}</div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[13px] font-semibold text-slate-800" title={c.description || undefined}>{codeTitle(c.code, c.title)}</span>
                <span className={`rounded px-1.5 py-px text-[10px] font-semibold uppercase ${STYLE[c.severity].tag}`}>{STYLE[c.severity].label}</span>
                {c.critical && <span className="rounded bg-rose-600 px-1.5 py-px text-[10px] font-semibold uppercase text-white">critical</span>}
                {c.stage && <span className="text-[11px] text-slate-400">{STAGE_LABELS[c.stage]}</span>}
                <span className="font-mono text-[10px] text-slate-400" title="Internal code">{c.code}</span>
              </div>
              <p className="mt-0.5 text-[13px] leading-snug text-slate-700">{c.message}</p>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
