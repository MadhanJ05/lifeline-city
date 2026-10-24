import type { Badge } from "../provenance";

interface Props {
  badges: Badge[];
}

/** Provenance labels as a quiet list: label in body text, what it applies to as a faint line (Req 8.8, 25.3, 25.4). */
export function SourceBadges({ badges }: Props) {
  return (
    <ul className="flex flex-col gap-2">
      {badges.map((b) => (
        <li key={b.id} data-badge={b.id} className="rounded-card border border-line px-2.5 py-2">
          <p className="text-[13px] leading-snug text-fg">{b.label}</p>
          <p className="mt-0.5 text-[11px] leading-snug text-muted">{b.detail}</p>
        </li>
      ))}
    </ul>
  );
}
