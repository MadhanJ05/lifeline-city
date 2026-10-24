import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { sendCheckins, useLatest, useRunPolling, useTractDetail } from "../api";
import { SEND_EXISTS_NOTE, SEND_WAIT_NOTE, runMatches, sendErrorText } from "../checkin";
import { briefingBadge, briefingNote } from "../drawer";
import { formatHour } from "../format";
import { shortTractName } from "../mapValues";
import { channelLabel, channelNote, formatPriority } from "../queue";
import type { Briefing, CapeTimeline, Geoid, HourKey, Run, TractDetail } from "../types";
import { CheckInStatus } from "./CheckInStatus";
import { ReachPanel } from "./ReachPanel";
import { WhyFlagged } from "./WhyFlagged";

/** What the drawer hands to plug-ins below the check-in status (the PhoneSimulator, task 13.5). */
export interface RunContext {
  detail: TractDetail;
  /** The run for the tract-hour on screen, or null. */
  run: Run | null;
  /** Hand back a run returned by the API (e.g. POST /api/simulator/reply); polling restarts from it. */
  onRunUpdate: (run: Run) => void;
}

interface Props {
  geoid: Geoid;
  hour: HourKey;
  /** From the static tract file, so the title is right before the detail arrives. */
  town: string;
  name: string;
  scoring: Pick<CapeTimeline, "hours_dark_cap" | "telecom_model">;
  onClose: () => void;
  /** Incremented by the App after a demo reset; the drawer refetches its tract-hour (Req 21.2). */
  resetVersion?: number;
  /** Rendered below the check-in status with the run and an update callback (PhoneSimulator, task 13.5). */
  reach?: (ctx: RunContext) => ReactNode;
}

/** Non-modal side panel for the selected tract-hour (Req 10). On open, focus moves to the heading;
 *  Esc or the Close button closes it and focus returns to the control that opened it (Req 29.1).
 *  Render it only while a tract is selected, so mount = open and unmount = close. */
export function TractDrawer({ geoid, hour, town, name, scoring, onClose, resetVersion = 0, reach }: Props) {
  const titleId = useId();
  const reachId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const { detail, content, loading, error, reload } = useTractDetail(geoid, hour, resetVersion);

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    headingRef.current?.focus();
    return () => {
      if (opener && opener !== document.body && opener.isConnected) opener.focus();
    };
  }, []);

  const onKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    if (e.key === "Escape" && !e.defaultPrevented) {
      e.preventDefault();
      onClose();
    }
  };

  // Previous data stays visible during an hour change; another tract's data is never shown.
  const current: TractDetail | null = detail && detail.geoid === geoid ? detail : null;
  const briefing = current && content && content.geoid === geoid ? content.briefing : null;
  const shownHour = current?.hour ?? hour;
  const updating = loading && current !== null && current.hour !== hour;

  // Check-in run for the selected tract-hour. Keyed by tract, hour and reset version: any change clears
  // the held run, and a TractDetail that already carries a run (hour switched back) resumes polling it.
  const runKey = `${geoid}|${hour}|${resetVersion}`;
  const detailForHour = current && current.hour === hour ? current : null;
  const { run: polled, error: pollError, setRun } = useRunPolling(detailForHour?.run ?? null, runKey);
  const run = current && runMatches(polled, current.geoid, current.hour) ? polled : null;
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<{ key: string; text: string } | null>(null);
  const latestKey = useLatest(runKey);

  const onSend = useCallback(() => {
    const sentKey = runKey;
    setSending(true);
    setSendError(null);
    sendCheckins(geoid, hour)
      .then((r) => {
        // Ignore a response for a tract-hour that is no longer on screen.
        if (latestKey.current === sentKey && runMatches(r, geoid, hour)) setRun(r);
      })
      .catch((e: unknown) => {
        if (latestKey.current === sentKey) setSendError({ key: sentKey, text: sendErrorText(e) });
      })
      .finally(() => setSending(false));
  }, [geoid, hour, runKey, latestKey, setRun]);

  // Only sms tract-hours get a send handler; door_knock never sends (Req 12.6, 15.6).
  const canSend = current?.channel === "sms";
  const sendNote = !detailForHour ? SEND_WAIT_NOTE : run ? SEND_EXISTS_NOTE : undefined;
  const shownSendError = sendError && sendError.key === runKey ? sendError.text : null;

  return (
    <aside
      role="dialog"
      aria-modal="false"
      aria-labelledby={titleId}
      aria-busy={loading}
      onKeyDown={onKeyDown}
      className="flex flex-col gap-3 rounded-md border border-slate-700 bg-slate-950 p-3 text-slate-100 shadow-xl xl:sticky xl:top-2 xl:max-h-[calc(100vh-1rem)] xl:w-[28rem] xl:shrink-0 xl:overflow-y-auto"
    >
      <header className="flex items-start gap-2">
        <div className="flex-1">
          <h2 id={titleId} ref={headingRef} tabIndex={-1} className="text-lg font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-300">
            {town} {shortTractName(name)}
          </h2>
          <p className="text-sm text-slate-300">
            {formatHour(shownHour)}
            {current && (
              <>
                {" · "}
                {current.rank !== null ? `Rank ${current.rank} in the queue` : "Not in the top 10 at this hour"}
                {" · "}
                <span className="tabular-nums">Priority {formatPriority(current.priority)}</span>
              </>
            )}
          </p>
          {current && (
            <p className="mt-1 flex flex-wrap items-center gap-1.5 text-xs">
              <span className="rounded border border-slate-500 bg-slate-800 px-1.5 py-0.5 font-semibold">
                {channelLabel(current.channel)}
              </span>
              {channelNote(current.channel) && <span className="text-amber-100">{channelNote(current.channel)}</span>}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close tract details"
          className="rounded-md border border-slate-600 bg-slate-800 px-2 py-1 text-sm text-slate-100 hover:bg-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-300"
        >
          <span aria-hidden="true">✕</span>
        </button>
      </header>

      <p role="status" className="sr-only">
        {loading ? `Loading ${town} ${shortTractName(name)} at ${formatHour(hour)}` : ""}
      </p>
      {updating && <p className="text-xs text-slate-300">Updating to {formatHour(hour)}…</p>}

      {error && (
        <div role="alert" className="rounded-md border border-rose-400/70 bg-rose-950/60 p-2 text-sm">
          <p>Could not load this tract-hour: {error.message}</p>
          <button
            type="button"
            onClick={reload}
            className="mt-1 rounded border border-slate-500 bg-slate-800 px-2 py-0.5 hover:bg-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-300"
          >
            Retry
          </button>
        </div>
      )}

      {!current && loading && <p className="text-sm text-slate-300">Loading tract details…</p>}

      {current && (
        <div className={`flex flex-col gap-4 ${updating ? "opacity-70" : ""}`}>
          <BriefingSection briefing={briefing} />
          <WhyFlagged detail={current} scoring={scoring} />
        </div>
      )}

      <section aria-labelledby={reachId} className="flex flex-col gap-2 border-t border-slate-800 pt-3">
        <h3 id={reachId} className="text-base font-semibold">
          Reach
        </h3>
        {current ? (
          <>
            <ReachPanel
              detail={current}
              content={content}
              telecomModel={scoring.telecom_model}
              onSend={canSend ? onSend : undefined}
              sending={sending}
              sendNote={canSend ? sendNote : undefined}
              sendError={shownSendError}
            />
            <CheckInStatus channel={current.channel} households={current.households} run={run} pollError={pollError} />
            {reach?.({ detail: current, run, onRunUpdate: setRun })}
          </>
        ) : (
          !error && <p className="text-sm text-slate-300">Loading reach options…</p>
        )}
      </section>
    </aside>
  );
}

const BADGE_CLASS = {
  Verified: "border-emerald-300/70 bg-emerald-950 text-emerald-100",
  Template: "border-slate-400/70 bg-slate-800 text-slate-100",
} as const;

function BriefingSection({ briefing }: { briefing: Briefing | null }) {
  const headingId = useId();
  if (!briefing) {
    return (
      <section aria-labelledby={headingId}>
        <h3 id={headingId} className="text-base font-semibold">
          Briefing
        </h3>
        <p className="text-sm text-slate-300">No briefing cached for this tract-hour.</p>
      </section>
    );
  }
  const badge = briefingBadge(briefing);
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id={headingId} className="text-base font-semibold">
          Briefing
        </h3>
        <span className={`rounded border px-1.5 py-0.5 text-xs font-semibold ${BADGE_CLASS[badge]}`}>{badge}</span>
      </div>
      <p className="text-xs text-slate-400">{briefingNote(briefing)}</p>
      <p className="font-semibold">{briefing.headline}</p>
      <ul className="list-disc pl-5 text-sm">
        {briefing.claims.map((c) => (
          <li key={`${c.field}:${c.text}`}>
            {c.text} <span className="text-xs text-slate-400">(field: {c.field})</span>
          </li>
        ))}
      </ul>
      <p className="text-sm">
        <span className="font-semibold">Recommended action:</span> {briefing.action}
      </p>
    </section>
  );
}
