import { forwardRef, useId } from "react";
import {
  BACK_TO_CAPE_LABEL,
  BOSTON_PLACEHOLDER_TEXT,
  SELECTOR_LABEL,
  entryOptionLabel,
  previewModel,
} from "../scale";
import type { CatalogEntry } from "../types";

interface SelectorProps {
  entries: readonly CatalogEntry[];
  value: string;
  onChange: (id: string) => void;
}

/** Native <select> listing every catalog entry with its tier (Req 24.1, 24.2, 29.1). */
export const ScaleSelector = forwardRef<HTMLSelectElement, SelectorProps>(function ScaleSelector(
  { entries, value, onChange },
  ref,
) {
  const id = useId();
  return (
    <div className="flex items-center gap-2">
      <label htmlFor={id} className="text-sm text-slate-300">
        {SELECTOR_LABEL}
      </label>
      <select
        id={id}
        ref={ref}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-slate-600 bg-slate-800 px-2 py-1 text-sm text-slate-100 hover:bg-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-300"
      >
        {entries.map((e) => (
          <option key={e.id} value={e.id}>
            {entryOptionLabel(e)}
          </option>
        ))}
      </select>
    </div>
  );
});

interface PreviewProps {
  entry: CatalogEntry;
  onBack: () => void;
}

/** Configuration_Preview: tier and inputs for a place and hazard, never a score (Req 24.5, 23.12).
 *  Renders only fields of the preview view model, whose only number is the tier. */
export function ConfigurationPreview({ entry, onBack }: PreviewProps) {
  const m = previewModel(entry);
  const headingId = useId();
  return (
    <section
      aria-labelledby={headingId}
      className="mx-auto flex max-w-3xl flex-col gap-4 rounded-md border border-slate-700 bg-slate-900 p-5"
    >
      <div className="flex flex-wrap items-center gap-3">
        <h2 id={headingId} className="text-xl font-semibold">
          {m.heading}
        </h2>
        <span className="rounded border border-amber-300/70 bg-amber-950/70 px-1.5 py-0.5 text-xs font-semibold tracking-wide text-amber-100">
          {m.badge}
        </span>
        <span className="rounded border border-slate-500 bg-slate-800 px-1.5 py-0.5 text-xs font-semibold">
          {m.tierLabel}
        </span>
      </div>
      <p className="text-slate-200">{m.tierText}</p>
      <div className="grid gap-4 sm:grid-cols-2">
        <InputList title="Need inputs" items={m.needInputs} />
        <InputList title={`Lost-lifelines inputs for ${entry.hazard_label.toLowerCase()}`} items={m.lostLifelinesInputs} />
      </div>
      <p className="text-sm text-slate-300">{m.noScoresText}</p>
      <div>
        <BackButton onBack={onBack} />
      </div>
    </section>
  );
}

/** Switch point for the Boston Voice view: task 16 replaces this placeholder with BostonVoiceView. */
export function BostonPlaceholder({ onBack }: { onBack: () => void }) {
  return (
    <section className="mx-auto flex max-w-3xl flex-col gap-3 rounded-md border border-slate-700 bg-slate-900 p-5">
      <p className="text-slate-200">{BOSTON_PLACEHOLDER_TEXT}</p>
      <div>
        <BackButton onBack={onBack} />
      </div>
    </section>
  );
}

function InputList({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <h3 className="mb-1 text-base font-semibold">{title}</h3>
      <ul className="list-disc pl-5 text-slate-200">
        {items.map((i) => (
          <li key={i}>{i}</li>
        ))}
      </ul>
    </div>
  );
}

function BackButton({ onBack }: { onBack: () => void }) {
  return (
    <button
      type="button"
      onClick={onBack}
      className="rounded-md border border-sky-300 bg-sky-900 px-3 py-1.5 text-sm font-semibold text-white hover:bg-sky-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-300"
    >
      {BACK_TO_CAPE_LABEL}
    </button>
  );
}
