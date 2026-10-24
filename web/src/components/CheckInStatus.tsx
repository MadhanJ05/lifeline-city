import { useId } from "react";
import {
  checkInLists,
  countersAnnouncement,
  countersText,
  elapsedText,
  escalationStatusText,
  escalationTimeText,
  silentReasonText,
  statusText,
} from "../checkin";
import { SIMULATED_LABEL } from "../labels";
import { langLabel } from "../reach";
import type { Channel, Escalation, HouseholdStatus, Run, RunHousehold } from "../types";
import { SimulatedBadge } from "./SimulatedBadge";

interface Props {
  channel: Channel;
  households: HouseholdStatus[];
  /** The run for the tract-hour on screen (already matched by the drawer), or null. */
  run: Run | null;
  /** Last poll error, shown without hiding the last known run state. */
  pollError?: Error | null;
}

/** Check-in counters, Escalation list, silent follow-up list and door-knock statuses for the drawer
 *  (Req 10.6, 18.9, 19.8, 20.2, 20.3). All records are synthetic and carry the "Simulated" badge. */
export function CheckInStatus({ channel, households, run, pollError }: Props) {
  const headingId = useId();
  const lists = checkInLists(channel, households, run);

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3 rounded-md border border-slate-700 bg-slate-900 p-3 text-sm">
      <h4 id={headingId} className="font-semibold">
        Check-in run ({SIMULATED_LABEL})
      </h4>

      {channel === "door_knock" ? (
        <DoorKnockStatuses households={lists.awaitingDoorKnock} />
      ) : run ? (
        <RunSummary run={run} silent={lists.silent} />
      ) : (
        <p className="text-slate-300">No check-ins sent for this tract-hour yet.</p>
      )}

      {pollError && (
        <p role="alert" className="rounded border border-rose-400/70 bg-rose-950/60 px-2 py-1 text-xs">
          Could not refresh the run: {pollError.message}
        </p>
      )}
    </section>
  );
}

function RunSummary({ run, silent }: { run: Run; silent: RunHousehold[] }) {
  return (
    <>
      <div className="flex flex-col gap-1">
        <p className="font-semibold tabular-nums">{countersText(run.counters)}</p>
        <p className="text-xs text-slate-300 tabular-nums">
          Reply window: {elapsedText(run.elapsed_s, run.timeout_s)}
          {" · "}
          {run.complete ? "Run complete" : "Updating every 2 seconds"}
        </p>
        {/* Counters only, so the seconds ticking by are not read out on every poll. */}
        <p aria-live="polite" aria-atomic="true" className="sr-only">
          {countersAnnouncement(run)}
        </p>
      </div>
      <EscalationList escalations={run.escalations} />
      <SilentList households={silent} />
    </>
  );
}

function EscalationList({ escalations }: { escalations: Escalation[] }) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-1.5">
      <h5 id={headingId} className="font-semibold">
        Escalations ({escalations.length})
      </h5>
      {escalations.length === 0 ? (
        <p className="text-slate-300">No one has asked for help yet.</p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {escalations.map((e) => (
            <li key={e.id} className="rounded-md border border-amber-300/60 bg-slate-950 p-2">
              <p className="flex flex-wrap items-center gap-1.5 font-semibold">
                {e.household_label} <SimulatedBadge />
              </p>
              <dl className="grid grid-cols-[auto_1fr] gap-x-2 text-xs">
                <dt className="text-slate-400">Language</dt>
                <dd>{langLabel(e.lang)}</dd>
                <dt className="text-slate-400">Asked for help</dt>
                <dd className="tabular-nums">{escalationTimeText(e.created_at)}</dd>
                <dt className="text-slate-400">Responder</dt>
                <dd>{e.responder_label}</dd>
                <dt className="text-slate-400">Status</dt>
                <dd>{escalationStatusText(e.status)}</dd>
              </dl>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function SilentList({ households }: { households: RunHousehold[] }) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-1.5">
      <h5 id={headingId} className="font-semibold">
        Needs human follow-up (no reply) ({households.length})
      </h5>
      {households.length === 0 ? (
        <p className="text-slate-300">No household is silent.</p>
      ) : (
        <>
          <p className="text-xs text-slate-300">
            No reply is a question, not a verdict. A person should follow up by phone or at the door.
          </p>
          <ul className="flex flex-col gap-1.5">
            {households.map((h) => (
              <li key={h.id} className="rounded-md border border-slate-600 bg-slate-950 p-2">
                <p className="flex flex-wrap items-center gap-1.5 font-semibold">
                  {h.label} <SimulatedBadge />
                </p>
                <dl className="grid grid-cols-[auto_1fr] gap-x-2 text-xs">
                  <dt className="text-slate-400">Language</dt>
                  <dd>{langLabel(h.lang)}</dd>
                  <dt className="text-slate-400">Why</dt>
                  <dd>{silentReasonText(h.silent_reason)}</dd>
                </dl>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function DoorKnockStatuses({ households }: { households: HouseholdStatus[] }) {
  return (
    <div className="flex flex-col gap-1.5">
      <p className="text-slate-200">
        Phones likely degraded: no SMS is sent and no household is counted as silent. Responders check in person.
      </p>
      {households.length === 0 ? (
        <p className="text-slate-300">No simulated households in this tract.</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {households.map((h) => (
            <li key={h.id} className="flex flex-wrap items-center gap-1.5">
              <span className="font-semibold">{h.label}</span> <SimulatedBadge />
              <span className="text-xs text-slate-300">
                {langLabel(h.lang)} · {statusText(h.status)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
