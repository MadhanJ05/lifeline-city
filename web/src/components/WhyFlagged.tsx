import { useId } from "react";
import {
  EMPOWER_MASKING_NOTE,
  affectsText,
  componentRows,
  eventChannelNote,
  eventWindowText,
  fmt3,
  fmtWeight,
  humanize,
  missingIndicatorNames,
  needRows,
  safeUrl,
  telecomRuleView,
} from "../drawer";
import type { ActiveTelecomEvent, CapeTimeline, Citation, TractDetail } from "../types";

interface Props {
  detail: TractDetail;
  scoring: Pick<CapeTimeline, "hours_dark_cap" | "telecom_model">;
}

const LABEL = "text-[11px] font-medium uppercase tracking-[0.06em] text-faint";
const TH = "px-1.5 pb-1 text-left text-[11px] font-medium uppercase tracking-[0.06em] text-faint";
const TD = "px-1.5 py-1.5 align-top";
const FAINT = "text-[11px] text-faint";

/** Thin bar for a value in [0, 1]; decorative, the value is always shown as text next to it. */
function Bar({ value, tone }: { value: number | null | undefined; tone: "need" | "lifelines" }) {
  const w = typeof value === "number" && Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;
  const fill = tone === "need" ? "bg-[#A985F0]" : "bg-accent";
  return (
    <span aria-hidden="true" className="mt-1 block h-[3px] w-full overflow-hidden rounded-full bg-line-strong">
      <span className={`block h-full rounded-full ${fill}`} style={{ width: `${w * 100}%` }} />
    </span>
  );
}

/** Every scoring input for the tract-hour as text (Req 10.1, 10.2, 10.3, 10.5, 25.3, 25.4, 29.4). */
export function WhyFlagged({ detail, scoring }: Props) {
  const headingId = useId();
  const rows = needRows(detail);
  const missing = missingIndicatorNames(detail);
  const comps = componentRows(detail, scoring.hours_dark_cap);
  const telecom = telecomRuleView(detail, scoring.telecom_model);

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4">
      <h3 id={headingId} className={LABEL}>
        Why flagged
      </h3>

      {/* Need */}
      <div className="flex flex-col gap-1">
        <table className="w-full table-fixed text-[13px] text-fg">
          <caption className="pb-2 text-left">
            <span className="flex items-baseline justify-between gap-2">
              <span className="font-semibold">Need</span>
              <span className="font-mono text-[15px] tabular-nums">{fmt3(detail.need_t)}</span>
            </span>
            <span className={`block ${FAINT}`}>Mean of the percentile ranks among Cape tracts</span>
          </caption>
          <thead>
            <tr>
              <th scope="col" className={`${TH} w-[55%]`}>Indicator</th>
              <th scope="col" className={`${TH} text-right`}>Value</th>
              <th scope="col" className={`${TH} text-right`}>Rank</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-t border-line">
                <th scope="row" className={`${TD} text-left font-normal`}>
                  <span className="block">{r.label}</span>
                  <span className={`block ${FAINT}`}>{r.source}</span>
                  <Bar value={r.missing ? null : detail.need[r.id]?.pct} tone="need" />
                </th>
                <td className={`${TD} text-right font-mono tabular-nums ${r.missing ? "text-accent" : ""}`}>{r.raw}</td>
                <td className={`${TD} text-right font-mono tabular-nums ${r.missing ? "text-accent" : ""}`}>{r.rank}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className={FAINT}>
          {missing.length
            ? `Missing indicators: ${missing.join(", ")}. Need averages the indicators that exist.`
            : "No missing indicators."}
        </p>
        {detail.empower_masked && (
          <p className={FAINT}>{EMPOWER_MASKING_NOTE}. The value is shown as reported and is not unmasked.</p>
        )}
      </div>

      {/* Lost lifelines */}
      <div className="flex flex-col gap-1 border-t border-line pt-3">
        <table className="w-full table-fixed text-[13px] text-fg">
          <caption className="pb-2 text-left">
            <span className="flex items-baseline justify-between gap-2">
              <span className="font-semibold">Lost lifelines for {detail.town}</span>
              <span className="font-mono text-[15px] tabular-nums">{fmt3(detail.lifelines)}</span>
            </span>
            <span className={`block ${FAINT}`}>Weight × term = contribution</span>
          </caption>
          <thead>
            <tr>
              <th scope="col" className={`${TH} w-[45%]`}>Component</th>
              <th scope="col" className={`${TH} text-right`}>Weight</th>
              <th scope="col" className={`${TH} text-right`}>Value</th>
              <th scope="col" className={`${TH} text-right`}>Contribution</th>
            </tr>
          </thead>
          <tbody>
            {comps.map((c) => (
              <tr key={c.id} className="border-t border-line">
                <th scope="row" className={`${TD} text-left font-normal`}>
                  <span className="block">{c.label}</span>
                  <Bar value={c.term} tone="lifelines" />
                  {c.id === "hours_dark" && (
                    <span className={`mt-1 block ${FAINT}`}>
                      Term <span className="font-mono">{fmt3(c.term)}</span> (hours ÷ cap, at most 1)
                    </span>
                  )}
                  {c.notes.map((n) => (
                    <span key={n} className={`mt-0.5 block ${FAINT}`}>
                      {n}
                    </span>
                  ))}
                </th>
                <td className={`${TD} text-right font-mono tabular-nums text-muted`}>{fmtWeight(c.weight)}</td>
                <td className={`${TD} text-right font-mono tabular-nums`}>{c.value}</td>
                <td className={`${TD} text-right font-mono tabular-nums`}>{fmt3(c.contribution)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t border-line-strong">
              <th scope="row" colSpan={3} className={`${TD} text-left font-semibold`}>
                Lost lifelines (sum)
              </th>
              <td className={`${TD} text-right font-mono font-semibold tabular-nums`}>{fmt3(detail.lifelines)}</td>
            </tr>
            <tr>
              <th scope="row" colSpan={3} className={`${TD} text-left font-semibold`}>
                Priority = Need <span className="font-mono">{fmt3(detail.need_t)}</span> × lost lifelines{" "}
                <span className="font-mono">{fmt3(detail.lifelines)}</span>
              </th>
              <td className={`${TD} text-right font-mono font-semibold tabular-nums text-accent`}>{fmt3(detail.priority)}</td>
            </tr>
          </tfoot>
        </table>
      </div>

      {/* Telecom rule */}
      <div className="rounded-card border border-line p-3">
        <h4 className="font-semibold text-fg">{telecom.headline}</h4>
        <p className="mt-0.5 text-xs text-muted">{telecom.rule}</p>
        {telecom.label && <p className={`mt-1 ${FAINT}`}>{telecom.label}</p>}
        {telecom.citations.length > 0 && (
          <ul className="mt-1 flex flex-col gap-0.5 text-xs text-muted">
            {telecom.citations.map((c) => (
              <li key={c.event_id}>
                Observed: {humanize(c.system)}. Source: <SourceLink c={c} />
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Active observed telecom events */}
      <ActiveEvents events={detail.active_events} town={detail.town} />

      {/* Provenance */}
      <div className="flex flex-col gap-0.5">
        <h4 className={LABEL}>Sources for {detail.town}</h4>
        <ul className="flex flex-col gap-0.5">
          <li className={FAINT}>Outage share and hours dark: {detail.out_pct_label}</li>
          {detail.customers_label && <li className={FAINT}>Customer count and outage share: {detail.customers_label}</li>}
        </ul>
      </div>
    </section>
  );
}

function SourceLink({ c }: { c: Pick<Citation, "source_name" | "source_url"> }) {
  const href = safeUrl(c.source_url);
  if (!href) return <span>{c.source_name}</span>;
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-accent underline hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
    >
      {c.source_name}
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  );
}

function ActiveEvents({ events, town }: { events: ActiveTelecomEvent[]; town: string }) {
  const headingId = useId();
  return (
    <div aria-labelledby={headingId} role="group" className="text-[13px]">
      <h4 id={headingId} className="sr-only">
        Observed telecom events active for {town} or Cape-wide
      </h4>
      {events.length === 0 ? (
        <p className="text-xs text-muted">Observed telecom events active for {town} or Cape-wide: none at this hour.</p>
      ) : (
        <details className="rounded-card border border-line">
          <summary className="cursor-pointer rounded-card px-3 py-2 text-xs font-medium text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">
            Telecom reports at this hour ({events.length})
          </summary>
          <div className="flex flex-col gap-2 px-3 pb-3">
            <p className={FAINT}>
              Shown as context. An event sets the reach channel only when it is marked to drive the phones flag.
            </p>
            <ul className="flex flex-col gap-1.5">
              {events.map((e) => (
                <li key={e.id} className="rounded-card border border-line p-2">
                  <p className="font-semibold text-fg">
                    {humanize(e.system)}: {humanize(e.status)}
                  </p>
                  <p className="text-xs text-muted">
                    Affects: {affectsText(e.affects)}. Area: {e.town_or_area}.
                  </p>
                  <p className="font-mono text-[11px] text-muted">{eventWindowText(e)}</p>
                  {e.note && <p className="text-xs text-muted">{e.note}</p>}
                  <p className={FAINT}>{eventChannelNote(e)}</p>
                  <p className="text-xs text-fg">
                    Source: <SourceLink c={e} />
                  </p>
                </li>
              ))}
            </ul>
          </div>
        </details>
      )}
    </div>
  );
}
