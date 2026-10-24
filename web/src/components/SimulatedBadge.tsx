import { SIMULATED_LABEL } from "../labels";

interface Props {
  className?: string;
}

/** "Simulated" badge for every synthetic record (Req 17.10). Shared by Queue, drawer, Reach panel
 *  and phone simulator. Text, not color alone, carries the meaning. */
export function SimulatedBadge({ className = "" }: Props) {
  return (
    <span
      className={`inline-flex items-center rounded border border-fuchsia-300/70 bg-fuchsia-950/70 px-1.5 py-0.5 text-xs font-semibold tracking-wide text-fuchsia-100 ${className}`}
    >
      {SIMULATED_LABEL}
    </span>
  );
}
