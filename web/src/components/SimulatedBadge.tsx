import { SIMULATED_LABEL } from "../labels";

interface Props {
  className?: string;
}

/** "Simulated" badge for every synthetic record (Req 17.10). Shared by Queue, drawer, Reach panel
 *  and phone simulator. Text, not color alone, carries the meaning. */
export function SimulatedBadge({ className = "" }: Props) {
  return (
    <span
      className={`inline-flex items-center rounded-full border border-simulated/40 px-1.5 py-0.5 text-[10px] font-medium uppercase leading-none tracking-[0.08em] text-simulated ${className}`}
    >
      {SIMULATED_LABEL}
    </span>
  );
}
