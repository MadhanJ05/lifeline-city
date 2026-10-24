import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import {
  Map as MapLibreMap,
  Marker,
  NavigationControl,
  Popup,
  setWorkerUrl,
  type GeoJSONSourceSpecification,
  type MapLayerMouseEvent,
  type StyleSpecification,
} from "maplibre-gl";
// MapLibre looks for its worker next to its own module URL by default, which does not exist once
// Vite bundles or pre-bundles it. Point it at the worker file Vite emits as an asset.
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import { formatHour } from "../format";
import {
  bboxOf,
  fillColorExpression,
  formatLayerValue,
  humanize,
  isEventActive,
  layerDomainMax,
  layerLabel,
  layerValues,
  legendStops,
  pinFeatures,
  pinGroups,
  shortTractName,
  sortByValue,
  tractRefs,
  tractTown,
  type Layer,
  type LegendStop,
  type PinGroup,
  type SortedTract,
} from "../mapValues";
import { tooltipNotes } from "../provenance";
import type { CapeTimeline, CapeTowns, CapeTracts, Geoid, HourKey, TelecomEvent, TelecomEvents } from "../types";

/** CARTO dark-matter vector style; no token needed. */
export const CARTO_STYLE_URL = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";

/** Plain background used when the basemap style or tiles fail (Req 8.7). No glyphs or sprites. */
export const FALLBACK_STYLE: StyleSpecification = {
  version: 8,
  name: "Lifeline plain background",
  sources: {},
  layers: [{ id: "background", type: "background", paint: { "background-color": "#0b1220" } }],
};

setWorkerUrl(maplibreWorkerUrl);

const STYLE_TIMEOUT_MS = 10_000;
const OVERLAY_SOURCES = new Set(["tracts", "towns", "pins"]);
const TOOLTIP_W = 288;

interface Props {
  tracts: CapeTracts;
  towns: CapeTowns;
  timeline: CapeTimeline;
  events: TelecomEvents;
  hourIdx: number;
  layer: Layer;
  selectedGeoid: Geoid | null;
  onSelectTract: (geoid: Geoid) => void;
}

interface Hover {
  geoid: Geoid;
  via: "map" | "list";
  left: number;
  top: number;
}

type Basemap = "loading" | "carto" | "fallback";

const asData = (x: unknown) => x as GeoJSONSourceSpecification["data"];
const isHttpUrl = (u: string) => /^https?:\/\//i.test(u);

function addOverlays(map: MapLibreMap, tracts: CapeTracts, towns: CapeTowns, groups: PinGroup[],
                     stops: LegendStop[]): void {
  const beforeLabels = map.getStyle().layers.find((l) => l.type === "symbol")?.id;
  map.addSource("tracts", { type: "geojson", data: asData(tracts), promoteId: "geoid" });
  map.addLayer(
    {
      id: "tract-fill",
      type: "fill",
      source: "tracts",
      paint: { "fill-color": fillColorExpression(stops), "fill-opacity": 0.8 },
    },
    beforeLabels,
  );
  map.addLayer(
    { id: "tract-outline", type: "line", source: "tracts", paint: { "line-color": "#0f172a", "line-width": 0.6 } },
    beforeLabels,
  );
  map.addSource("towns", { type: "geojson", data: asData(towns) });
  map.addLayer({
    id: "town-line",
    type: "line",
    source: "towns",
    paint: { "line-color": "#e2e8f0", "line-width": 1.4, "line-opacity": 0.8, "line-dasharray": [3, 2] },
  });
  map.addLayer({
    id: "tract-highlight",
    type: "line",
    source: "tracts",
    paint: {
      "line-color": ["case", ["boolean", ["feature-state", "selected"], false], "#ffffff", "#7dd3fc"],
      "line-width": ["case", ["boolean", ["feature-state", "selected"], false], 3.5, 2.5],
      "line-opacity": [
        "case",
        ["any", ["boolean", ["feature-state", "selected"], false], ["boolean", ["feature-state", "hover"], false]],
        1,
        0,
      ],
    },
  });
  map.addSource("pins", { type: "geojson", data: asData(pinFeatures(groups)), promoteId: "pin_id" });
  map.addLayer({
    id: "pin-circle",
    type: "circle",
    source: "pins",
    paint: {
      "circle-radius": ["case", ["==", ["get", "kind"], "cape_wide"], 10, 7],
      "circle-color": ["case", ["boolean", ["feature-state", "active"], false], "#fbbf24", "#94a3b8"],
      "circle-stroke-color": "#020617",
      "circle-stroke-width": 2,
      "circle-opacity": ["case", ["boolean", ["feature-state", "active"], false], 1, 0.75],
    },
  });
}

/** Cape map: choropleth (Priority, Need, Lost lifelines), town lines, telecom pins, legend, hover
 *  tooltip, and a keyboard tract list as the non-map alternative (Req 8.1, 8.4 to 8.7, 29.4). */
export function MapView({ tracts, towns, timeline, events, hourIdx, layer, selectedGeoid, onSelectTract }: Props) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const onSelectRef = useRef(onSelectTract);
  const pinReturnFocus = useRef<HTMLElement | null>(null);
  const highlighted = useRef<{ hover: Geoid | null; selected: Geoid | null }>({ hover: null, selected: null });

  const [styleVersion, setStyleVersion] = useState(0); // bumps whenever overlays are (re)added
  const [basemap, setBasemap] = useState<Basemap>("loading");
  const [hover, setHover] = useState<Hover | null>(null);
  const [openPin, setOpenPin] = useState<string | null>(null);
  const [popupEl, setPopupEl] = useState<HTMLDivElement | null>(null);

  useEffect(() => {
    onSelectRef.current = onSelectTract;
  }, [onSelectTract]);

  const hour: HourKey = timeline.hours[hourIdx] ?? "";
  const refs = useMemo(() => tractRefs(tracts), [tracts]);
  const refByGeoid = useMemo(() => new Map(refs.map((r) => [r.geoid, r])), [refs]);
  const values = useMemo(() => layerValues(layer, refs, hourIdx, timeline), [layer, refs, hourIdx, timeline]);
  const stops = useMemo(() => legendStops(layerDomainMax(layer, timeline)), [layer, timeline]);
  const sorted = useMemo(() => sortByValue(refs, values), [refs, values]);
  const groups = useMemo(() => pinGroups(events.events), [events]);
  const eventById = useMemo(() => new Map(events.events.map((e) => [e.id, e])), [events]);
  const activeCount = useMemo(
    () =>
      new Map(
        groups.map((g) => [
          g.key,
          g.eventIds.filter((id) => {
            const ev = eventById.get(id);
            return ev ? isEventActive(ev, hour) : false;
          }).length,
        ]),
      ),
    [groups, eventById, hour],
  );

  // Latest stops for the style.load handler (overlays re-added after a fallback style swap).
  const stopsRef = useRef(stops);
  useEffect(() => {
    stopsRef.current = stops;
  }, [stops]);

  // ------------------------------------------------------------ create the map once
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    let fallback = false;
    let overlaysAdded = false;
    let settled = false; // basemap reached idle; later tile errors keep the dark CARTO background
    let handlersBound = false;

    const map = new MapLibreMap({
      container,
      style: CARTO_STYLE_URL,
      bounds: bboxOf(tracts),
      fitBoundsOptions: { padding: 24 },
      attributionControl: { compact: true },
      dragRotate: false,
      pitchWithRotate: false,
    });
    map.touchZoomRotate.disableRotation();
    map.addControl(new NavigationControl({ showCompass: false }), "top-right");
    mapRef.current = map;

    const useFallback = () => {
      if (fallback) return;
      fallback = true;
      setBasemap("fallback");
      map.setStyle(FALLBACK_STYLE, { diff: false });
    };
    const timer = window.setTimeout(() => {
      if (!overlaysAdded) useFallback();
    }, STYLE_TIMEOUT_MS);

    map.on("error", (e) => {
      const sid = (e as { sourceId?: unknown }).sourceId;
      if (typeof sid === "string" && OVERLAY_SOURCES.has(sid)) {
        console.warn("Map overlay error", e.error);
        return;
      }
      if (fallback || settled) return;
      console.warn("Basemap failed to load; switching to a plain background", e.error);
      useFallback();
    });
    map.once("idle", () => {
      settled = true;
    });

    const tractGeoid = (e: MapLayerMouseEvent): Geoid | null => {
      const f = e.features?.[0];
      const id = f?.id ?? f?.properties?.geoid;
      return id === undefined || id === null ? null : String(id);
    };
    const bindHandlers = () => {
      map.on("mousemove", "tract-fill", (e) => {
        const geoid = tractGeoid(e);
        if (!geoid) return;
        const w = container.clientWidth;
        const left = e.point.x > w / 2 ? Math.max(4, e.point.x - 14 - TOOLTIP_W) : e.point.x + 14;
        setHover({ geoid, via: "map", left, top: e.point.y + 14 });
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", "tract-fill", () => {
        setHover((h) => (h?.via === "map" ? null : h));
        map.getCanvas().style.cursor = "";
      });
      map.on("click", "tract-fill", (e) => {
        if (map.queryRenderedFeatures(e.point, { layers: ["pin-circle"] }).length) return; // pin wins
        const geoid = tractGeoid(e);
        if (geoid) onSelectRef.current(geoid);
      });
      map.on("click", "pin-circle", (e) => {
        const g: unknown = e.features?.[0]?.properties?.group;
        if (typeof g !== "string") return;
        pinReturnFocus.current = null;
        setOpenPin(g);
      });
      map.on("mouseenter", "pin-circle", () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", "pin-circle", () => {
        map.getCanvas().style.cursor = "";
      });
    };

    map.on("style.load", () => {
      addOverlays(map, tracts, towns, groups, stopsRef.current);
      overlaysAdded = true;
      if (!fallback) setBasemap("carto");
      if (!handlersBound) {
        bindHandlers();
        handlersBound = true;
      }
      setStyleVersion((v) => v + 1);
    });

    // Town names as DOM markers: they need no glyphs, so they also show on the fallback background.
    for (const f of towns.features) {
      const el = document.createElement("div");
      el.className = "lifeline-town-label";
      el.textContent = f.properties.name;
      el.setAttribute("aria-hidden", "true");
      new Marker({ element: el }).setLngLat(f.properties.label_point).addTo(map);
    }

    return () => {
      window.clearTimeout(timer);
      map.remove();
      mapRef.current = null;
      highlighted.current = { hover: null, selected: null };
    };
  }, [tracts, towns, groups]);

  const mapReady = (): MapLibreMap | null => {
    const map = mapRef.current;
    return map && styleVersion > 0 && map.getSource("tracts") ? map : null;
  };

  // ------------------------------------------------------------ hour and layer -> feature state
  useEffect(() => {
    const map = mapReady();
    if (!map) return;
    for (const [geoid, value] of values) map.setFeatureState({ source: "tracts", id: geoid }, { value });
  }, [values, styleVersion]);

  useEffect(() => {
    const map = mapReady();
    if (!map) return;
    map.setPaintProperty("tract-fill", "fill-color", fillColorExpression(stops));
  }, [stops, styleVersion]);

  useEffect(() => {
    const map = mapReady();
    if (!map) return;
    for (const g of groups) {
      const active = (activeCount.get(g.key) ?? 0) > 0;
      for (const id of g.eventIds) map.setFeatureState({ source: "pins", id: `${id}@${g.key}` }, { active });
    }
  }, [groups, activeCount, styleVersion]);

  const hoverGeoid = hover?.geoid ?? null;
  useEffect(() => {
    const map = mapReady();
    if (!map) return;
    const prev = highlighted.current;
    const next = { hover: hoverGeoid, selected: selectedGeoid };
    const touched = new Set([prev.hover, prev.selected, next.hover, next.selected]);
    for (const g of touched) {
      if (!g) continue;
      map.setFeatureState({ source: "tracts", id: g }, { hover: g === next.hover, selected: g === next.selected });
    }
    highlighted.current = next;
  }, [hoverGeoid, selectedGeoid, styleVersion]);

  // ------------------------------------------------------------ telecom popup
  const openGroup = openPin ? groups.find((g) => g.key === openPin) ?? null : null;
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !openGroup) return;
    const el = document.createElement("div");
    const popup = new Popup({ className: "lifeline-popup", maxWidth: "360px", focusAfterOpen: true })
      .setLngLat([openGroup.lon, openGroup.lat])
      .setDOMContent(el)
      .addTo(map);
    setPopupEl(el);
    const onClose = () => {
      setOpenPin((cur) => (cur === openGroup.key ? null : cur));
      pinReturnFocus.current?.focus();
    };
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") popup.remove();
    };
    popup.on("close", onClose);
    popup.getElement().addEventListener("keydown", onKey);
    return () => {
      popup.off("close", onClose);
      popup.getElement()?.removeEventListener("keydown", onKey);
      popup.remove();
      setPopupEl(null);
    };
  }, [openGroup]);

  // ------------------------------------------------------------ tooltip content
  const hoverRef = hover ? refByGeoid.get(hover.geoid) : undefined;
  const hoverTown = hoverRef ? tractTown(hoverRef, timeline) : "";
  const hoverNotes = hoverRef ? tooltipNotes(layer, hoverTown, hourIdx, timeline, towns) : [];
  const label = layerLabel(layer);
  const mapLabel = `Cape Cod map: ${label} by census tract at ${formatHour(hour)}, local time. ` +
    "The tract list below the map offers the same values by keyboard.";

  return (
    <div className="flex flex-col gap-3">
      <div
        ref={wrapperRef}
        role="region"
        aria-label={mapLabel}
        className="relative h-[58vh] min-h-96 overflow-hidden rounded-md border border-slate-800 bg-[#0b1220]"
      >
        <div ref={containerRef} className="absolute inset-0" />

        {hover && hoverRef && (
          <div
            role="tooltip"
            className="pointer-events-none absolute z-10 rounded-md border border-slate-500 bg-slate-950/95 px-3 py-2 text-sm text-slate-100 shadow-lg"
            style={{
              width: TOOLTIP_W,
              left: hover.via === "map" ? hover.left : 8,
              top: hover.via === "map" ? hover.top : 8,
            }}
          >
            <p className="font-semibold">
              {shortTractName(hoverRef.name)}, {hoverTown}
            </p>
            <p className="tabular-nums">{formatLayerValue(layer, values.get(hoverRef.geoid))}</p>
            {hoverNotes.map((n) => (
              <p key={n} className="mt-1 text-xs text-slate-300">
                {n}
              </p>
            ))}
          </div>
        )}

        {basemap === "fallback" && (
          <p
            role="status"
            className="absolute left-1/2 top-2 z-10 -translate-x-1/2 rounded bg-slate-900/95 px-2 py-1 text-xs text-slate-200"
          >
            Basemap unavailable. Showing tracts on a plain background.
          </p>
        )}

        <Legend layer={layer} stops={stops} />
      </div>

      <div className="grid gap-3 lg:grid-cols-[3fr_2fr]">
        <TractList
          rows={sorted}
          layer={layer}
          hour={hour}
          stops={stops}
          selectedGeoid={selectedGeoid}
          onFocusTract={(geoid) => setHover({ geoid, via: "list", left: 8, top: 8 })}
          onBlurTract={() => setHover((h) => (h?.via === "list" ? null : h))}
          onSelect={onSelectTract}
        />
        <PinList
          groups={groups}
          activeCount={activeCount}
          openPin={openPin}
          onOpen={(key, trigger) => {
            pinReturnFocus.current = trigger;
            setOpenPin(key);
          }}
        />
      </div>

      {popupEl && openGroup &&
        createPortal(
          <PinPopupContent
            group={openGroup}
            events={openGroup.eventIds.map((id) => eventById.get(id)).filter((e): e is TelecomEvent => !!e)}
            hour={hour}
          />,
          popupEl,
        )}
    </div>
  );
}

// ---------------------------------------------------------------- legend

function swatchFor(stops: readonly LegendStop[], v: number | null): string {
  if (v === null) return "#475569";
  let color = stops[0]?.color ?? "#475569";
  for (const s of stops) if (v >= s.value) color = s.color;
  return color;
}

function Legend({ layer, stops }: { layer: Layer; stops: LegendStop[] }) {
  const first = stops[0]?.label ?? "0.00";
  const last = stops[stops.length - 1]?.label ?? "1.00";
  return (
    <section
      aria-label={`Legend: ${layerLabel(layer)} from ${first} to ${last}`}
      className="absolute bottom-2 left-2 z-10 rounded-md border border-slate-700 bg-slate-950/90 px-3 py-2 text-xs text-slate-200"
    >
      <p className="font-semibold text-slate-100">
        {layerLabel(layer)}, {first} to {last}
      </p>
      <ol className="mt-1 flex">
        {stops.map((s) => (
          <li key={s.label} className="flex w-11 flex-col items-center">
            <span aria-hidden="true" className="block h-3 w-full border border-slate-950" style={{ background: s.color }} />
            <span className="mt-0.5 tabular-nums">{s.label}</span>
          </li>
        ))}
      </ol>
      <p className="mt-1 text-slate-300">Darker is lower, brighter is higher. Grey: no value.</p>
      <p className="mt-1 flex items-center gap-1.5 text-slate-300">
        <span aria-hidden="true" className="inline-block h-2.5 w-2.5 rounded-full bg-amber-400" />
        Telecom event active at this hour
        <span aria-hidden="true" className="ml-2 inline-block h-2.5 w-2.5 rounded-full bg-slate-400" />
        Not active
      </p>
    </section>
  );
}

// ---------------------------------------------------------------- keyboard tract list

const ROW_BTN =
  "grid w-full grid-cols-[1.75rem_0.75rem_1fr_auto] items-center gap-2 rounded px-2 py-1 text-left text-sm " +
  "text-slate-100 hover:bg-slate-800 focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-sky-300";

interface TractListProps {
  rows: SortedTract[];
  layer: Layer;
  hour: HourKey;
  stops: LegendStop[];
  selectedGeoid: Geoid | null;
  onFocusTract: (geoid: Geoid) => void;
  onBlurTract: () => void;
  onSelect: (geoid: Geoid) => void;
}

/** One tab stop; arrow keys, Home and End move between tracts; Enter or Space opens one. */
function TractList({ rows, layer, hour, stops, selectedGeoid, onFocusTract, onBlurTract, onSelect }: TractListProps) {
  const headingId = useId();
  const hintId = useId();
  const [active, setActive] = useState(0);
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const activeIdx = Math.min(active, Math.max(0, rows.length - 1));

  const move = (i: number) => {
    const j = Math.max(0, Math.min(rows.length - 1, i));
    setActive(j);
    buttons.current[j]?.focus();
  };
  const onKey = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    const targets: Record<string, number> = {
      ArrowDown: i + 1, ArrowUp: i - 1, Home: 0, End: rows.length - 1, PageDown: i + 10, PageUp: i - 10,
    };
    const to = targets[e.key];
    if (to === undefined) return;
    e.preventDefault();
    move(to);
  };

  return (
    <section aria-labelledby={headingId} className="rounded-md border border-slate-800 bg-slate-900/70 p-2">
      <h2 id={headingId} className="px-1 text-sm font-semibold text-slate-200">
        Tract list: {layerLabel(layer)} at {formatHour(hour)}, highest first
      </h2>
      <p id={hintId} className="px-1 pb-1 text-xs text-slate-400">
        Up and down arrows move between tracts. Enter selects a tract.
      </p>
      <ul aria-labelledby={headingId} aria-describedby={hintId} className="max-h-64 overflow-y-auto">
        {rows.map((r, i) => {
          const selected = r.ref.geoid === selectedGeoid;
          return (
            <li key={r.ref.geoid}>
              <button
                ref={(el) => {
                  buttons.current[i] = el;
                }}
                type="button"
                tabIndex={i === activeIdx ? 0 : -1}
                aria-current={selected ? "true" : undefined}
                onFocus={() => {
                  setActive(i);
                  onFocusTract(r.ref.geoid);
                }}
                onBlur={onBlurTract}
                onClick={() => onSelect(r.ref.geoid)}
                onKeyDown={(e) => onKey(e, i)}
                className={`${ROW_BTN} ${selected ? "bg-slate-800 ring-1 ring-white/70" : ""}`}
              >
                <span className="tabular-nums text-slate-400">{i + 1}</span>
                <span aria-hidden="true" className="h-3 w-3 rounded-sm" style={{ background: swatchFor(stops, r.value) }} />
                <span>
                  {r.ref.town} <span className="text-slate-300">{shortTractName(r.ref.name)}</span>
                </span>
                <span className="font-semibold tabular-nums">{formatLayerValue(layer, r.value)}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

// ---------------------------------------------------------------- telecom pins (keyboard + popup)

interface PinListProps {
  groups: PinGroup[];
  activeCount: Map<string, number>;
  openPin: string | null;
  onOpen: (key: string, trigger: HTMLElement) => void;
}

function PinList({ groups, activeCount, openPin, onOpen }: PinListProps) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="rounded-md border border-slate-800 bg-slate-900/70 p-2">
      <h2 id={headingId} className="px-1 text-sm font-semibold text-slate-200">
        Observed telecom events (map pins)
      </h2>
      <ul className="mt-1 space-y-0.5">
        {groups.map((g) => {
          const n = g.eventIds.length;
          const a = activeCount.get(g.key) ?? 0;
          return (
            <li key={g.key}>
              <button
                type="button"
                aria-expanded={openPin === g.key}
                onClick={(e) => onOpen(g.key, e.currentTarget)}
                className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-sm text-slate-100 hover:bg-slate-800 focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-sky-300"
              >
                <span
                  aria-hidden="true"
                  className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${a > 0 ? "bg-amber-400" : "bg-slate-400"}`}
                />
                <span className="flex-1">
                  {g.caption}: {n} {n === 1 ? "event" : "events"}
                </span>
                <span className="text-xs text-slate-300">{a > 0 ? `${a} active at this hour` : "none active"}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function PinPopupContent({ group, events, hour }: { group: PinGroup; events: TelecomEvent[]; hour: HourKey }) {
  return (
    <div className="text-sm text-slate-100">
      <h3 className="pr-6 font-semibold">
        {group.caption}: {events.length} observed telecom {events.length === 1 ? "event" : "events"}
      </h3>
      <ul
        tabIndex={0}
        aria-label={`Telecom events at ${group.caption}`}
        className="mt-2 max-h-72 space-y-3 overflow-y-auto pr-1 focus-visible:outline-2 focus-visible:outline-sky-300"
      >
        {events.map((ev) => {
          const active = isEventActive(ev, hour);
          const end = ev.end_local
            ? formatHour(ev.end_local)
            : `${formatHour(ev.end_effective)}${ev.end_label ? ` (${ev.end_label})` : ""}`;
          return (
            <li key={ev.id} className="border-t border-slate-700 pt-2 first:border-t-0 first:pt-0">
              <p className="font-semibold">{humanize(ev.system)}</p>
              <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
                <dt className="text-slate-400">Status</dt>
                <dd>{humanize(ev.status)}</dd>
                <dt className="text-slate-400">Affects</dt>
                <dd>{humanize(ev.affects)}</dd>
                <dt className="text-slate-400">Area</dt>
                <dd>{ev.town_or_area}</dd>
                <dt className="text-slate-400">Start</dt>
                <dd>{formatHour(ev.start_local)}</dd>
                <dt className="text-slate-400">End</dt>
                <dd>{end}</dd>
                <dt className="text-slate-400">This hour</dt>
                <dd>{active ? "Active" : "Not active"}</dd>
                <dt className="text-slate-400">Source</dt>
                <dd>
                  {isHttpUrl(ev.source_url) ? (
                    <a
                      href={ev.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sky-300 underline hover:text-sky-200 focus-visible:outline-2 focus-visible:outline-sky-300"
                    >
                      {ev.source_name}
                      <span className="sr-only"> (opens in a new tab)</span>
                    </a>
                  ) : (
                    ev.source_name
                  )}
                </dd>
              </dl>
              {!ev.drives_reach_flag && (
                <p className="mt-1 text-xs text-slate-400">Map pin and briefing context only. It does not set the Reach channel.</p>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
