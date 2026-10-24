import { useState } from "react";
import { resetDemo } from "../api";
import { RESET_DONE_TEXT, RESET_LABEL, resetErrorText } from "../scale";

interface Props {
  /** Called after a successful reset so views refetch their state (Req 21.2). */
  onReset: () => void;
}

type Status = { kind: "idle" } | { kind: "pending" } | { kind: "done" } | { kind: "error"; message: string };

/** Labeled "Reset demo" button that calls POST /api/demo/reset (Req 21.2, 29.1). */
export function ResetControl({ onReset }: Props) {
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  const onClick = () => {
    setStatus({ kind: "pending" });
    resetDemo()
      .then(() => {
        setStatus({ kind: "done" });
        onReset();
      })
      .catch((e: unknown) => setStatus({ kind: "error", message: e instanceof Error ? e.message : String(e) }));
  };

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={onClick}
        disabled={status.kind === "pending"}
        className="flex items-center gap-1.5 whitespace-nowrap rounded-full border border-transparent px-3 py-1 text-[13px] text-muted transition-colors duration-150 ease-out hover:border-line hover:bg-line hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-60"
      >
        <svg aria-hidden="true" width="14" height="14" viewBox="0 0 16 16" fill="none">
          <path
            d="M3 8a5 5 0 1 0 1.6-3.7M3 2.5v2.8h2.8"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        {status.kind === "pending" ? "Resetting…" : RESET_LABEL}
      </button>
      <span role="status" className="text-sm text-ok">
        {status.kind === "done" ? RESET_DONE_TEXT : ""}
      </span>
      <span role="alert" className="text-sm text-help">
        {status.kind === "error" ? resetErrorText(status.message) : ""}
      </span>
    </div>
  );
}
