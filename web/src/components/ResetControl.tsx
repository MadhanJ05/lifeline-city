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
        className="rounded-md border border-slate-500 bg-slate-800 px-2.5 py-1 text-sm text-slate-100 hover:bg-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-300 disabled:opacity-60"
      >
        {status.kind === "pending" ? "Resetting…" : RESET_LABEL}
      </button>
      <span role="status" className="text-sm text-emerald-200">
        {status.kind === "done" ? RESET_DONE_TEXT : ""}
      </span>
      <span role="alert" className="text-sm text-rose-200">
        {status.kind === "error" ? resetErrorText(status.message) : ""}
      </span>
    </div>
  );
}
