import { useEffect, useId, useRef, useState } from "react";
import type { Badge } from "../provenance";
import type { Sources } from "../types";
import { SourceBadges } from "./SourceBadges";

interface Props {
  /** Badges for the layer on screen. */
  onScreen: Badge[];
  /** Badges that apply to the other layers (shown so every provenance label stays reachable). */
  otherLayers: Badge[];
  sources: Sources;
}

const isHttp = (url: string) => /^https?:\/\//i.test(url);

/** Unique data sources by name, from the fetches and the workbook inputs. */
function dataSources(sources: Sources): { name: string; url: string }[] {
  const seen = new Map<string, string>();
  for (const f of sources.fetches ?? []) if (!seen.has(f.name)) seen.set(f.name, f.url);
  for (const w of sources.workbook_inputs ?? []) if (!seen.has(w.source_name)) seen.set(w.source_name, w.source_url);
  return [...seen].map(([name, url]) => ({ name, url }));
}

const sectionLabel = "mb-2 text-[11px] font-medium uppercase tracking-[0.06em] text-muted";

/** (i) button in the top bar that opens a non-modal "Sources & assumptions" popover (Req 8.8, 25.3, 25.4, 29.1). */
export function SourcesPopover({ onScreen, otherLayers, sources }: Props) {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const popRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const id = useId();
  const popId = `${id}-pop`;
  const headingId = `${id}-heading`;

  useEffect(() => {
    if (!open) return;
    headingRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    const onPointer = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!popRef.current?.contains(t) && !buttonRef.current?.contains(t)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open]);

  const assumptions = sources.assumptions ?? [];
  const inputs = dataSources(sources);

  return (
    <div className="relative">
      <button
        ref={buttonRef}
        type="button"
        aria-label="Sources & assumptions"
        aria-expanded={open}
        aria-controls={popId}
        onClick={() => setOpen((o) => !o)}
        className={`flex h-8 w-8 items-center justify-center rounded-full border text-muted transition-colors duration-150 ease-out hover:bg-line hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
          open ? "border-line-strong bg-line text-fg" : "border-transparent"
        }`}
      >
        <svg aria-hidden="true" width="18" height="18" viewBox="0 0 20 20" fill="none">
          <circle cx="10" cy="10" r="8.25" stroke="currentColor" strokeWidth="1.5" />
          <path d="M10 9v5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          <circle cx="10" cy="6.25" r="1" fill="currentColor" />
        </svg>
      </button>
      <div
        ref={popRef}
        id={popId}
        role="dialog"
        aria-modal="false"
        aria-labelledby={headingId}
        hidden={!open}
        className="absolute right-0 top-[calc(100%+12px)] z-40 max-h-[min(640px,calc(100vh-120px))] w-[380px] overflow-y-auto rounded-panel border border-line-strong bg-panel-solid p-4 text-[13px] text-fg shadow-panel"
      >
        <h2 ref={headingRef} id={headingId} tabIndex={-1} className="mb-3 text-[15px] font-semibold focus:outline-none">
          Sources &amp; assumptions
        </h2>
        <section aria-label="On screen" className="mb-4">
          <h3 className={sectionLabel}>On screen</h3>
          <SourceBadges badges={onScreen} />
        </section>
        {otherLayers.length > 0 && (
          <section aria-label="Other layers" className="mb-4">
            <h3 className={sectionLabel}>Other layers</h3>
            <SourceBadges badges={otherLayers} />
          </section>
        )}
        {assumptions.length > 0 && (
          <section aria-label="Assumptions" className="mb-4">
            <h3 className={sectionLabel}>Assumptions</h3>
            <ul className="flex flex-col gap-1.5">
              {assumptions.map((a) => (
                <li key={a.key} className="flex items-baseline justify-between gap-3">
                  <span className="text-muted">{a.label}</span>
                  <span className="shrink-0 font-mono text-fg">{String(a.value)}</span>
                </li>
              ))}
            </ul>
          </section>
        )}
        {inputs.length > 0 && (
          <section aria-label="Data sources">
            <h3 className={sectionLabel}>Data sources</h3>
            <ul className="flex flex-col gap-1">
              {inputs.map((s) => (
                <li key={s.name} className="text-muted">
                  {isHttp(s.url) ? (
                    <a
                      href={s.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="underline decoration-line-strong underline-offset-2 hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                    >
                      {s.name}
                    </a>
                  ) : (
                    s.name
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  );
}
