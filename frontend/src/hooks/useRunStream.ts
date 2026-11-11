import { useCallback, useEffect, useRef, useState } from "react";
import { api, RunDetail, RunEvent, Stage, StepOut } from "../api";

export type StageState = "pending" | "running" | "completed" | "failed";

export interface StageView {
  state: StageState;
  summary: string | null;
  detail: StepOut["detail"];
  durationMs: number | null;
}

type StageMap = Partial<Record<Stage, StageView>>;

function fromSteps(steps: StepOut[]): StageMap {
  const map: StageMap = {};
  for (const s of steps) {
    map[s.stage] = {
      state: s.status === "completed" ? "completed" : s.status === "failed" ? "failed" : "running",
      summary: s.summary,
      detail: s.detail,
      durationMs: s.duration_ms,
    };
  }
  return map;
}

const RANK: Record<StageState, number> = { pending: 0, running: 1, completed: 2, failed: 2 };

// A detail fetch can land after newer SSE events; never move a stage backwards.
function merge(current: StageMap, fetched: StageMap): StageMap {
  const out: StageMap = { ...current };
  for (const [stage, view] of Object.entries(fetched) as [Stage, StageView][]) {
    const existing = out[stage];
    if (!existing || RANK[view.state] >= RANK[existing.state]) out[stage] = view;
  }
  return out;
}

function applyEvent(map: StageMap, ev: RunEvent): StageMap {
  if (!ev.stage || ev.type === "run_completed" || ev.type === "run_failed") return map;
  const next = { ...map };
  if (ev.type === "stage_started") {
    next[ev.stage] = { state: "running", summary: null, detail: {}, durationMs: null };
  } else {
    next[ev.stage] = {
      state: ev.type === "stage_completed" ? "completed" : "failed",
      summary: ev.summary,
      detail: ev.detail,
      durationMs: ev.duration_ms,
    };
  }
  return next;
}

/** Live view of one run: SSE for stage events, full detail refetched at the end; polls if SSE drops. */
export function useRunStream(runId: string | undefined) {
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [stages, setStages] = useState<StageMap>({});
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState(false);
  const pollRef = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    if (!runId) return null;
    try {
      const d = await api.run(runId);
      setDetail(d);
      setStages((prev) => merge(prev, fromSteps(d.steps)));
      setError(null);
      return d;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return null;
    }
  }, [runId]);

  useEffect(() => {
    if (!runId) return;
    let closed = false;
    setDetail(null);
    setStages({});
    refresh();

    const stopPolling = () => {
      if (pollRef.current !== null) window.clearInterval(pollRef.current);
      pollRef.current = null;
    };
    const startPolling = () => {
      if (pollRef.current !== null) return;
      pollRef.current = window.setInterval(async () => {
        const d = await refresh();
        if (d && (d.run.status === "completed" || d.run.status === "failed")) stopPolling();
      }, 2000);
    };

    const source = new EventSource(api.eventsUrl(runId));
    source.onopen = () => setLive(true);
    source.onmessage = (msg) => {
      const ev = JSON.parse(msg.data) as RunEvent;
      setStages((prev) => applyEvent(prev, ev));
      if (ev.type === "run_completed" || ev.type === "run_failed") {
        source.close();
        setLive(false);
        refresh();
      }
    };
    source.onerror = () => {
      source.close();
      setLive(false);
      if (!closed) startPolling();
    };

    return () => {
      closed = true;
      source.close();
      stopPolling();
    };
  }, [runId, refresh]);

  return { detail, stages, error, live, refresh };
}
