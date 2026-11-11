import { ReactNode } from "react";

interface Props {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "default" | "emerald" | "amber" | "rose";
  /** Full, untruncated text shown as a tooltip when the displayed value is shortened. Defaults to the value if it is plain text. */
  fullValue?: string;
}

const TONE = {
  default: "text-slate-900",
  emerald: "text-emerald-700",
  amber: "text-amber-700",
  rose: "text-rose-700",
};

/** Long values get a smaller font so they fit; truncation with a tooltip is the last resort. */
function sizeFor(text: string): string {
  if (text.length > 14) return "text-base";
  if (text.length > 9) return "text-xl";
  return "text-2xl";
}

export default function StatTile({ label, value, hint, tone = "default", fullValue }: Props) {
  const text = typeof value === "string" || typeof value === "number" ? String(value) : "";
  const tip = fullValue ?? (text || undefined);
  const hintText = typeof hint === "string" ? hint : undefined;
  return (
    <div className="card min-w-0 overflow-hidden px-4 py-3.5">
      <div className="truncate text-xs font-medium text-slate-500" title={label}>{label}</div>
      <div className={`mt-1 truncate font-semibold tabular-nums tracking-tight ${sizeFor(text)} ${TONE[tone]}`} title={tip}>{value}</div>
      {hint && <div className="mt-0.5 truncate text-xs text-slate-500" title={hintText}>{hint}</div>}
    </div>
  );
}
