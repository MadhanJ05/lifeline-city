import { useId, useMemo } from "react";
import { formatHour } from "../format";
import { channelLabel, channelNote, formatPriority, rowChips, tractNameOf, tractNames } from "../queue";
import type { CapeTracts, Channel, Geoid, HourKey, QueueRow } from "../types";

interface Props {
  rows: QueueRow[];
  hour: HourKey;
  tracts: CapeTracts;
  selectedGeoid: Geoid | null;
  onSelectTract: (geoid: Geoid) => void;
}

const BADGE: Record<Channel, string> = {
  sms: "border-sky-300/70 bg-sky-950 text-sky-100",
  door_knock: "border-amber-300/70 bg-amber-950 text-amber-100",
};

/** Ranked Priority_Queue at the selected hour (Req 9.1, 9.2). Each row is a native button, so it is
 *  reachable by Tab and opens with Enter or Space (Req 29.1). Channel and priority are text. */
export function Queue({ rows, hour, tracts, selectedGeoid, onSelectTract }: Props) {
  const headingId = useId();
  const names = useMemo(() => tractNames(tracts), [tracts]);

  return (
    <section aria-labelledby={headingId} className="flex flex-col rounded-md border border-slate-800 bg-slate-900/70 p-2">
      <h2 id={headingId} className="px-1 text-sm font-semibold text-slate-200">
        Priority queue at {formatHour(hour)}
      </h2>
      <p className="px-1 pb-1 text-xs text-slate-400">Highest priority first. Select a row to open the tract.</p>
      {rows.length === 0 ? (
        <p className="px-1 py-2 text-sm text-slate-300">No ranked tracts at this hour.</p>
      ) : (
        <ol aria-labelledby={headingId} className="flex flex-col gap-1.5">
          {rows.map((r) => {
            const selected = r.geoid === selectedGeoid;
            const tract = tractNameOf(names, r.geoid);
            const note = channelNote(r.channel);
            return (
              <li key={r.geoid}>
                <button
                  type="button"
                  aria-current={selected ? "true" : undefined}
                  onClick={() => onSelectTract(r.geoid)}
                  className={`flex w-full flex-col gap-1 rounded-md border px-2.5 py-2 text-left text-sm text-slate-100 hover:bg-slate-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-300 ${
                    selected ? "border-white/80 bg-slate-800" : "border-slate-700 bg-slate-900"
                  }`}
                >
                  <span className="flex items-baseline gap-2">
                    <span className="w-6 shrink-0 tabular-nums text-slate-400">
                      <span className="sr-only">Rank </span>
                      {r.rank}
                    </span>
                    <span className="flex-1">
                      <span className="font-semibold">{r.town}</span>{" "}
                      <span className="text-slate-300">{tract}</span>
                    </span>
                    <span className="font-semibold tabular-nums">Priority {formatPriority(r.priority)}</span>
                  </span>
                  <span className="flex flex-wrap items-center gap-1.5 pl-8">
                    <span className={`rounded border px-1.5 py-0.5 text-xs font-semibold ${BADGE[r.channel]}`}>
                      {channelLabel(r.channel)}
                    </span>
                    {note && <span className="text-xs text-amber-100">{note}</span>}
                  </span>
                  <span className="flex flex-wrap gap-1.5 pl-8">
                    {rowChips(r).map((c) => (
                      <span
                        key={c.field}
                        className="rounded-full border border-slate-600 bg-slate-800 px-2 py-0.5 text-xs text-slate-100"
                      >
                        {c.text}
                      </span>
                    ))}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
