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
      className="flex flex-wrap items-center gap-3 rounded-card border border-line border-l-2 border-l-help bg-panel-solid px-4 py-3 text-fg shadow-panel"
    >
      <div className="flex-1">
        <p className="font-semibold">{apiUnreachableText(API_BASE)}</p>
        <p className="text-sm text-accent">
          {error.message}. Start it with <code>uvicorn api.main:app --port 8000</code>.
        </p>
      </div>
      <button
        type="button"
        onClick={onRetry}
        disabled={loading}
        className="rounded-md bg-accent px-3 py-1.5 font-semibold text-on-accent hover:bg-accent/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-60"
      >
        {loading ? "Retrying…" : "Retry"}
      </button>
    </div>
  );
}
