import { useId, type CSSProperties } from "react";
import { formatHour } from "../format";
import { clampHourIdx } from "../mapValues";
import { barHourLabel, shortHourLabel, sparklinePath, tickPercent } from "../timebar";
import type { HourKey } from "../types";
import "../styles/timebar.css";

interface Props {
  hours: HourKey[];
  keyHours: HourKey[];
  hourIdx: number;
  onChange: (idx: number) => void;
  /** Cape customers out per hour (timeline.cape_total). Optional: no sparkline when absent. */
  capeTotal?: number[];
}

const ICON_BTN =
  "grid h-8 w-8 shrink-0 place-items-center rounded-card border border-line-strong text-fg hover:bg-line " +
  "transition-colors duration-150 ease-out motion-reduce:transition-none " +
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-40";

/** Half the 14px thumb: the sparkline and ticks are inset by this so x positions match the thumb. */
const INSET = 7;
const SPARK_W = 1000;
const SPARK_H = 32;

/** CSS left for a fraction p of the thumb travel. */
const atPct = (p: number) => `calc(${INSET}px + (100% - ${2 * INSET}px) * ${p})`;

/** Hourly replay control: prev/next, the hour readout, a cape_total sparkline behind a custom range
 *  input, and key-hour ticks (Req 8.2, 8.3, 29.1). Arrow keys step by one hour on the native range. */
export function TimeSlider({ hours, keyHours, hourIdx, onChange, capeTotal }: Props) {
  const id = useId();
  const n = hours.length;
  const hour = hours[hourIdx] ?? "";
  const set = (i: number) => onChange(clampHourIdx(i, n));
  const local = `${formatHour(hour)} (local time)`;
  const fill = `${tickPercent(hourIdx, n) * 100}%`;
  const spark = capeTotal && capeTotal.length > 0 ? sparklinePath(capeTotal, SPARK_W, SPARK_H) : null;

  return (
    <section aria-label="Time slider" className="flex h-full w-full items-center gap-4">
      <div className="flex shrink-0 items-center gap-2">
        <button type="button" className={ICON_BTN} aria-label="Previous hour" disabled={hourIdx <= 0}
                onClick={() => set(hourIdx - 1)}>
          <span aria-hidden="true">‹</span>
        </button>
        <button type="button" className={ICON_BTN} aria-label="Next hour" disabled={hourIdx >= n - 1}
                onClick={() => set(hourIdx + 1)}>
          <span aria-hidden="true">›</span>
        </button>
        <output htmlFor={id} aria-live="polite"
                className="ml-2 min-w-[13.5rem] whitespace-nowrap font-mono text-[22px] font-medium tabular-nums text-fg">
          {barHourLabel(hour)}
          <span className="sr-only"> local time, hour {hourIdx + 1} of {n}</span>
        </output>
      </div>

      <div className="timebar-track relative min-w-0 flex-1">
        <label htmlFor={id} className="sr-only">Hour</label>
        <div className="relative h-8">
          {spark && (
            <svg aria-hidden="true" focusable="false" viewBox={`0 0 ${SPARK_W} ${SPARK_H}`} preserveAspectRatio="none"
                 className="pointer-events-none absolute inset-y-0 h-8"
                 style={{ left: INSET, width: `calc(100% - ${2 * INSET}px)` }}>
              <title>Cape customers without power</title>
              <path d={spark.area} fill="var(--color-accent)" fillOpacity={0.2} stroke="none" />
              <path d={spark.line} fill="none" stroke="var(--color-accent)" strokeWidth={1.5}
                    vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
            </svg>
          )}
          {spark && (
            <span aria-hidden="true"
                  className="timebar-caption pointer-events-none absolute right-2 top-0 text-[11px] text-muted">
              Cape customers without power
            </span>
          )}
          <input
            id={id}
            type="range"
            min={0}
            max={Math.max(0, n - 1)}
            step={1}
            value={hourIdx}
            aria-valuetext={local}
            onChange={(e) => set(Number(e.currentTarget.value))}
            className="timebar-range absolute inset-x-0 -bottom-[6px]"
            style={{ "--fill": fill } as CSSProperties}
          />
        </div>

        <div role="group" aria-label="Key demo hours" className="relative mt-2.5 h-5">
          {keyHours.map((k) => {
            const i = hours.indexOf(k);
            if (i < 0) return null;
            const current = i === hourIdx;
            return (
              <button
                key={k}
                type="button"
                aria-pressed={current}
                title={`${formatHour(k)} (local time)`}
                onClick={() => set(i)}
                style={{ left: atPct(tickPercent(i, n)) }}
                className={
                  "absolute top-0 -translate-x-1/2 whitespace-nowrap rounded-full px-1.5 py-0.5 text-[11px] font-medium " +
                  "hover:bg-line transition-colors duration-150 ease-out motion-reduce:transition-none " +
                  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent " +
                  (current ? "text-accent" : "text-muted")
                }
              >
                <span aria-hidden="true" className={`mx-auto mb-0.5 block h-1 w-px ${current ? "bg-accent" : "bg-line-strong"}`} />
                {shortHourLabel(k)}
              </button>
            );
          })}
        </div>
      </div>
    </section>
  );
}
