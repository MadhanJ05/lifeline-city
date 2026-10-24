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

const TH = "px-2 py-1 text-left font-semibold text-slate-200";
const TD = "px-2 py-1 align-top";

/** Every scoring input for the tract-hour as text (Req 10.1, 10.2, 10.3, 10.5, 25.3, 25.4, 29.4). */
export function WhyFlagged({ detail, scoring }: Props) {
  const headingId = useId();
  const rows = needRows(detail);
  const missing = missingIndicatorNames(detail);
  const comps = componentRows(detail, scoring.hours_dark_cap);
  const telecom = telecomRuleView(detail, scoring.telecom_model);

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <h3 id={headingId} className="text-base font-semibold text-slate-100">
        Why flagged
      </h3>

      {/* Need */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm text-slate-100">
          <caption className="pb-1 text-left text-sm font-semibold text-slate-200">
            Need: {fmt3(detail.need_t)} (mean of the percentile ranks among Cape tracts)
          </caption>
          <thead className="border-b border-slate-700 text-xs">
            <tr>
              <th scope="col" className={TH}>Indicator</th>
              <th scope="col" className={`${TH} text-right`}>Value</th>
              <th scope="col" className={`${TH} text-right`}>Rank</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-b border-slate-800">
                <th scope="row" className={`${TD} text-left font-normal`}>
                  {r.label} <span className="text-xs text-slate-400">({r.source})</span>
                </th>
                <td className={`${TD} text-right tabular-nums ${r.missing ? "text-amber-200" : ""}`}>{r.raw}</td>
                <td className={`${TD} text-right tabular-nums ${r.missing ? "text-amber-200" : ""}`}>{r.rank}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-1 text-xs text-slate-300">
          {missing.length
            ? `Missing indicators: ${missing.join(", ")}. Need averages the indicators that exist.`
            : "No missing indicators."}
        </p>
        {detail.empower_masked && (
          <p className="mt-1 text-xs text-slate-300">
            {EMPOWER_MASKING_NOTE}. The value is shown as reported and is not unmasked.
          </p>
        )}
      </div>

      {/* Lost lifelines */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm text-slate-100">
          <caption className="pb-1 text-left text-sm font-semibold text-slate-200">
            Lost lifelines for {detail.town} (weight × term = contribution)
          </caption>
          <thead className="border-b border-slate-700 text-xs">
            <tr>
              <th scope="col" className={TH}>Component</th>
              <th scope="col" className={`${TH} text-right`}>Weight</th>
              <th scope="col" className={TH}>Value</th>
              <th scope="col" className={`${TH} text-right`}>Contribution</th>
            </tr>
          </thead>
          <tbody>
            {comps.map((c) => (
              <tr key={c.id} className="border-b border-slate-800">
                <th scope="row" className={`${TD} text-left font-normal`}>
                  {c.label}
                </th>
                <td className={`${TD} text-right tabular-nums`}>{fmtWeight(c.weight)}</td>
                <td className={TD}>
                  <span className="tabular-nums">{c.value}</span>
                  {c.id === "hours_dark" && (
                    <span className="block text-xs text-slate-400">Term {fmt3(c.term)} (hours ÷ cap, at most 1)</span>
                  )}
                  {c.notes.map((n) => (
                    <span key={n} className="block text-xs text-slate-300">
                      {n}
                    </span>
                  ))}
                </td>
                <td className={`${TD} text-right tabular-nums`}>{fmt3(c.contribution)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot className="text-sm">
            <tr>
              <th scope="row" colSpan={3} className={`${TD} text-left font-semibold`}>
                Lost lifelines (sum)
              </th>
              <td className={`${TD} text-right font-semibold tabular-nums`}>{fmt3(detail.lifelines)}</td>
            </tr>
            <tr>
              <th scope="row" colSpan={3} className={`${TD} text-left font-semibold`}>
                Priority = Need {fmt3(detail.need_t)} × lost lifelines {fmt3(detail.lifelines)}
              </th>
              <td className={`${TD} text-right font-semibold tabular-nums`}>{fmt3(detail.priority)}</td>
            </tr>
          </tfoot>
        </table>
      </div>

      {/* Telecom rule */}
      <div className="rounded-md border border-slate-700 bg-slate-900 p-2 text-sm">
        <h4 className="font-semibold text-slate-100">{telecom.headline}</h4>
        <p className="mt-0.5 text-slate-300">{telecom.rule}</p>
        {telecom.label && <p className="mt-0.5 text-xs text-slate-200">{telecom.label}</p>}
        {telecom.citations.length > 0 && (
          <ul className="mt-1 list-disc pl-5 text-xs text-slate-200">
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
      <div className="text-xs text-slate-300">
        <h4 className="font-semibold text-slate-200">Sources for {detail.town}</h4>
        <ul className="mt-0.5 list-disc pl-5">
          <li>Outage share and hours dark: {detail.out_pct_label}</li>
          {detail.customers_label && <li>Customer count and outage share: {detail.customers_label}</li>}
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
      className="text-sky-300 underline hover:text-sky-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-300"
    >
      {c.source_name}
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  );
}

function ActiveEvents({ events, town }: { events: ActiveTelecomEvent[]; town: string }) {
  const headingId = useId();
  return (
    <div aria-labelledby={headingId} role="group" className="text-sm">
      <h4 id={headingId} className="font-semibold text-slate-100">
        Observed telecom events active for {town} or Cape-wide
      </h4>
      {events.length === 0 ? (
        <p className="text-slate-300">None at this hour.</p>
      ) : (
        <>
          <p className="text-xs text-slate-300">
            Shown as context. An event sets the reach channel only when it is marked to drive the phones flag.
          </p>
          <ul className="mt-1 flex flex-col gap-1.5">
            {events.map((e) => (
              <li key={e.id} className="rounded-md border border-slate-700 bg-slate-900 p-2">
                <p className="font-semibold text-slate-100">
                  {humanize(e.system)}: {humanize(e.status)}
                </p>
                <p className="text-xs text-slate-300">
                  Affects: {affectsText(e.affects)}. Area: {e.town_or_area}.
                </p>
                <p className="text-xs text-slate-300">{eventWindowText(e)}</p>
                {e.note && <p className="text-xs text-slate-300">{e.note}</p>}
                <p className="text-xs text-slate-300">{eventChannelNote(e)}</p>
                <p className="text-xs text-slate-200">
                  Source: <SourceLink c={e} />
                </p>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
