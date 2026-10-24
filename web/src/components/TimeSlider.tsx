import { useId } from "react";
import { formatHour } from "../format";
import { clampHourIdx } from "../mapValues";
import type { HourKey } from "../types";

interface Props {
  hours: HourKey[];
  keyHours: HourKey[];
  hourIdx: number;
  onChange: (idx: number) => void;
}

const BTN =
  "rounded-md border border-slate-600 bg-slate-800 px-2.5 py-1 text-sm text-slate-100 hover:bg-slate-700 " +
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-300 disabled:opacity-50";

/** Hourly replay control: range input over every hour of the demo window plus key-hour shortcuts
 *  (Req 8.2, 29.1). The arrow keys step by one hour on the native range input. */
export function TimeSlider({ hours, keyHours, hourIdx, onChange }: Props) {
  const id = useId();
  const n = hours.length;
  const hour = hours[hourIdx] ?? "";
  const set = (i: number) => onChange(clampHourIdx(i, n));
  const local = `${formatHour(hour)} (local time)`;

  return (
    <section aria-label="Time slider" className="rounded-md border border-slate-800 bg-slate-900/70 px-3 py-2">
      <div className="flex flex-wrap items-center gap-3">
        <label htmlFor={id} className="text-sm font-semibold text-slate-200">
          Hour
        </label>
        <button type="button" className={BTN} aria-label="Previous hour" disabled={hourIdx <= 0}
                onClick={() => set(hourIdx - 1)}>
          <span aria-hidden="true">‹</span>
        </button>
        <input
          id={id}
          type="range"
          min={0}
          max={Math.max(0, n - 1)}
          step={1}
          value={hourIdx}
          aria-valuetext={local}
          onChange={(e) => set(Number(e.currentTarget.value))}
          className="min-w-48 flex-1 accent-sky-400 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-sky-300"
        />
        <button type="button" className={BTN} aria-label="Next hour" disabled={hourIdx >= n - 1}
                onClick={() => set(hourIdx + 1)}>
          <span aria-hidden="true">›</span>
        </button>
        <output htmlFor={id} className="min-w-44 text-sm font-semibold tabular-nums text-slate-100">
          {formatHour(hour)} <span className="font-normal text-slate-400">local time</span>
          <span className="ml-2 font-normal text-slate-400">
            ({hourIdx + 1} of {n})
          </span>
        </output>
      </div>
      <div role="group" aria-label="Key demo hours" className="mt-2 flex flex-wrap items-center gap-1.5">
        <span className="text-xs text-slate-400" aria-hidden="true">
          Key hours:
        </span>
        {keyHours.map((k) => {
          const i = hours.indexOf(k);
          if (i < 0) return null;
          const current = i === hourIdx;
          return (
            <button
              key={k}
              type="button"
              aria-pressed={current}
              onClick={() => set(i)}
              className={`${BTN} text-xs ${current ? "border-sky-300 bg-sky-900 text-white" : ""}`}
            >
              {formatHour(k)}
            </button>
          );
        })}
      </div>
    </section>
  );
}
