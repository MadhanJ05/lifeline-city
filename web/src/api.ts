// Typed client for the local Lifeline API. The web app talks to nothing else (Req 28.4).
import { useCallback, useEffect, useRef, useState } from "react";
import { POLL_INTERVAL_MS, nextPollDelay, shouldPoll, syncRunSource, type RunSource } from "./checkin";
import type {
  CapeTimeline,
  CapeTowns,
  CapeTracts,
  ContentResponse,
  Health,
  Hours,
  QueueRow,
  ResetResponse,
  Run,
  ScaleCatalog,
  Sources,
  StaticData,
  TelecomEvents,
  TractDetail,
} from "./types";

export const API_BASE: string = (import.meta.env.VITE_API_BASE ?? "http://localhost:8000").replace(/\/+$/, "");

/** Banner text when the API cannot be loaded (Req 28.4). */
export function apiUnreachableText(base: string = API_BASE): string {
  return `API not reachable at ${base}`;
}

export class ApiError extends Error {
  readonly status: number | null; // null when the request never reached the server
  readonly path: string;
  /** Machine-readable code from a `{detail: {code, message}}` body (e.g. 409 "phones_degraded"), else null. */
  readonly code: string | null;
  /** Human-readable detail from the body, without the "HTTP 409 for ..." prefix; null when absent. */
  readonly detail: string | null;

  constructor(message: string, path: string, status: number | null, code: string | null = null,
              detail: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.path = path;
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

/** Read FastAPI's `detail`: a plain string, or `{code, message}` from the check-in 409s. */
export function parseErrorDetail(body: unknown): { code: string | null; message: string | null } {
  if (!body || typeof body !== "object" || !("detail" in body)) return { code: null, message: null };
  const d: unknown = body.detail;
  if (typeof d === "string") return { code: null, message: d };
  if (d && typeof d === "object") {
    const code = "code" in d && typeof d.code === "string" ? d.code : null;
    const message = "message" in d && typeof d.message === "string" ? d.message : null;
    return { code, message };
  }
  return { code: null, message: null };
}

/** Build an API URL. Path segments and query values are URI-encoded. */
export function apiUrl(path: string, query?: Record<string, string>, base: string = API_BASE): string {
  const qs = query ? new URLSearchParams(query).toString() : "";
  return `${base}${path}${qs ? `?${qs}` : ""}`;
}

async function request<T>(method: "GET" | "POST", path: string, query?: Record<string, string>,
                          signal?: AbortSignal, body?: unknown): Promise<T> {
  let res: Response;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  try {
    res = await fetch(apiUrl(path, query), {
      method,
      signal,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(`Network error for ${path}`, path, null);
  }
  if (!res.ok) {
    let parsed: { code: string | null; message: string | null } = { code: null, message: null };
    try {
      parsed = parseErrorDetail(await res.json());
    } catch {
      // non-JSON error body; status alone is enough
    }
    const suffix = parsed.message ? `: ${parsed.message}` : parsed.code ? `: ${parsed.code}` : "";
    throw new ApiError(`HTTP ${res.status} for ${path}${suffix}`, path, res.status, parsed.code, parsed.message);
  }
  return (await res.json()) as T;
}

const seg = encodeURIComponent;

// ---------------------------------------------------------------- GET endpoints

export const getHealth = (signal?: AbortSignal) => request<Health>("GET", "/api/health", undefined, signal);
export const getHours = (signal?: AbortSignal) => request<Hours>("GET", "/api/hours", undefined, signal);
export const getTowns = (signal?: AbortSignal) => request<CapeTowns>("GET", "/api/towns", undefined, signal);
export const getTracts = (signal?: AbortSignal) => request<CapeTracts>("GET", "/api/tracts", undefined, signal);
export const getTimeline = (signal?: AbortSignal) =>
  request<CapeTimeline>("GET", "/api/timeline", undefined, signal);
export const getTelecomEvents = (signal?: AbortSignal) =>
  request<TelecomEvents>("GET", "/api/telecom-events", undefined, signal);
export const getSources = (signal?: AbortSignal) => request<Sources>("GET", "/api/sources", undefined, signal);
export const getScaleCatalog = (signal?: AbortSignal) =>
  request<ScaleCatalog>("GET", "/api/scale-catalog", undefined, signal);
export const getQueue = (hour: string, signal?: AbortSignal) =>
  request<QueueRow[]>("GET", "/api/queue", { hour }, signal);
export const getTractDetail = (geoid: string, hour: string, signal?: AbortSignal) =>
  request<TractDetail>("GET", `/api/tracts/${seg(geoid)}`, { hour }, signal);
export const getContent = (geoid: string, hour: string, signal?: AbortSignal) =>
  request<ContentResponse>("GET", `/api/content/${seg(geoid)}`, { hour }, signal);

// ---------------------------------------------------------------- POST endpoints

/** Clear every check-in run, reply, escalation and counter (Req 21.1). */
export const resetDemo = (signal?: AbortSignal) =>
  request<ResetResponse>("POST", "/api/demo/reset", undefined, signal);

/** Start (201) or return the existing (200) Check_In_Run for an sms tract-hour (Req 18.1). A door_knock
 *  tract-hour is rejected with 409 `phones_degraded` and no SMS is sent (Req 15.6). */
export const sendCheckins = (geoid: string, hour: string, signal?: AbortSignal) =>
  request<Run>("POST", "/api/checkins/send", undefined, signal, { geoid, hour });

/** The run after the API advances it (due replies delivered, timeout applied). */
export const getRun = (runId: string, signal?: AbortSignal) =>
  request<Run>("GET", `/api/checkins/${seg(runId)}`, undefined, signal);

/** A reply typed by the Operator in the Phone_Simulator (Req 18.5); returns the updated run. */
export const postReply = (runId: string, householdId: string, body: string, signal?: AbortSignal) =>
  request<Run>("POST", "/api/simulator/reply", undefined, signal, { run_id: runId, household_id: householdId, body });

// ---------------------------------------------------------------- hooks

export async function loadStaticData(signal?: AbortSignal): Promise<StaticData> {
  const [hours, towns, tracts, timeline, events, sources, catalog] = await Promise.all([
    getHours(signal),
    getTowns(signal),
    getTracts(signal),
    getTimeline(signal),
    getTelecomEvents(signal),
    getSources(signal),
    getScaleCatalog(signal),
  ]);
  return { hours, towns, tracts, timeline, events, sources, catalog };
}

export interface StaticDataState {
  data: StaticData | null;
  error: ApiError | Error | null;
  loading: boolean;
  retry: () => void;
}

/** Load the static demo data once, in parallel. `retry()` reloads after a failure. */
export function useStaticData(): StaticDataState {
  const [attempt, setAttempt] = useState(0);
  const [data, setData] = useState<StaticData | null>(null);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    loadStaticData(ctrl.signal)
      .then((d) => {
        setData(d);
        setLoading(false);
      })
      .catch((e: unknown) => {
        if (ctrl.signal.aborted) return;
        setError(e instanceof Error ? e : new Error(String(e)));
        setLoading(false);
      });
    return () => ctrl.abort();
  }, [attempt]);

  const retry = useCallback(() => setAttempt((a) => a + 1), []);
  return { data, error, loading, retry };
}

export interface TractDetailState {
  detail: TractDetail | null;
  content: ContentResponse | null;
  loading: boolean;
  error: ApiError | Error | null;
  reload: () => void;
}

/** Tract detail and content for the selected tract-hour, fetched in parallel. A change of tract or
 *  hour aborts the in-flight pair. The previous data stays visible while the next pair loads, so the
 *  drawer never blanks on an hour change; `loading` drives aria-busy. `geoid === null` clears it.
 *  A change of `version` (the App's reset counter) refetches the same tract-hour (Req 21.2). */
export function useTractDetail(geoid: string | null, hour: string, version = 0): TractDetailState {
  const [attempt, setAttempt] = useState(0);
  const [detail, setDetail] = useState<TractDetail | null>(null);
  const [content, setContent] = useState<ContentResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | Error | null>(null);

  useEffect(() => {
    if (!geoid || !hour) {
      setDetail(null);
      setContent(null);
      setLoading(false);
      setError(null);
      return;
    }
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    Promise.all([getTractDetail(geoid, hour, ctrl.signal), getContent(geoid, hour, ctrl.signal)])
      .then(([d, c]) => {
        if (ctrl.signal.aborted) return;
        setDetail(d);
        setContent(c);
        setLoading(false);
      })
      .catch((e: unknown) => {
        if (ctrl.signal.aborted) return;
        setError(e instanceof Error ? e : new Error(String(e)));
        setLoading(false);
      });
    return () => ctrl.abort();
  }, [geoid, hour, attempt, version]);

  const reload = useCallback(() => setAttempt((a) => a + 1), []);
  return { detail, content, loading, error, reload };
}

export interface RunPollingState {
  run: Run | null;
  error: ApiError | Error | null;
  /** Fetch the run now, then keep the 2 s cadence while it is active. */
  refresh: () => void;
  /** Replace the run (send or reply response). Restarts the cadence, so an older in-flight poll is dropped. */
  setRun: (run: Run | null) => void;
}

interface PollState extends RunSource<Run> {
  error: ApiError | Error | null;
}

/** Hold a Check_In_Run and poll `GET /api/checkins/{id}` every 2 s while it is active (Req 18.7). Polling
 *  stops when the run completes (Req 18.8), on unmount, or when the run id changes. `initialRun` is the
 *  run from TractDetail; a new value replaces the held run. A change of `key` (tract, hour or reset
 *  version) clears the run, so the drawer shows no run after a demo reset (Req 21.2). */
export function useRunPolling(initialRun: Run | null, key = ""): RunPollingState {
  const [state, setState] = useState<PollState>({ run: initialRun, initial: initialRun, key, error: null });
  const [kick, setKick] = useState({ n: 0, immediate: false });

  // Derived state from props, applied during render (React's recommended pattern for resets).
  let current = state;
  const synced = syncRunSource(state, initialRun, key);
  if (synced !== state) {
    current = { ...synced, error: null };
    setState(current);
  }

  const runId = current.run?.id ?? null;
  const active = shouldPoll(current.run);

  useEffect(() => {
    if (!runId || (!active && !kick.immediate)) return;
    const ctrl = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const schedule = (delay: number) => {
      timer = setTimeout(() => {
        getRun(runId, ctrl.signal)
          .then((r) => {
            if (ctrl.signal.aborted) return;
            setState((prev) => (prev.run?.id === runId ? { ...prev, run: r, error: null } : prev));
            const next = nextPollDelay(r);
            if (next !== null) schedule(next);
          })
          .catch((e: unknown) => {
            if (ctrl.signal.aborted) return;
            const err = e instanceof Error ? e : new Error(String(e));
            setState((prev) => (prev.run?.id === runId ? { ...prev, error: err } : prev));
            // 404: the run is gone (reset elsewhere), stop. Network errors retry on the same cadence.
            if (!(err instanceof ApiError && err.status === 404)) schedule(POLL_INTERVAL_MS);
          });
      }, delay);
    };
    schedule(kick.immediate ? 0 : POLL_INTERVAL_MS);
    return () => {
      ctrl.abort();
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [runId, active, kick]);

  const setRun = useCallback((run: Run | null) => {
    setState((prev) => ({ ...prev, run, error: null }));
    setKick((k) => ({ n: k.n + 1, immediate: false }));
  }, []);
  const refresh = useCallback(() => setKick((k) => ({ n: k.n + 1, immediate: true })), []);

  return { run: current.run, error: current.error, refresh, setRun };
}

/** Latest value in a ref, for async callbacks that must ignore results for a stale tract-hour. */
export function useLatest<T>(value: T): { readonly current: T } {
  const ref = useRef(value);
  ref.current = value;
  return ref;
}
