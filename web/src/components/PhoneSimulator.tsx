import { useCallback, useEffect, useId, useRef, useState, type FormEvent } from "react";
import { postReply, useLatest } from "../api";
import {
  NO_RUN_DOOR_KNOCK_NOTE,
  NO_RUN_SMS_NOTE,
  REPLY_HINT,
  REPLY_MAX_LENGTH,
  SENDER_NAME,
  SIMULATOR_HEADING,
  householdOptionLabel,
  maskPhonesInText,
  messageClassText,
  messageKindLabel,
  messageSourceLabel,
  messageTimeText,
  quickReplies,
  replyBody,
  replyErrorText,
  replyLabel,
  resolveHouseholdId,
  threadLabel,
  toLineText,
} from "../phone";
import type { Run, RunHousehold, RunMessage } from "../types";
import type { RunContext } from "./TractDrawer";
import { SimulatedBadge } from "./SimulatedBadge";

const FOCUS = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

/** In-app phone for the check-in loop (Req 14.8, 18.4, 18.5, 26.5, 29.1). Plugged into the drawer through
 *  TractDrawer's `reach` render prop. Everything here is synthetic and labeled "Simulated". */
export function PhoneSimulator({ detail, run, onRunUpdate }: RunContext) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-2 rounded-card border border-line p-3 text-[13px]">
      <h4 id={headingId} className="font-semibold">
        {SIMULATOR_HEADING}
      </h4>
      {run ? (
        <SimulatorBody key={run.id} run={run} onRunUpdate={onRunUpdate} />
      ) : (
        <p className="text-muted">{detail.channel === "sms" ? NO_RUN_SMS_NOTE : NO_RUN_DOOR_KNOCK_NOTE}</p>
      )}
    </section>
  );
}

/** Keyed by run id, so a new run resets the picked household, the draft and any error. */
function SimulatorBody({ run, onRunUpdate }: { run: Run; onRunUpdate: (run: Run) => void }) {
  const pickerId = useId();
  const [picked, setPicked] = useState<string | null>(null);
  const householdId = resolveHouseholdId(run.households, picked);
  const household = run.households.find((h) => h.id === householdId) ?? null;

  if (!household) return <p className="text-muted">No simulated households in this run.</p>;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <label htmlFor={pickerId} className="font-semibold">
          Household
        </label>
        <select
          id={pickerId}
          value={household.id}
          onChange={(e) => setPicked(e.target.value)}
          className={`rounded-card border border-line-strong bg-bg px-2 py-1.5 text-fg ${FOCUS}`}
        >
          {run.households.map((h) => (
            <option key={h.id} value={h.id}>
              {householdOptionLabel(h)}
            </option>
          ))}
        </select>
      </div>
      <PhoneFrame run={run} household={household} onRunUpdate={onRunUpdate} />
    </div>
  );
}

interface FrameProps {
  run: Run;
  household: RunHousehold;
  onRunUpdate: (run: Run) => void;
}

function PhoneFrame({ run, household, onRunUpdate }: FrameProps) {
  const inputId = useId();
  const hintId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [draft, setDraft] = useState("");
  const [posting, setPosting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const latestRunId = useLatest(run.id);
  const ctrlRef = useRef<AbortController | null>(null);

  // Abort an in-flight reply when the frame unmounts (drawer closed, tract-hour changed).
  useEffect(() => () => ctrlRef.current?.abort(), []);

  const send = useCallback(
    (raw: string, fromBox: boolean) => {
      const body = replyBody(raw);
      if (posting || body === null) return;
      const runId = run.id;
      const ctrl = new AbortController();
      ctrlRef.current = ctrl;
      setPosting(true);
      setError(null);
      postReply(runId, household.id, body, ctrl.signal)
        .then((r) => {
          if (ctrl.signal.aborted || latestRunId.current !== runId || r.id !== runId) return;
          onRunUpdate(r);
          if (fromBox) setDraft("");
        })
        .catch((e: unknown) => {
          if (ctrl.signal.aborted || latestRunId.current !== runId) return;
          setError(replyErrorText(e));
        })
        .finally(() => {
          if (ctrl.signal.aborted) return;
          setPosting(false);
          if (fromBox) inputRef.current?.focus();
        });
    },
    [posting, run.id, household.id, latestRunId, onRunUpdate],
  );

  const onSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    send(draft, true);
  };

  const canSend = !posting && replyBody(draft) !== null;

  return (
    <div className="mx-auto flex w-full max-w-[22rem] flex-col gap-2 rounded-[24px] border border-line-strong bg-bg p-3">
      {/* Sender and "Simulated" label sit outside the message bubbles (Req 14.8). */}
      <div className="flex flex-col gap-0.5 border-b border-line pb-2">
        <p className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-muted">From:</span>
          <span className="font-semibold">{SENDER_NAME}</span>
          <SimulatedBadge />
        </p>
        <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
          <span className="tabular-nums">{toLineText(household.phone)}</span>
          <span aria-hidden="true">·</span>
          <span>{household.label}</span>
        </p>
      </div>

      <Thread household={household} />

      <form onSubmit={onSubmit} className="flex flex-col gap-1.5 border-t border-line pt-2" aria-busy={posting}>
        <label htmlFor={inputId} className="text-xs font-semibold">
          {replyLabel(household)}
        </label>
        <div className="flex gap-1.5">
          <input
            ref={inputRef}
            id={inputId}
            type="text"
            value={draft}
            maxLength={REPLY_MAX_LENGTH}
            readOnly={posting}
            autoComplete="off"
            aria-describedby={hintId}
            onChange={(e) => setDraft(e.target.value)}
            className={`min-w-0 flex-1 rounded-full border border-line-strong bg-panel px-3 py-1 text-fg placeholder:text-muted ${FOCUS}`}
            placeholder="Type a reply"
          />
          <button
            type="submit"
            aria-disabled={!canSend}
            className={`rounded-full border border-accent bg-accent px-3 py-1 font-semibold text-on-accent hover:bg-accent/90 aria-disabled:cursor-not-allowed aria-disabled:border-line-strong aria-disabled:bg-transparent aria-disabled:text-muted ${FOCUS}`}
          >
            {posting ? "Sending…" : "Send"}
          </button>
        </div>
        <p id={hintId} className="text-xs text-muted">
          {REPLY_HINT}
        </p>
        <div role="group" aria-label="Quick replies" className="flex flex-wrap gap-1.5">
          {quickReplies(household.lang).map((q) => (
            <button
              key={q.body}
              type="button"
              aria-label={q.label}
              aria-disabled={posting}
              onClick={() => send(q.body, false)}
              className={`rounded-full border border-line-strong px-2.5 py-0.5 font-mono text-xs font-medium text-fg hover:bg-line aria-disabled:cursor-not-allowed aria-disabled:text-muted ${FOCUS}`}
            >
              {q.body}
            </button>
          ))}
        </div>
        <p aria-live="polite" className="sr-only">
          {posting ? "Sending reply" : ""}
        </p>
        {error && (
          <p role="alert" className="rounded-card border border-line border-l-2 border-l-help bg-help/10 px-2 py-1 text-xs">
            {error}
          </p>
        )}
      </form>
    </div>
  );
}

function Thread({ household }: { household: RunHousehold }) {
  const logRef = useRef<HTMLDivElement>(null);
  const count = household.messages.length;

  // Keep the newest message in view.
  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [count, household.id]);

  return (
    <div
      ref={logRef}
      role="log"
      aria-live="polite"
      aria-label={threadLabel(household)}
      tabIndex={0}
      className={`max-h-80 overflow-y-auto rounded-md ${FOCUS}`}
    >
      {count === 0 ? (
        <p className="text-muted">No messages yet.</p>
      ) : (
        <ol className="flex flex-col gap-2">
          {household.messages.map((m, i) => (
            <MessageItem key={`${i}-${m.direction}-${m.at}`} message={m} lang={household.lang} />
          ))}
        </ol>
      )}
    </div>
  );
}

function MessageItem({ message: m, lang }: { message: RunMessage; lang: string }) {
  const out = m.direction === "out";
  const source = messageSourceLabel(m);
  const classText = messageClassText(m);
  return (
    <li className={`flex max-w-[85%] flex-col gap-0.5 ${out ? "self-start items-start" : "self-end items-end"}`}>
      <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
        <span className="font-semibold">{out ? `${SENDER_NAME}: ${messageKindLabel(m)}` : "Household reply"}</span>
        {source && <span className="rounded border border-simulated/40 px-1 text-simulated">{source}</span>}
        <span className="tabular-nums">{messageTimeText(m.at)}</span>
      </p>
      {/* Message body only: no sender name or "Simulated" label inside the bubble (Req 14.8). */}
      <p
        lang={out ? lang : undefined}
        className={`whitespace-pre-wrap break-words rounded-lg px-2.5 py-1.5 ${
          out ? "rounded-tl-sm border border-line bg-panel text-fg" : "rounded-tr-sm bg-text-channel/14 text-fg"
        }`}
      >
        {maskPhonesInText(m.text)}
      </p>
      {classText && <p className="text-xs text-muted">{classText}</p>}
    </li>
  );
}
