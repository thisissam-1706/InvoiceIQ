import { useState } from "react";
import { AuditOut, RunDetail } from "../api";
import { CheckIcon } from "./Icons";
import OverrideDialog from "./OverrideDialog";
import StatusBadge from "./StatusBadge";

const TONE = {
  APPROVE: "border-emerald-200 bg-emerald-50/40",
  HOLD: "border-amber-200 bg-amber-50/40",
  REJECT: "border-rose-200 bg-rose-50/40",
};

export default function DecisionCard({ detail, onChanged }: { detail: RunDetail; onChanged: () => void }) {
  const { run, actions, explanation } = detail;
  const [dialog, setDialog] = useState<"APPROVE" | "REJECT" | null>(null);
  const [copied, setCopied] = useState(false);
  if (!run.decision) return null;

  const override: AuditOut | undefined = [...detail.audit].reverse().find((a) => a.action.startsWith("override_"));
  const email = actions?.vendor_email;
  const canOverride = run.decision === "HOLD" && !run.decision_overridden && !run.superseded_by;
  const tone = TONE[run.decision];

  const copy = async () => {
    if (!email) return;
    await navigator.clipboard.writeText(`Subject: ${email.subject}\n\n${email.body}`);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className={`rounded-xl border ${tone}`}>
      <div className="flex items-center justify-between gap-3 border-b border-inherit px-5 py-3">
        <div className="flex items-center gap-2.5">
          <StatusBadge decision={run.decision} status={run.status} overridden={run.decision_overridden} size="lg" />
          {run.decision_overridden && run.original_decision && (
            <span className="text-xs text-slate-500">system decision was {run.original_decision}</span>
          )}
        </div>
        {canOverride && (
          <div className="flex gap-2">
            <button className="btn bg-emerald-600 text-white hover:bg-emerald-700" onClick={() => setDialog("APPROVE")}>
              Approve…
            </button>
            <button className="btn-secondary text-rose-700" onClick={() => setDialog("REJECT")}>
              Reject…
            </button>
          </div>
        )}
      </div>
      <div className="space-y-4 px-5 py-4">
        {explanation && <p className="text-[15px] leading-relaxed text-slate-800">{explanation}</p>}

        {actions && actions.actions.length > 0 && (
          <div>
            <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">Suggested next action</div>
            <ol className="space-y-1.5">
              {actions.actions.map((a, i) => (
                <li key={a.code} className="flex gap-2 text-sm text-slate-800">
                  <span className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold ${a.severity === "block" ? "bg-rose-100 text-rose-700" : "bg-amber-100 text-amber-800"}`}>
                    {i + 1}
                  </span>
                  {a.text}
                </li>
              ))}
            </ol>
          </div>
        )}

        {run.decision === "APPROVE" && actions?.payment_due_date && !run.decision_overridden && (
          <div className="flex items-center gap-2 text-sm text-emerald-800">
            <CheckIcon className="h-4 w-4" /> Scheduled for payment by {new Date(actions.payment_due_date + "T00:00:00").toLocaleDateString(undefined, { dateStyle: "medium" })}
          </div>
        )}

        {email && (
          <div className="rounded-lg border border-slate-200 bg-white">
            <div className="flex items-center justify-between border-b border-slate-100 px-3 py-2">
              <div className="text-xs text-slate-500">
                <span className="font-semibold text-slate-700">Draft email to vendor</span> · never sent automatically
                {email.polished_by_llm && " · polished by AI"}
              </div>
              <button className="btn-secondary px-2 py-1 text-xs" onClick={copy}>
                {copied ? "Copied" : "Copy"}
              </button>
            </div>
            <div className="px-3 py-2 text-xs text-slate-500">
              To: {email.to}
              <br />
              Subject: <span className="text-slate-700">{email.subject}</span>
            </div>
            <pre className="whitespace-pre-wrap px-3 pb-3 font-sans text-[13px] leading-relaxed text-slate-700">{email.body}</pre>
          </div>
        )}

        {override && (
          <div className="rounded-lg border border-indigo-200 bg-indigo-50/60 px-3 py-2 text-sm">
            <div className="font-medium text-indigo-900">
              Reviewer override → {override.action === "override_approve" ? "APPROVED" : "REJECTED"} ·{" "}
              {new Date(override.at).toLocaleString()}
            </div>
            <div className="mt-0.5 text-indigo-800">“{override.note}”</div>
          </div>
        )}
      </div>
      {dialog && (
        <OverrideDialog
          runId={run.id}
          decision={dialog}
          onClose={() => setDialog(null)}
          onDone={() => {
            setDialog(null);
            onChanged();
          }}
        />
      )}
    </div>
  );
}
