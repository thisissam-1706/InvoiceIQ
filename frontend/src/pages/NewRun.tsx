import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, Decision, Health, Sample } from "../api";
import { MailIcon, ScanIcon, Spinner } from "../components/Icons";
import StatusBadge from "../components/StatusBadge";
import UploadDropzone from "../components/UploadDropzone";

const EXPECTED_STYLE: Record<Decision, string> = {
  APPROVE: "text-emerald-700",
  HOLD: "text-amber-700",
  REJECT: "text-rose-700",
};

export default function NewRun() {
  const navigate = useNavigate();
  const [samples, setSamples] = useState<Sample[] | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [uploading, setUploading] = useState(false);
  const [starting, setStarting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.samples().then(setSamples).catch((e) => setError(String(e)));
    api.health().then(setHealth).catch(() => undefined);
  }, []);

  const upload = async (files: File[]) => {
    setUploading(true);
    setError(null);
    try {
      const created = await api.upload(files);
      navigate(created.length === 1 ? `/runs/${created[0].run_id}` : "/");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setUploading(false);
    }
  };

  const runSample = async (file: string) => {
    setStarting(file);
    setError(null);
    try {
      const created = await api.runSample(file);
      navigate(`/runs/${created.run_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStarting(null);
    }
  };

  return (
    <div className="mx-auto max-w-[1180px] space-y-6 px-8 py-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">New run</h1>
        <p className="text-sm text-slate-500">Upload vendor invoices, or replay one of the prepared demo scenarios.</p>
      </header>

      <UploadDropzone onFiles={upload} busy={uploading} />
      {error && <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-700">{error}</div>}

      <div className="flex items-start gap-3 rounded-xl border border-sky-200 bg-sky-50/60 px-4 py-3 text-sm text-sky-900">
        <MailIcon className="mt-0.5 h-4 w-4 shrink-0" />
        <div>
          <span className="font-medium">Email intake (simulated).</span> PDFs dropped into{" "}
          <code className="rounded bg-white px-1 py-0.5 text-xs">backend/data/inbox/</code> are picked up automatically within a few seconds,
          the same way an AP mailbox would forward attachments. They appear on the dashboard with an “Email inbox” badge.
          {health && <div className="mt-1 break-all text-xs text-sky-700">{health.inbox_dir}</div>}
        </div>
      </div>

      <section>
        <div className="mb-3 flex items-end justify-between">
          <div>
            <h2 className="text-base font-semibold">Demo samples</h2>
            <p className="text-sm text-slate-500">
              Run them in order after a reset: later scenarios depend on earlier ones (03→05 share a PO; 06 duplicates 01).
            </p>
          </div>
          <Link to="/settings" className="text-sm font-medium text-indigo-600 hover:underline">Reset demo data</Link>
        </div>
        {!samples ? (
          <div className="flex items-center gap-2 text-sm text-slate-500"><Spinner /> Loading samples…</div>
        ) : samples.length === 0 ? (
          <div className="card px-4 py-8 text-center text-sm text-slate-500">
            No samples found. Run <code>python backend/scripts/generate_samples.py</code>.
          </div>
        ) : (
          <div className="grid grid-cols-3 gap-3">
            {samples.map((s) => (
              <div key={s.file} className={`card flex flex-col p-4 ${s.headline ? "border-indigo-300 ring-1 ring-indigo-200" : ""}`}>
                <div className="flex items-start justify-between gap-2">
                  <div className="font-mono text-[11px] text-slate-500">{s.file}</div>
                  <div className="flex shrink-0 gap-1">
                    {s.scanned && (
                      <span className="inline-flex items-center gap-1 rounded bg-violet-50 px-1.5 py-px text-[10px] font-medium text-violet-700">
                        <ScanIcon className="h-3 w-3" /> scan
                      </span>
                    )}
                    {s.headline && <span className="rounded bg-indigo-600 px-1.5 py-px text-[10px] font-semibold uppercase text-white">Headline</span>}
                  </div>
                </div>
                <div className="mt-1.5 text-sm font-semibold text-slate-900">{s.scenario}</div>
                <p className="mt-1 flex-1 text-[13px] leading-snug text-slate-600">{s.description}</p>
                <div className="mt-3 flex items-center justify-between gap-2">
                  <div className="text-xs text-slate-500">
                    Expect <span className={`font-semibold ${EXPECTED_STYLE[s.expected_decision]}`}>{s.expected_decision}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    {s.last_run && (
                      <Link to={`/runs/${s.last_run.id}`} title="Open last run">
                        <StatusBadge decision={s.last_run.decision} status={s.last_run.status} overridden={s.last_run.overridden} />
                      </Link>
                    )}
                    <button className="btn-primary px-2.5 py-1 text-xs" disabled={!s.available || starting !== null} onClick={() => runSample(s.file)}>
                      {starting === s.file ? <Spinner className="h-3 w-3" /> : "Run"}
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
