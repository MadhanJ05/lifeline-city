import { useCallback, useMemo, useRef, useState } from "react";
import { useStaticData } from "./api";
import { ApiBanner } from "./components/ApiBanner";
import { MapView } from "./components/MapView";
import { Queue } from "./components/Queue";
import { ResetControl } from "./components/ResetControl";
import { BostonPlaceholder, ConfigurationPreview, ScaleSelector } from "./components/ScaleSelector";
import { SourceBadges } from "./components/SourceBadges";
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

  const subtitle =
    view.kind === "cape" ? "Blizzard of 2026 replay (Cape Cod)" : entry ? `${entry.place}: ${entry.hazard_label}` : "";

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-slate-800 px-4 py-3">
        <h1 className="text-lg font-semibold">
          Lifeline City{subtitle && <span className="font-normal text-slate-300"> — {subtitle}</span>}
        </h1>
        {entries.length > 0 && <ScaleSelector ref={selectRef} entries={entries} value={entryId} onChange={setEntryId} />}
        {view.kind === "cape" && <LayerSwitch layer={layer} onChange={setLayer} />}
        <div className="ml-auto">
          <ResetControl onReset={onReset} />
        </div>
      </header>
      <ApiBanner error={error} loading={loading} onRetry={retry} />
      <main className="px-4 py-3" aria-busy={loading}>
        {loading && !error && <p className="text-slate-300">Loading demo data…</p>}
        {data && !error && view.kind === "cape" && (
          <CapeView data={data} layer={layer} hourIdx={hourIdx} onHourIdx={setHourIdx} resetVersion={resetVersion} />
        )}
        {/* Switch point: task 16 renders BostonVoiceView here for the live Boston entry. */}
        {data && !error && view.kind === "boston" && <BostonPlaceholder onBack={backToCape} />}
        {data && !error && view.kind === "preview" && entry && <ConfigurationPreview entry={entry} onBack={backToCape} />}
      </main>
    </div>
  );
}

function LayerSwitch({ layer, onChange }: { layer: Layer; onChange: (l: Layer) => void }) {
  return (
    <fieldset className="flex items-center gap-1">
      <legend className="sr-only">Map layer</legend>
      <span aria-hidden="true" className="mr-1 text-sm text-slate-300">
        Layer:
      </span>
      {LAYERS.map((l) => (
        <label
          key={l.id}
          className={`cursor-pointer rounded-md border px-2.5 py-1 text-sm has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-sky-300 ${
            layer === l.id ? "border-sky-300 bg-sky-900 text-white" : "border-slate-600 bg-slate-800 text-slate-100 hover:bg-slate-700"
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
  const { timeline, tracts, towns, events, sources } = data;
  const n = timeline.hours.length;
  const hourIdx = clampHourIdx(hourIdxProp ?? defaultHourIdx(timeline.hours, timeline.key_demo_hours), n);
  const [selectedGeoid, setSelectedGeoid] = useState<Geoid | null>(null);
  const setHourIdx = useCallback((i: number) => onHourIdx(clampHourIdx(i, n)), [n, onHourIdx]);
  const onSelectTract = useCallback((geoid: Geoid) => setSelectedGeoid(geoid), []);
  const onCloseDrawer = useCallback(() => setSelectedGeoid(null), []);

  const badges = useMemo(() => sourceBadges(layer, { timeline, towns, sources }), [layer, timeline, towns, sources]);
  const selected = selectedGeoid ? tracts.features.find((f) => f.properties.geoid === selectedGeoid) : undefined;
  const hour = timeline.hours[hourIdx] ?? "";
  const queueRows = useMemo(() => queueAt(timeline, hour), [timeline, hour]);

  // Wide screens (xl): the drawer is a sticky right column; while it is open the queue moves under the
  // map until 2xl, so the map keeps a usable width. Smaller screens: the drawer stacks below.
  const grid = selected
    ? "lg:grid-cols-[minmax(0,1fr)_24rem] xl:grid-cols-1 2xl:grid-cols-[minmax(0,1fr)_22rem]"
    : "lg:grid-cols-[minmax(0,1fr)_24rem]";

  return (
    <div className="flex flex-col gap-3 xl:flex-row xl:items-start">
      <div className="flex min-w-0 flex-1 flex-col gap-3">
        <TimeSlider hours={timeline.hours} keyHours={timeline.key_demo_hours} hourIdx={hourIdx} onChange={setHourIdx} />
        <div className={`grid gap-3 ${grid}`}>
          <MapView
            tracts={tracts}
            towns={towns}
            timeline={timeline}
            events={events}
            hourIdx={hourIdx}
            layer={layer}
            selectedGeoid={selectedGeoid}
            onSelectTract={onSelectTract}
          />
          <Queue
            rows={queueRows}
            hour={hour}
            tracts={tracts}
            selectedGeoid={selectedGeoid}
            onSelectTract={onSelectTract}
          />
        </div>
        <p role="status" className="text-sm text-slate-300">
          {selected
            ? `Selected: ${shortTractName(selected.properties.name)}, ${selected.properties.town} at ${formatHour(hour)}.`
            : "Select a tract on the map, in the tract list or in the priority queue."}
        </p>
        <SourceBadges badges={badges} />
      </div>
      {selected && (
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
      )}
    </div>
  );
}
