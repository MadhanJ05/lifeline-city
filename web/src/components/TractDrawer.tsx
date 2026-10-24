import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { sendCheckins, useLatest, useRunPolling, useTractDetail } from "../api";
import { SEND_EXISTS_NOTE, SEND_WAIT_NOTE, runMatches, sendErrorText } from "../checkin";
import { briefingBadge, briefingNote } from "../drawer";
import { formatHour } from "../format";
import { shortTractName } from "../mapValues";
import { channelLabel, channelNote, formatPriority } from "../queue";
import { DRAWER_TABS, DRAWER_TAB_LABEL, nextTab, shownTab, type DrawerTab } from "../tabs";
import type { Briefing, CapeTimeline, Channel, Claim, Geoid, HourKey, Run, TelecomRule, TractDetail } from "../types";
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

const FOCUS = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";
const LABEL = "text-[11px] font-medium uppercase tracking-[0.06em] text-faint";

/** Short pill text per channel; the full channel label stays in the Reach tab. */
const CHANNEL_PILL: Record<Channel, { text: string; className: string }> = {
  sms: { text: "Text check-in", className: "bg-text-channel/12 text-text-channel" },
  door_knock: { text: "Door-knock", className: "bg-knock/12 text-knock" },
};

const RULE_TAG: Record<TelecomRule, string | null> = {
  none: null,
  modeled: "Modeled",
  observed: "Observed",
  both: "Modeled and Observed",
};

/** One muted line under the stats, e.g. "Phones likely degraded · Modeled". */
function channelNoteLine(d: Pick<TractDetail, "channel" | "telecom_rule">): string {
  const note = channelNote(d.channel);
  const tag = RULE_TAG[d.telecom_rule] ?? null;
  if (!note) return `${channelLabel(d.channel)} · Phones working`;
  return tag ? `${note} · ${tag}` : note;
}

/** Non-modal side panel for the selected tract-hour (Req 10). On open, focus moves to the heading;
 *  Esc or the Close button closes it and focus returns to the control that opened it (Req 29.1).
 *  Render it only while a tract is selected, so mount = open and unmount = close. */
export function TractDrawer({ geoid, hour, town, name, scoring, onClose, resetVersion = 0, reach }: Props) {
  const titleId = useId();
  const tabsId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const tabRefs = useRef<Partial<Record<DrawerTab, HTMLButtonElement | null>>>({});
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

  // The user's tab pick holds across hour changes for the same tract; a new tract starts from the default.
  const [picked, setPicked] = useState<{ geoid: Geoid; tab: DrawerTab } | null>(null);
  const tab = shownTab(picked && picked.geoid === geoid ? picked.tab : null, run !== null);
  const pickTab = (t: DrawerTab) => setPicked({ geoid, tab: t });
  const onTabKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const next = nextTab(tab, e.key);
    if (!next) return;
    e.preventDefault();
    e.stopPropagation();
    pickTab(next);
    tabRefs.current[next]?.focus();
  };

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

  const tabId = (t: DrawerTab) => `${tabsId}-tab-${t}`;
  const panelId = (t: DrawerTab) => `${tabsId}-panel-${t}`;
  const pill = current ? CHANNEL_PILL[current.channel] : null;

  return (
    <aside
      role="dialog"
      aria-modal="false"
      aria-labelledby={titleId}
      aria-busy={loading}
      onKeyDown={onKeyDown}
      className="lifeline-drawer flex h-full flex-col gap-3 overflow-y-auto rounded-panel border border-line bg-panel-solid p-4 text-[13px] text-fg shadow-panel"
    >
      <header className="flex flex-col gap-3">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <h2
              id={titleId}
              ref={headingRef}
              tabIndex={-1}
              className={`text-[17px] font-semibold leading-tight ${FOCUS}`}
            >
              {town} {shortTractName(name)}
            </h2>
            <p className="mt-0.5 font-mono text-xs text-muted">{formatHour(shownHour)}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close tract details"
            className={`grid h-8 w-8 place-items-center rounded-card border border-line text-muted hover:bg-line hover:text-fg ${FOCUS}`}
          >
            <svg aria-hidden="true" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
              <path d="M4 4l8 8M12 4l-8 8" />
            </svg>
          </button>
        </div>

        {current && pill && (
          <>
            <dl className="grid grid-cols-3 gap-2">
              <div className="rounded-card border border-line px-3 py-2">
                <dt className={LABEL}>Rank</dt>
                <dd className="font-mono text-[22px] font-medium leading-tight tabular-nums">
                  {current.rank !== null ? (
                    current.rank
                  ) : (
                    <>
                      <span aria-hidden="true">—</span>
                      <span className="sr-only">Not in the top 10 at this hour</span>
                    </>
                  )}
                </dd>
              </div>
              <div className="rounded-card border border-line px-3 py-2">
                <dt className={LABEL}>Priority</dt>
                <dd className="font-mono text-[22px] font-medium leading-tight tabular-nums">
                  {formatPriority(current.priority)}
                </dd>
              </div>
              <div className="rounded-card border border-line px-3 py-2">
                <dt className={LABEL}>Channel</dt>
                <dd className="mt-1">
                  <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-semibold ${pill.className}`}>
                    {pill.text}
                  </span>
                </dd>
              </div>
            </dl>
            <p className="truncate text-xs text-muted">{channelNoteLine(current)}</p>
          </>
        )}
      </header>

      <p role="status" className="sr-only">
        {loading ? `Loading ${town} ${shortTractName(name)} at ${formatHour(hour)}` : ""}
      </p>
      {updating && <p className="text-xs text-muted">Updating to {formatHour(hour)}…</p>}

      {error && (
        <div role="alert" className="rounded-card border border-line border-l-2 border-l-help bg-help/10 p-2 text-sm">
          <p>Could not load this tract-hour: {error.message}</p>
          <button
            type="button"
            onClick={reload}
            className={`mt-1 rounded-card border border-line-strong px-2 py-0.5 hover:bg-line ${FOCUS}`}
          >
            Retry
          </button>
        </div>
      )}

      {!current && loading && <p className="text-sm text-muted">Loading tract details…</p>}

      {current && (
        <>
          <div
            role="tablist"
            aria-label="Tract details"
            onKeyDown={onTabKeyDown}
            className="flex gap-1 rounded-full border border-line p-1"
          >
            {DRAWER_TABS.map((t) => {
              const selected = t === tab;
              return (
                <button
                  key={t}
                  ref={(el) => {
                    tabRefs.current[t] = el;
                  }}
                  id={tabId(t)}
                  type="button"
                  role="tab"
                  aria-selected={selected}
                  aria-controls={panelId(t)}
                  tabIndex={selected ? 0 : -1}
                  onClick={() => pickTab(t)}
                  className={`flex-1 rounded-full border px-3 py-1 text-xs font-medium ${FOCUS} ${
                    selected ? "border-line-strong bg-bg text-fg" : "border-transparent text-muted hover:text-fg"
                  }`}
                >
                  {DRAWER_TAB_LABEL[t]}
                </button>
              );
            })}
          </div>

          <div
            role="tabpanel"
            id={panelId(tab)}
            aria-labelledby={tabId(tab)}
            tabIndex={0}
            className={`flex flex-col gap-3 rounded-card ${FOCUS} ${updating ? "opacity-70" : ""}`}
          >
            {tab === "briefing" && <BriefingSection briefing={briefing} />}
            {tab === "why" && <WhyFlagged detail={current} scoring={scoring} />}
            {tab === "reach" && (
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
            )}
          </div>
        </>
      )}

      {!current && !loading && !error && <p className="text-sm text-muted">Loading reach options…</p>}
    </aside>
  );
}

const BADGE_CLASS = {
  Verified: "bg-ok/12 text-ok",
  Template: "border border-line-strong text-muted",
} as const;

/** Compact value for a claim: shares as percent, small fractions with 3 decimals, counts as integers. */
function claimValueText(c: Claim): string {
  const v = c.value;
  if (!Number.isFinite(v)) return "n/a";
  if (/pct|share|out_pct/.test(c.field) && v >= 0 && v <= 1) return `${Math.round(v * 100)}%`;
  if (Number.isInteger(v)) return v.toLocaleString("en-US");
  if (Math.abs(v) < 1) return v.toFixed(3);
  return v.toFixed(1);
}

function BriefingSection({ briefing }: { briefing: Briefing | null }) {
  const headingId = useId();
  if (!briefing) {
    return (
      <section aria-labelledby={headingId} className="flex flex-col gap-1">
        <h3 id={headingId} className={LABEL}>
          Briefing
        </h3>
        <p className="text-sm text-muted">No briefing cached for this tract-hour.</p>
      </section>
    );
  }
  const badge = briefingBadge(briefing);
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id={headingId} className={LABEL}>
          Briefing
        </h3>
        <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${BADGE_CLASS[badge]}`}>{badge}</span>
      </div>
      <p className="text-xs text-muted">{briefingNote(briefing)}</p>
      <p className="text-[15px] font-semibold leading-snug">{briefing.headline}</p>
      <ul className="flex flex-col divide-y divide-line rounded-card border border-line">
        {briefing.claims.map((c) => (
          <li key={`${c.field}:${c.text}`} className="flex items-start gap-3 px-3 py-2">
            <div className="min-w-0 flex-1">
              <p>{c.text}</p>
              <p className="text-[11px] text-faint">field: {c.field}</p>
            </div>
            <span className="font-mono text-sm tabular-nums text-fg">{claimValueText(c)}</span>
          </li>
        ))}
      </ul>
      <div className="rounded-r-card border-l-2 border-accent bg-line px-3 py-2">
        <p className={LABEL}>Recommended action</p>
        <p className="mt-0.5">{briefing.action}</p>
      </div>
    </section>
  );
}
