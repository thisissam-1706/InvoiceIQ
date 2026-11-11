import { Decision, RunStatus } from "../api";
import { MailIcon, Spinner } from "./Icons";

const DECISION_STYLE: Record<Decision, string> = {
  APPROVE: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  HOLD: "bg-amber-50 text-amber-800 ring-amber-600/25",
  REJECT: "bg-rose-50 text-rose-700 ring-rose-600/20",
};

const DECISION_TEXT: Record<Decision, string> = { APPROVE: "APPROVED", HOLD: "ON HOLD", REJECT: "REJECTED" };

interface Props {
  decision: Decision | null;
  status: RunStatus;
  overridden?: boolean;
  size?: "sm" | "lg";
}

export default function StatusBadge({ decision, status, overridden = false, size = "sm" }: Props) {
  const sizing = size === "lg" ? "px-3 py-1 text-sm" : "px-2 py-0.5 text-[11px]";
  const common = `inline-flex items-center gap-1 whitespace-nowrap rounded-md font-semibold tracking-wide ring-1 ring-inset ${sizing}`;

  if (status === "failed") {
    return <span className={`${common} bg-slate-100 text-slate-600 ring-2 ring-rose-400`}>FAILED</span>;
  }
  if (status === "queued" || status === "running" || !decision) {
    return (
      <span className={`${common} bg-indigo-50 text-indigo-700 ring-indigo-600/20`}>
        <Spinner className="h-3 w-3" />
        {status === "queued" ? "QUEUED" : "PROCESSING"}
      </span>
    );
  }
  return (
    <span className={`${common} ${DECISION_STYLE[decision]}`}>
      {DECISION_TEXT[decision]}
      {overridden && <span className="font-medium opacity-80">(override)</span>}
    </span>
  );
}

export function SourceBadge({ source }: { source: string }) {
  if (source !== "inbox") return null;
  return (
    <span className="inline-flex items-center gap-1 rounded-md bg-sky-50 px-1.5 py-0.5 text-[11px] font-medium text-sky-700 ring-1 ring-inset ring-sky-600/20">
      <MailIcon className="h-3 w-3" /> Email inbox
    </span>
  );
}
