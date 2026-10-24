import type { Badge } from "../provenance";

interface Props {
  badges: Badge[];
}

/** Provenance labels for the layers on screen (Req 8.8, 25.3, 25.4). */
export function SourceBadges({ badges }: Props) {
  return (
    <section aria-labelledby="source-badges-heading" className="text-xs">
      <h2 id="source-badges-heading" className="mb-1 font-semibold text-slate-300">
        Sources for what is on screen
      </h2>
      <ul className="flex flex-wrap gap-1.5">
        {badges.map((b) => (
          <li
            key={b.id}
            data-badge={b.id}
            className="rounded border border-slate-600 bg-slate-900 px-2 py-1 text-slate-200"
          >
            <span className="text-slate-400">{b.detail}: </span>
            {b.label}
          </li>
        ))}
      </ul>
    </section>
  );
}
