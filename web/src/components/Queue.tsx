import { useId, useMemo } from "react";
import { formatHour } from "../format";
import { channelLabel, channelNote, formatPriority, rowReason, tractNameOf, tractNames } from "../queue";
import type { CapeTracts, Channel, Geoid, HourKey, QueueRow } from "../types";

interface Props {
  rows: QueueRow[];
  hour: HourKey;
  tracts: CapeTracts;
  selectedGeoid: Geoid | null;
  onSelectTract: (geoid: Geoid) => void;
}

const PILL: Record<Channel, string> = {
  sms: "bg-text-channel/12 text-text-channel",
  door_knock: "bg-knock/12 text-knock",
};
const DOT: Record<Channel, string> = { sms: "bg-text-channel", door_knock: "bg-knock" };

/** Ranked Priority_Queue at the selected hour (Req 9.1, 9.2). Each row is a native button, so it is
 *  reachable by Tab and opens with Enter or Space (Req 29.1). Channel and priority are text. */
export function Queue({ rows, hour, tracts, selectedGeoid, onSelectTract }: Props) {
  const headingId = useId();
  const names = useMemo(() => tractNames(tracts), [tracts]);
  const maxPriority = Math.max(0, ...rows.map((r) => r.priority));
  const knocks = rows.filter((r) => r.channel === "door_knock").length;
  const texts = rows.filter((r) => r.channel === "sms").length;

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-2">
      <header className="flex flex-col gap-1">
        <h2 id={headingId} className="text-[11px] font-medium uppercase tracking-[0.06em] text-faint">
          Priority list <span className="sr-only">at {formatHour(hour)}</span>
        </h2>
        <p className="text-xs text-muted">Neighborhoods most likely to need help right now</p>
        <p aria-hidden="true" className="font-mono text-[15px] font-medium text-fg">
          {formatHour(hour)}
        </p>
        <p className="flex items-center gap-3 text-xs text-muted">
          <span className="flex items-center gap-1.5">
            <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${DOT.door_knock}`} />
            {knocks} door-knock
          </span>
          <span aria-hidden="true">·</span>
          <span className="flex items-center gap-1.5">
            <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${DOT.sms}`} />
            {texts} text
          </span>
        </p>
        <p className="sr-only">Highest priority first. Select a row to open the tract.</p>
      </header>
      {rows.length === 0 ? (
        <p className="py-2 text-muted">No ranked tracts at this hour.</p>
      ) : (
        <ol aria-labelledby={headingId} className="flex flex-col gap-1">
          {rows.map((r) => {
            const selected = r.geoid === selectedGeoid;
            const tract = tractNameOf(names, r.geoid);
            const note = channelNote(r.channel);
            const width = maxPriority > 0 ? (r.priority / maxPriority) * 100 : 0;
            const reason = rowReason(r);
            return (
              <li key={r.geoid}>
                <button
                  type="button"
                  aria-current={selected ? "true" : undefined}
                  onClick={() => onSelectTract(r.geoid)}
                  className={`grid w-full grid-cols-[1.25rem_minmax(0,1fr)_auto] items-start gap-x-2 gap-y-1 rounded-card border p-2.5 text-left text-fg transition-colors duration-150 ease-out hover:bg-line ${
                    selected ? "border-line-strong bg-line shadow-[inset_2px_0_0_var(--accent)]" : "border-transparent"
                  }`}
                >
                  <span className="font-mono text-faint tabular-nums">
                    <span className="sr-only">Rank </span>
                    {r.rank}
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate">
                      <span className="text-[13px] font-semibold">{r.town}</span>{" "}
                      <span className="text-muted">{tract}</span>
                    </span>
                  </span>
                  <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${PILL[r.channel]}`}>
                    {channelLabel(r.channel)}
                    {note && <span className="sr-only">. {note}</span>}
                  </span>
                  <span className="col-start-2 col-end-4 flex items-center gap-2">
                    <span aria-hidden="true" className="h-[3px] flex-1 overflow-hidden rounded-full bg-line">
                      <span className="block h-full rounded-full bg-accent" style={{ width: `${width}%` }} />
                    </span>
                    <span className="font-mono text-xs tabular-nums text-fg">
                      <span className="sr-only">Priority </span>
                      {formatPriority(r.priority)}
                    </span>
                  </span>
                  {reason && (
                    <span title={reason} className="col-start-2 col-end-4 truncate text-xs text-muted">
                      {reason}
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
