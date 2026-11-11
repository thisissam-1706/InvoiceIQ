export type Decision = "APPROVE" | "HOLD" | "REJECT";
export type RunStatus = "queued" | "running" | "completed" | "failed";
export type Severity = "pass" | "info" | "warning" | "review" | "block";
export type StepStatus = "started" | "completed" | "failed" | "skipped";

export const STAGES = [
  "ingest",
  "text_extract",
  "llm_extract",
  "normalise",
  "validate",
  "vendor_match",
  "po_match",
  "duplicates",
  "rules",
  "decision",
  "explain",
] as const;
export type Stage = (typeof STAGES)[number];

export const STAGE_LABELS: Record<Stage, string> = {
  ingest: "Ingest",
  text_extract: "Text extraction",
  llm_extract: "AI field extraction",
  normalise: "Normalisation",
  validate: "Validation",
  vendor_match: "Vendor match",
  po_match: "PO match",
  duplicates: "Duplicate check",
  rules: "Tolerance & rules",
  decision: "Decision",
  explain: "Explanation",
};

export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

export interface RunSummary {
  id: string;
  created_at: string;
  finished_at: string | null;
  source: string;
  file_name: string;
  status: RunStatus;
  current_stage: Stage | null;
  decision: Decision | null;
  original_decision: Decision | null;
  decision_overridden: boolean;
  vendor_id: string | null;
  vendor_name: string | null;
  po_number: string | null;
  invoice_number: string | null;
  invoice_total: string | null;
  currency: string | null;
  doc_type: "digital" | "scanned" | null;
  duration_ms: number | null;
  error_message: string | null;
  rerun_of: string | null;
  superseded_by: string | null;
}

export interface RunList {
  items: RunSummary[];
  total: number;
}

export interface StepOut {
  stage: Stage;
  status: StepStatus;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  summary: string | null;
  detail: JsonObject;
}

export interface CheckOut {
  code: string;
  title?: string;
  description?: string;
  severity: Severity;
  message: string;
  stage: Stage | "";
  field: string | null;
  critical: boolean;
  data: JsonObject;
}

export interface ExtractedField {
  value: string | number | boolean | null;
  confidence: number;
  source_text: string | null;
}

export interface ExtractedLine {
  description: string;
  sku: string | null;
  quantity: string | null;
  unit_price: string | null;
  amount: string | null;
}

export type ExtractionFields = { [name: string]: ExtractedField } & { line_items?: ExtractedLine[] };

export interface ExtractionMeta {
  provider: string;
  model: string;
  mode: string;
  cached: boolean;
  attempts: number;
  prompt_version: string;
  fields_found: number;
  fields_total: number;
  line_items: number;
  avg_confidence: number;
  confidence_adjustments: { field: string; from: number; to: number }[];
  confidence_cap: number | null;
  fallback_from?: string;
  fallback_reason?: string;
}

export interface Extraction {
  fields: ExtractionFields;
  meta: ExtractionMeta;
}

export interface NormalisedInvoice {
  vendor_name: string | null;
  invoice_number: string | null;
  invoice_number_norm: string | null;
  invoice_date: string | null;
  invoice_date_raw: string | null;
  date_reading: string | null;
  po_number: string | null;
  currency: string | null;
  subtotal: string | null;
  tax_amount: string | null;
  tax_rate: string | null;
  total: string | null;
  tax_mode: string;
  tax_note: string;
  pretax_subtotal: string | null;
  tax_effective: string;
}

export interface Validation {
  invoice: NormalisedInvoice;
  line_sum: string | null;
}

export interface Vendor {
  vendor_id: string;
  name: string;
  aliases: string[];
  tax_id: string | null;
  bank_account_last4: string | null;
  bank_routing: string | null;
  country: string;
  currency: string;
  status: string;
  payment_terms_days: number;
}

export interface LineMatch {
  invoice_line: number;
  description: string;
  sku: string | null;
  po_line_no: number;
  po_description: string;
  po_sku: string | null;
  match_method: "sku" | "description";
  match_score: number;
  uom: string;
  invoice_qty: string | null;
  po_qty: string;
  already_billed_qty: string;
  received_qty: string | null;
  invoice_unit_price: string | null;
  po_unit_price: string;
  variance_pct: string | null;
  line_amount: string | null;
  price_checked: boolean;
}

export interface Budget {
  po_total: string;
  consumed_before: string;
  this_invoice: string;
  remaining_before: string;
  remaining_after: string;
  allowed: string;
  overrun: string;
  pct_consumed_after: string;
  is_blanket: boolean;
}

export interface POCandidate {
  po_number: string;
  line_match_score: number;
  amount_proximity_score: number;
  score: number;
}

export interface Matching {
  vendor_match: { method: string; score: number; candidate: string | null; status?: string };
  vendor: Vendor | null;
  po: {
    po_number: string;
    vendor_id: string;
    status: string;
    total: string;
    consumed: string;
    remaining: string;
    is_blanket: boolean;
    line_count: number;
  } | null;
  po_match: { method: string; reference?: string | null; normalised?: string; candidates?: POCandidate[]; score?: number };
  line_matches: LineMatch[];
  budget: Budget | Record<string, never>;
  duplicate: { compared_against?: number; match?: string | null; run_id?: string | null };
  pretax_subtotal: string | null;
}

export interface VendorEmail {
  to: string;
  subject: string;
  body: string;
  polished_by_llm: boolean;
}

export interface Actions {
  actions: { code: string; severity: Severity; text: string }[];
  primary: string | null;
  vendor_email: VendorEmail | null;
  payment_due_date: string | null;
  po_consumed: string | null;
}

export interface AuditOut {
  at: string;
  actor: "system" | "reviewer";
  action: string;
  note: string | null;
}

export interface RunDetail {
  run: RunSummary;
  steps: StepOut[];
  extraction: Extraction | null;
  validation: Validation | null;
  matching: Matching | null;
  rules: { config_snapshot: AppConfig; checks: CheckOut[]; findings: CheckOut[] } | null;
  checks: CheckOut[];
  explanation: string | null;
  actions: Actions | null;
  audit: AuditOut[];
  llm_provider: string | null;
  llm_model: string | null;
  provider_note: string | null;
}

export interface RunEvent {
  type: "stage_started" | "stage_completed" | "stage_failed" | "run_completed" | "run_failed";
  run_id: string;
  stage: Stage | null;
  at: string;
  summary: string | null;
  detail: JsonObject;
  decision: Decision | null;
  duration_ms: number | null;
}

export interface Sample {
  file: string;
  scenario: string;
  description: string;
  expected_decision: Decision;
  expected_codes: string[];
  headline: boolean;
  scanned: boolean;
  available: boolean;
  last_run: { id: string; decision: Decision | null; status: RunStatus; overridden: boolean } | null;
}

export interface Stats {
  total_runs: number;
  processed: number;
  failed: number;
  in_progress: number;
  approved: number;
  auto_approved: number;
  on_hold: number;
  rejected: number;
  overridden: number;
  auto_approve_rate: number;
  total_value: string;
  avg_duration_ms: number;
  top_findings: { code: string; label: string; title: string; description: string; count: number }[];
  recent: { id: string; created_at: string; file_name: string; decision: Decision | null; status: RunStatus; overridden: boolean }[];
  needs_attention: {
    id: string;
    created_at: string;
    file_name: string;
    vendor_name: string | null;
    invoice_number: string | null;
    invoice_total: string | null;
    currency: string | null;
    codes: string[];
    findings: { code: string; title: string; description: string }[];
    primary_action: string | null;
  }[];
}

export interface Health {
  status: "ok" | "degraded";
  configured_provider: string;
  provider: string;
  model: string;
  provider_note: string | null;
  cache_enabled: boolean;
  cache_entries: number;
  db_ok: boolean;
  worker_alive: boolean;
  queue_size: number;
  current_run: string | null;
  inbox_dir: string;
}

export interface POLineOut {
  line_no: number;
  sku: string | null;
  description: string;
  quantity: string;
  unit_price: string;
  uom: string;
  line_total: string;
  received_qty: string | null;
}

export interface PurchaseOrder {
  po_number: string;
  vendor_id: string;
  vendor_name: string | null;
  issue_date: string;
  currency: string;
  status: string;
  total_amount: string;
  consumed: string;
  remaining: string;
  lines: POLineOut[];
  runs: {
    run_id: string;
    file_name: string;
    invoice_number: string | null;
    invoice_total: string | null;
    decision: Decision | null;
    decision_overridden: boolean;
    status: RunStatus;
    consumed_amount: string | null;
  }[];
}

export interface AppConfig {
  tolerance: { unit_price_pct: string; total_abs: string; total_pct: string; po_overrun_pct: string };
  extraction: { min_confidence: number };
  policy: { auto_approve_max_amount: string; never_auto_approve_on: string[] };
  demo: { stage_delay_ms: number; inbox_poll_seconds: number };
  llm: { cache_enabled: boolean };
}

export interface SettingsResponse {
  config: AppConfig;
  known_codes: { code: string; label: string; title: string; description: string }[];
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function errorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((d) => {
          const item = d as { loc?: (string | number)[]; msg?: string };
          return `${(item.loc ?? []).slice(1).join(".")}: ${item.msg ?? ""}`;
        })
        .join("; ");
    }
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  const text = await res.text();
  const body: unknown = text ? JSON.parse(text) : null;
  if (!res.ok) throw new ApiError(res.status, errorMessage(body, `${res.status} ${res.statusText}`));
  return body as T;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export interface RunFilters {
  decision?: Decision;
  status?: RunStatus;
  q?: string;
  limit?: number;
}

export const api = {
  health: () => request<Health>("/api/health"),
  stats: () => request<Stats>("/api/stats"),
  runs: (filters: RunFilters = {}) => {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([k, v]) => v !== undefined && v !== "" && params.set(k, String(v)));
    return request<RunList>(`/api/runs?${params}`);
  },
  run: (id: string) => request<RunDetail>(`/api/runs/${id}`),
  upload: (files: File[]) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    return request<{ run_id: string; file_name: string }[]>("/api/runs", { method: "POST", body: form });
  },
  runSample: (file: string) => request<{ run_id: string; file_name: string }>(`/api/runs/sample/${encodeURIComponent(file)}`, { method: "POST" }),
  samples: () => request<Sample[]>("/api/samples"),
  override: (id: string, decision: "APPROVE" | "REJECT", note: string) =>
    request<RunSummary>(`/api/runs/${id}/override`, json("POST", { decision, note })),
  rerun: (id: string) => request<{ run_id: string; file_name: string }>(`/api/runs/${id}/rerun`, { method: "POST" }),
  vendors: () => request<Vendor[]>("/api/reference/vendors"),
  pos: () => request<PurchaseOrder[]>("/api/reference/pos"),
  settings: () => request<SettingsResponse>("/api/settings"),
  saveSettings: (config: AppConfig) => request<SettingsResponse>("/api/settings", json("PUT", config)),
  reset: () => request<{ ok: boolean }>("/api/system/reset", json("POST", { confirm: true })),
  fileUrl: (id: string) => `/api/runs/${id}/file`,
  eventsUrl: (id: string) => `/api/runs/${id}/events`,
};

/** Plain-English name for a finding code. Pass the title from the API when you have it; otherwise
 * (unknown or new codes) fall back to a humanised code: SOME_CODE -> "Some code". */
export function codeTitle(code: string, title?: string | null): string {
  if (title) return title;
  const text = code.replace(/_/g, " ").trim().toLowerCase();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function money(value: string | number | null | undefined, currency: string | null = "USD"): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(n)) return String(value);
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: currency || "USD" }).format(n);
  } catch {
    return `${n.toFixed(2)} ${currency}`;
  }
}

/** Short money for tight spaces: $3B, $1.2M, $48.3K. Keep the exact figure from money() in a tooltip. */
export function compactMoney(value: string | number | null | undefined, currency: string | null = "USD"): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(n)) return String(value);
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: currency || "USD", notation: "compact", maximumFractionDigits: 1 }).format(n);
  } catch {
    return `${n.toFixed(2)} ${currency}`;
  }
}

export function pct(fraction: string | number | null | undefined, digits = 1): string {
  if (fraction === null || fraction === undefined) return "—";
  const n = Number(fraction) * 100;
  return `${n > 0 ? "+" : ""}${n.toFixed(digits)}%`;
}

export function duration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export function timeAgo(iso: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return `${Math.floor(seconds)}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}

export function clockTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
