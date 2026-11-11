import { FormEvent, useState } from "react";
import { api } from "../api";
import { Spinner } from "./Icons";

interface Props {
  runId: string;
  decision: "APPROVE" | "REJECT";
  onClose: () => void;
  onDone: () => void;
}

export default function OverrideDialog({ runId, decision, onClose, onDone }: Props) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const approve = decision === "APPROVE";

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!note.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.override(runId, decision, note.trim());
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={onClose}>
      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} className="w-full max-w-md rounded-xl bg-white p-5 shadow-xl">
        <h2 className="text-base font-semibold text-slate-900">{approve ? "Approve this invoice?" : "Reject this invoice?"}</h2>
        <p className="mt-1 text-sm text-slate-600">
          {approve
            ? "This overrides the hold. The pre-tax amount is consumed from the PO and the override is written to the audit trail."
            : "The invoice will be marked rejected. A corrected resubmission will still be accepted later."}
        </p>
        <label className="label mt-4" htmlFor="override-note">
          Reviewer note (required)
        </label>
        <textarea
          id="override-note"
          autoFocus
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={4}
          className="input resize-none"
          placeholder={approve ? "e.g. Called vendor on the number in the master file; bank change confirmed." : "e.g. Vendor confirmed this was sent in error."}
        />
        {error && <div className="mt-2 text-sm text-rose-600">{error}</div>}
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" disabled={!note.trim() || busy} className={approve ? "btn bg-emerald-600 text-white hover:bg-emerald-700" : "btn-danger"}>
            {busy && <Spinner className="h-3.5 w-3.5" />}
            {approve ? "Approve with override" : "Reject"}
          </button>
        </div>
      </form>
    </div>
  );
}
