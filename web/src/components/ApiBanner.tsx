import { API_BASE, apiUnreachableText } from "../api";

interface Props {
  error: Error | null;
  loading: boolean;
  onRetry: () => void;
}

/** "API not reachable at {VITE_API_BASE}" with a keyboard-accessible Retry button (Req 28.4). */
export function ApiBanner({ error, loading, onRetry }: Props) {
  if (!error) return null;
  return (
    <div
      role="alert"
      className="mx-4 my-3 flex flex-wrap items-center gap-3 rounded-md border border-amber-400/60 bg-amber-950/60 px-4 py-3 text-amber-100"
    >
      <div className="flex-1">
        <p className="font-semibold">{apiUnreachableText(API_BASE)}</p>
        <p className="text-sm text-amber-200">
          {error.message}. Start it with <code>uvicorn api.main:app --port 8000</code>.
        </p>
      </div>
      <button
        type="button"
        onClick={onRetry}
        disabled={loading}
        className="rounded-md bg-amber-300 px-3 py-1.5 font-semibold text-slate-950 hover:bg-amber-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-100 disabled:opacity-60"
      >
        {loading ? "Retrying…" : "Retry"}
      </button>
    </div>
  );
}
