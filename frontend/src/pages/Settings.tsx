import { FormEvent, useEffect, useState } from "react";
import { api, AppConfig, codeTitle, SettingsResponse } from "../api";
import { Spinner } from "../components/Icons";

interface NumberFieldProps {
  label: string;
  hint: string;
  value: string | number;
  onChange: (v: string) => void;
  min: number;
  max: number;
  step: number;
}

function NumberField({ label, hint, value, onChange, min, max, step }: NumberFieldProps) {
  const n = Number(value);
  const invalid = value === "" || Number.isNaN(n) || n < min || n > max;
  return (
    <div>
      <label className="label">{label}</label>
      <input type="number" className={`input ${invalid ? "border-rose-400" : ""}`} value={value} min={min} max={max} step={step} onChange={(e) => onChange(e.target.value)} />
      <div className={`mt-1 text-[11px] ${invalid ? "text-rose-600" : "text-slate-500"}`}>{invalid ? `Must be between ${min} and ${max}` : hint}</div>
    </div>
  );
}

function valid(c: AppConfig): boolean {
  const inRange = (v: string | number, lo: number, hi: number) => v !== "" && !Number.isNaN(Number(v)) && Number(v) >= lo && Number(v) <= hi;
  return (
    inRange(c.tolerance.unit_price_pct, 0, 0.5) &&
    inRange(c.tolerance.total_pct, 0, 0.5) &&
    inRange(c.tolerance.po_overrun_pct, 0, 0.5) &&
    inRange(c.tolerance.total_abs, 0, 100000) &&
    inRange(c.extraction.min_confidence, 0, 1) &&
    inRange(c.policy.auto_approve_max_amount, 0, 1e9) &&
    inRange(c.demo.stage_delay_ms, 0, 5000) &&
    inRange(c.demo.inbox_poll_seconds, 0.5, 60)
  );
}

export default function Settings() {
  const [data, setData] = useState<SettingsResponse | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [resetting, setResetting] = useState(false);

  useEffect(() => {
    api.settings().then((d) => {
      setData(d);
      setConfig(d.config);
    });
  }, []);

  const flash = (kind: "ok" | "error", text: string) => {
    setToast({ kind, text });
    window.setTimeout(() => setToast(null), 3500);
  };

  if (!data || !config) {
    return <div className="flex items-center gap-2 p-8 text-sm text-slate-500"><Spinner /> Loading settings…</div>;
  }

  const set = <K extends keyof AppConfig>(section: K, patch: Partial<AppConfig[K]>) =>
    setConfig({ ...config, [section]: { ...config[section], ...patch } });

  const toggleCode = (code: string) => {
    const list = config.policy.never_auto_approve_on;
    set("policy", { never_auto_approve_on: list.includes(code) ? list.filter((c) => c !== code) : [...list, code] });
  };

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const payload: AppConfig = {
        ...config,
        extraction: { min_confidence: Number(config.extraction.min_confidence) },
        demo: { stage_delay_ms: Number(config.demo.stage_delay_ms), inbox_poll_seconds: Number(config.demo.inbox_poll_seconds) },
      };
      const saved = await api.saveSettings(payload);
      setData(saved);
      setConfig(saved.config);
      flash("ok", "Settings saved. They apply from the next run; earlier runs keep their snapshot.");
    } catch (err) {
      flash("error", err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const reset = async () => {
    setResetting(true);
    try {
      await api.reset();
      setConfirmReset(false);
      flash("ok", "Demo data reset: runs, PO consumption, fingerprints and audit cleared. Reference data kept.");
    } catch (err) {
      flash("error", err instanceof Error ? err.message : String(err));
    } finally {
      setResetting(false);
    }
  };

  const t = config.tolerance;
  return (
    <div className="mx-auto max-w-[920px] space-y-5 px-8 py-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Settings</h1>
        <p className="text-sm text-slate-500">Tolerances and policy used by the deterministic rules. Saved to config.yaml and snapshotted into every run.</p>
      </header>

      <form onSubmit={save} className="space-y-5">
        <section className="card p-5">
          <h2 className="card-title mb-4">Tolerances</h2>
          <div className="grid grid-cols-2 gap-4">
            <NumberField label="Unit price tolerance (fraction)" hint={`±${(Number(t.unit_price_pct) * 100).toFixed(1)}% per line vs PO price`} value={t.unit_price_pct} min={0} max={0.5} step={0.005} onChange={(v) => set("tolerance", { unit_price_pct: v })} />
            <NumberField label="PO overrun allowed (fraction)" hint={`${(Number(t.po_overrun_pct) * 100).toFixed(1)}% over remaining PO budget`} value={t.po_overrun_pct} min={0} max={0.5} step={0.01} onChange={(v) => set("tolerance", { po_overrun_pct: v })} />
            <NumberField label="Total variance: absolute cap" hint="Max difference from expected total, in currency" value={t.total_abs} min={0} max={100000} step={1} onChange={(v) => set("tolerance", { total_abs: v })} />
            <NumberField label="Total variance: percentage cap (fraction)" hint="The smaller of the two caps applies" value={t.total_pct} min={0} max={0.5} step={0.005} onChange={(v) => set("tolerance", { total_pct: v })} />
          </div>
        </section>

        <section className="card p-5">
          <h2 className="card-title mb-4">Extraction & policy</h2>
          <div className="grid grid-cols-2 gap-4">
            <NumberField label="Minimum field confidence" hint="Required fields below this are held for review" value={config.extraction.min_confidence} min={0} max={1} step={0.05} onChange={(v) => set("extraction", { min_confidence: Number(v) })} />
            <NumberField label="Auto-approve limit" hint="Invoices above this amount always need sign-off" value={config.policy.auto_approve_max_amount} min={0} max={1e9} step={100} onChange={(v) => set("policy", { auto_approve_max_amount: v })} />
          </div>
          <div className="mt-5">
            <div className="label">Never auto-approve when any of these findings appear</div>
            <div className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1.5">
              {data.known_codes.map(({ code, title, description }) => (
                <label key={code} className="flex items-center gap-2 text-sm text-slate-700" title={description}>
                  <input type="checkbox" className="h-4 w-4 rounded border-slate-300 text-indigo-600" checked={config.policy.never_auto_approve_on.includes(code)} onChange={() => toggleCode(code)} />
                  <span className="truncate">{codeTitle(code, title)}</span>
                </label>
              ))}
            </div>
          </div>
        </section>

        <section className="card p-5">
          <h2 className="card-title mb-4">Demo & LLM</h2>
          <div className="grid grid-cols-2 gap-4">
            <NumberField label="Stage delay (ms)" hint="Pause after each stage so the live view is readable" value={config.demo.stage_delay_ms} min={0} max={5000} step={50} onChange={(v) => set("demo", { stage_delay_ms: Number(v) })} />
            <NumberField label="Inbox poll interval (s)" hint="How often the email inbox folder is scanned" value={config.demo.inbox_poll_seconds} min={0.5} max={60} step={0.5} onChange={(v) => set("demo", { inbox_poll_seconds: Number(v) })} />
          </div>
          <label className="mt-4 flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" className="h-4 w-4 rounded border-slate-300 text-indigo-600" checked={config.llm.cache_enabled} onChange={(e) => set("llm", { cache_enabled: e.target.checked })} />
            Use the LLM response cache (keyed by file hash, provider, model and prompt version)
          </label>
        </section>

        <div className="flex items-center justify-end gap-3">
          <button type="submit" className="btn-primary" disabled={saving || !valid(config)}>
            {saving && <Spinner className="h-3.5 w-3.5" />} Save settings
          </button>
        </div>
      </form>

      <section className="rounded-xl border border-rose-200 bg-white p-5">
        <h2 className="text-sm font-semibold text-rose-700">Reset demo data</h2>
        <p className="mt-1 text-sm text-slate-600">Deletes all runs, PO consumption, duplicate fingerprints and audit events. Vendors and POs are kept.</p>
        {confirmReset ? (
          <div className="mt-3 flex items-center gap-2">
            <span className="text-sm font-medium text-rose-700">This cannot be undone.</span>
            <button className="btn-danger" onClick={reset} disabled={resetting}>
              {resetting && <Spinner className="h-3.5 w-3.5" />} Yes, reset everything
            </button>
            <button className="btn-secondary" onClick={() => setConfirmReset(false)}>Cancel</button>
          </div>
        ) : (
          <button className="btn-danger mt-3" onClick={() => setConfirmReset(true)}>Reset demo data…</button>
        )}
      </section>

      {toast && (
        <div className={`fixed bottom-6 right-6 z-50 max-w-sm rounded-lg px-4 py-3 text-sm shadow-lg ${toast.kind === "ok" ? "bg-slate-900 text-white" : "bg-rose-600 text-white"}`}>
          {toast.text}
        </div>
      )}
    </div>
  );
}
