import { useCallback, useMemo, useRef, useState } from "react";
import { useStaticData } from "./api";
import { ApiBanner } from "./components/ApiBanner";
import { MapView } from "./components/MapView";
import { Queue } from "./components/Queue";
import { ResetControl } from "./components/ResetControl";
import { BostonPlaceholder, ConfigurationPreview, ScaleSelector } from "./components/ScaleSelector";
import { SourcesPopover } from "./components/SourcesPopover";
import { TimeSlider } from "./components/TimeSlider";
import { PhoneSimulator } from "./components/PhoneSimulator";
import { TractDrawer, type RunContext } from "./components/TractDrawer";
import { formatHour } from "./format";
import { DEFAULT_LAYER, LAYERS, clampHourIdx, defaultHourIdx, shortTractName, type Layer } from "./mapValues";
import { sourceBadges } from "./provenance";
import { queueAt } from "./queue";
import { CAPE_ENTRY_ID, viewForId } from "./scale";
import type { Geoid, StaticData } from "./types";

/** Drawer plug-in below the check-in status: the phone simulator for the run on screen (task 13.5). */
const renderPhoneSimulator = (ctx: RunContext) => <PhoneSimulator {...ctx} />;

export default function App() {
  const { data, error, loading, retry } = useStaticData();
  const [layer, setLayer] = useState<Layer>(DEFAULT_LAYER);
  const [entryId, setEntryId] = useState<string>(CAPE_ENTRY_ID);
  // Hour lives here so it survives a trip to a preview and back; null = the default key hour.
  const [hourIdx, setHourIdx] = useState<number | null>(null);
  // Incremented after each successful demo reset; views refetch per-tract state on change (Req 21.2).
  const [resetVersion, setResetVersion] = useState(0);
  const selectRef = useRef<HTMLSelectElement>(null);

  const entries = data?.catalog.entries ?? [];
  const view = viewForId(entries, entryId);
  const entry = entries.find((e) => e.id === entryId);
  const onReset = useCallback(() => setResetVersion((v) => v + 1), []);
  const backToCape = useCallback(() => {
    setEntryId(CAPE_ENTRY_ID);
    // The preview unmounts with the focused button; return focus to the selector.
    requestAnimationFrame(() => selectRef.current?.focus());
  }, []);

  // Provenance for the top-bar popover: the layer on screen first, then the labels only other layers use.
  const badges = useMemo(() => {
    if (!data || view.kind !== "cape") return null;
    const ctx = { timeline: data.timeline, towns: data.towns, sources: data.sources };
    const onScreen = sourceBadges(layer, ctx);
    const ids = new Set(onScreen.map((b) => b.id));
    const otherLayers = sourceBadges("priority", ctx).filter((b) => !ids.has(b.id));
    return { onScreen, otherLayers };
  }, [data, view.kind, layer]);

  const subtitle =
    view.kind === "cape" ? "Cape Cod · Blizzard of 2026 replay" : entry ? `${entry.place} · ${entry.hazard_label}` : "";

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-bg text-fg">
      <main className="absolute inset-0" aria-busy={loading}>
        {data && !error && view.kind === "cape" && (
          <CapeView data={data} layer={layer} hourIdx={hourIdx} onHourIdx={setHourIdx} resetVersion={resetVersion} />
        )}
        {/* Switch point: task 16 renders BostonVoiceView here for the live Boston entry. */}
        {data && !error && view.kind !== "cape" && (
          <div className="absolute inset-x-3 bottom-3 top-[76px] flex items-center justify-center overflow-y-auto">
            {view.kind === "boston" && <BostonPlaceholder onBack={backToCape} />}
            {view.kind === "preview" && entry && <ConfigurationPreview entry={entry} onBack={backToCape} />}
          </div>
        )}
        {loading && !error && (
          <p className="absolute inset-0 flex items-center justify-center text-muted">Loading demo data…</p>
        )}
      </main>
      <header className="glass absolute left-3 right-3 top-3 z-20 flex h-[52px] items-center gap-4 px-4">
        <h1 className="flex min-w-0 items-baseline gap-3 whitespace-nowrap">
          <span className="flex items-center gap-2 text-[15px] font-semibold">
            <span aria-hidden="true" className="h-2 w-2 rounded-full bg-accent" />
            Lifeline
          </span>
          {subtitle && <span className="truncate text-[13px] font-normal text-muted">{subtitle}</span>}
        </h1>
        <div className="ml-auto flex items-center gap-3">
          {entries.length > 0 && (
            <ScaleSelector ref={selectRef} entries={entries} value={entryId} onChange={setEntryId} />
          )}
          {view.kind === "cape" && <LayerSwitch layer={layer} onChange={setLayer} />}
          {data && badges && (
            <SourcesPopover onScreen={badges.onScreen} otherLayers={badges.otherLayers} sources={data.sources} />
          )}
          <ResetControl onReset={onReset} />
        </div>
      </header>
      {error && (
        <div className="absolute left-1/2 top-[76px] z-30 w-[min(640px,calc(100vw-24px))] -translate-x-1/2">
          <ApiBanner error={error} loading={loading} onRetry={retry} />
        </div>
      )}
    </div>
  );
}

function LayerSwitch({ layer, onChange }: { layer: Layer; onChange: (l: Layer) => void }) {
  return (
    <fieldset className="flex items-center rounded-full border border-line bg-bg/40 p-0.5">
      <legend className="sr-only">Map layer</legend>
      {LAYERS.map((l) => (
        <label
          key={l.id}
          className={`cursor-pointer whitespace-nowrap rounded-full border px-3 py-1 text-xs font-medium transition-colors duration-150 ease-out has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent ${
            layer === l.id ? "border-line-strong bg-panel-solid text-fg" : "border-transparent text-muted hover:text-fg"
          }`}
        >
          <input
            type="radio"
            name="map-layer"
            value={l.id}
            checked={layer === l.id}
            onChange={() => onChange(l.id)}
            className="sr-only"
          />
          {l.label}
        </label>
      ))}
    </fieldset>
  );
}

/** Cape view state: selected tract (the hour index is owned by App). Every per-hour value is derived client-side from
 *  the timeline, so a slider change re-renders all panels without a fetch (Req 8.3). The drawer
 *  fetches only the selected tract-hour (useTractDetail). */
interface CapeViewProps {
  data: StaticData;
  layer: Layer;
  /** Owned by App so it survives view switches and resets; null = default key hour. */
  hourIdx: number | null;
  onHourIdx: (i: number) => void;
  resetVersion: number;
}

function CapeView({ data, layer, hourIdx: hourIdxProp, onHourIdx, resetVersion }: CapeViewProps) {
  const { timeline, tracts, towns, events } = data;
  const n = timeline.hours.length;
  const hourIdx = clampHourIdx(hourIdxProp ?? defaultHourIdx(timeline.hours), n);
  const [selectedGeoid, setSelectedGeoid] = useState<Geoid | null>(null);
  const setHourIdx = useCallback((i: number) => onHourIdx(clampHourIdx(i, n)), [n, onHourIdx]);
  const onSelectTract = useCallback((geoid: Geoid) => setSelectedGeoid(geoid), []);
  const onCloseDrawer = useCallback(() => setSelectedGeoid(null), []);

  const selected = selectedGeoid ? tracts.features.find((f) => f.properties.geoid === selectedGeoid) : undefined;
  const hour = timeline.hours[hourIdx] ?? "";
  const queueRows = useMemo(() => queueAt(timeline, hour), [timeline, hour]);

  // Left panel element that hosts MapView's collapsed tract and telecom lists (portal target).
  const [listsEl, setListsEl] = useState<HTMLDivElement | null>(null);

  return (
    <>
      <MapView
        tracts={tracts}
        towns={towns}
        timeline={timeline}
        events={events}
        hourIdx={hourIdx}
        layer={layer}
        selectedGeoid={selectedGeoid}
        onSelectTract={onSelectTract}
        listsContainer={listsEl}
      />
      <aside
        aria-label="Priority list panel"
        className="glass absolute bottom-[116px] left-3 top-[76px] z-10 flex w-[min(360px,28vw)] min-w-[300px] flex-col gap-3 overflow-y-auto p-4"
      >
        <Queue
          rows={queueRows}
          hour={hour}
          tracts={tracts}
          selectedGeoid={selectedGeoid}
          onSelectTract={onSelectTract}
        />
        <div ref={setListsEl} />
      </aside>
      <div className="glass absolute bottom-3 left-3 right-3 z-10 flex h-[92px] items-center px-4">
        <TimeSlider hours={timeline.hours} keyHours={timeline.key_demo_hours} hourIdx={hourIdx} onChange={setHourIdx} capeTotal={timeline.cape_total} />
      </div>
      <p role="status" className="sr-only">
        {selected
          ? `Selected: ${shortTractName(selected.properties.name)}, ${selected.properties.town} at ${formatHour(hour)}.`
          : "Select a tract on the map, in the tract list or in the priority list."}
      </p>
      {selected && (
        <div className="lifeline-drawer-wrap absolute bottom-[116px] right-3 top-[76px] z-20 w-[min(440px,34vw)] min-w-[380px]">
          <TractDrawer
            geoid={selected.properties.geoid}
            hour={hour}
            town={selected.properties.town}
            name={selected.properties.name}
            scoring={timeline}
            resetVersion={resetVersion}
            onClose={onCloseDrawer}
            reach={renderPhoneSimulator}
          />
        </div>
      )}
    </>
  );
}
