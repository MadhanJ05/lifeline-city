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
  NO_VALUE_COLOR,
  pinFeatures,
  pinGroups,
  RAMPS,
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
import "../styles/map.css";

/** CARTO dark-matter (no labels) vector style; no token needed. Town names come from our own markers. */
export const CARTO_STYLE_URL = "https://basemaps.cartocdn.com/gl/dark-matter-nolabels-gl-style/style.json";

/** Plain background used when the basemap style or tiles fail (Req 8.7). No glyphs or sprites. */
export const FALLBACK_STYLE: StyleSpecification = {
  version: 8,
  name: "Lifeline plain background",
  sources: {},
  layers: [{ id: "background", type: "background", paint: { "background-color": "#0A0E13" } }],
};

setWorkerUrl(maplibreWorkerUrl);

const STYLE_TIMEOUT_MS = 10_000;
/** fitBounds padding that keeps the Cape clear of the floating panels (left list, top bar, time bar). */
const FIT_PADDING = { left: 400, right: 40, top: 90, bottom: 130 } as const;
/** Same, while the 440px tract drawer is open on the right. */
const FIT_PADDING_DRAWER = { ...FIT_PADDING, right: 480 } as const;
/** maplibre-gl.css (unlayered) sets .maplibregl-map { position: relative }, which beats Tailwind's
 *  layered `absolute inset-0` and collapses the container to 0px. Inline styles win over both. */
const FILL_PARENT = { position: "absolute", inset: 0 } as const;
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
  /** Left-panel element that hosts the collapsed "All tracts" and "Telecom reports" lists (portal). */
  listsContainer?: HTMLElement | null;
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
      paint: { "fill-color": fillColorExpression(stops), "fill-opacity": 0.78 },
    },
    beforeLabels,
  );
  map.addLayer(
    {
      id: "tract-outline",
      type: "line",
      source: "tracts",
      paint: { "line-color": "rgba(255,255,255,0.12)", "line-width": 0.5 },
    },
    beforeLabels,
  );
  map.addSource("towns", { type: "geojson", data: asData(towns) });
  map.addLayer({
    id: "town-line",
    type: "line",
    source: "towns",
    paint: { "line-color": "rgba(255,255,255,0.35)", "line-width": 1.2 },
  });
  map.addLayer({
    id: "tract-highlight",
    type: "line",
    source: "tracts",
    paint: {
      // Hover: 1.5px --text. Selected: 2.5px --accent (selected wins when both apply).
      "line-color": ["case", ["boolean", ["feature-state", "selected"], false], "#F2A541", "#E9EEF3"],
      "line-width": ["case", ["boolean", ["feature-state", "selected"], false], 2.5, 1.5],
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
      // Active at the hour: --accent fill, dark ring. Inactive: transparent fill, --text-faint ring.
      "circle-radius": 7,
      "circle-color": ["case", ["boolean", ["feature-state", "active"], false], "#F2A541", "rgba(0,0,0,0)"],
      "circle-stroke-color": ["case", ["boolean", ["feature-state", "active"], false], "#10151C", "#5C6876"],
      "circle-stroke-width": 2,
    },
  });
}

/** Small count badge next to pins that hold several events (e.g. the Cape-wide marker). DOM markers
 *  need no glyphs, so they also show on the fallback background. aria-hidden: the Telecom reports
 *  list is the accessible path to the same counts. */
function addPinBadges(map: MapLibreMap, groups: readonly PinGroup[]): Marker[] {
  return groups
    .filter((g) => g.eventIds.length > 1)
    .map((g) => {
      const el = document.createElement("div");
      el.className = "lifeline-pin-badge";
      el.textContent = String(g.eventIds.length);
      el.setAttribute("aria-hidden", "true");
      return new Marker({ element: el, anchor: "bottom-left", offset: [4, -4] }).setLngLat([g.lon, g.lat]).addTo(map);
    });
}

/** Cape map: choropleth (Priority, Need, Lost lifelines), town lines, telecom pins, legend, hover
 *  tooltip, and a keyboard tract list as the non-map alternative (Req 8.1, 8.4 to 8.7, 29.4). */
export function MapView({
  tracts, towns, timeline, events, hourIdx, layer, selectedGeoid, onSelectTract, listsContainer,
}: Props) {
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

  const drawerOpen = selectedGeoid !== null && tracts.features.some((f) => f.properties.geoid === selectedGeoid);
  const fitPadding = drawerOpen ? FIT_PADDING_DRAWER : FIT_PADDING;
  const fitPaddingRef = useRef(fitPadding);
  fitPaddingRef.current = fitPadding;

  useEffect(() => {
    onSelectRef.current = onSelectTract;
  }, [onSelectTract]);

  const hour: HourKey = timeline.hours[hourIdx] ?? "";
  const refs = useMemo(() => tractRefs(tracts), [tracts]);
  const refByGeoid = useMemo(() => new Map(refs.map((r) => [r.geoid, r])), [refs]);
  const values = useMemo(() => layerValues(layer, refs, hourIdx, timeline), [layer, refs, hourIdx, timeline]);
  const stops = useMemo(() => legendStops(layerDomainMax(layer, timeline), RAMPS[layer]), [layer, timeline]);
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
      fitBoundsOptions: { padding: fitPaddingRef.current },
      attributionControl: { compact: true },
      dragRotate: false,
      pitchWithRotate: false,
    });
    map.touchZoomRotate.disableRotation();
    map.addControl(new NavigationControl({ showCompass: false }), "top-left");
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
      // The container may have had no size when the map was created; measure again and re-fit.
      map.resize();
      map.fitBounds(bboxOf(tracts), { padding: fitPaddingRef.current, duration: 0 });
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
    addPinBadges(map, groups);

    return () => {
      window.clearTimeout(timer);
      map.remove();
      mapRef.current = null;
      highlighted.current = { hover: null, selected: null };
    };
  }, [tracts, towns, groups]);

  // Re-fit when the drawer opens or closes so the Cape stays in the uncovered area.
  // duration 0: no motion on map updates (design.md).
  const firstFit = useRef(true);
  useEffect(() => {
    if (firstFit.current) {
      firstFit.current = false; // the initial fit happens at creation and on style.load
      return;
    }
    const map = mapRef.current;
    if (!map) return;
    map.fitBounds(bboxOf(tracts), { padding: drawerOpen ? FIT_PADDING_DRAWER : FIT_PADDING, duration: 0 });
  }, [drawerOpen, tracts]);

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
    "The All tracts list in the left panel offers the same values by keyboard.";

  return (
    <>
      <div
        ref={wrapperRef}
        role="region"
        aria-label={mapLabel}
        className="lifeline-map absolute inset-0 overflow-hidden bg-bg"
        style={FILL_PARENT}
      >
        <div ref={containerRef} className="absolute inset-0" style={FILL_PARENT} />

        {hover && hoverRef && (
          <div
            role="tooltip"
            className="pointer-events-none absolute z-10 rounded-card border border-line-strong bg-panel-solid px-3 py-2 text-[13px] text-fg shadow-panel"
            style={{
              width: TOOLTIP_W,
              left: hover.via === "map" ? hover.left : 8,
              top: hover.via === "map" ? hover.top : 8,
            }}
          >
            <p className="font-semibold">
              {hoverTown} <span className="font-normal text-muted">{shortTractName(hoverRef.name)}</span>
            </p>
            <p className="mt-0.5 font-mono tabular-nums">{formatLayerValue(layer, values.get(hoverRef.geoid))}</p>
            {hoverNotes.map((n) => (
              <p key={n} className="mt-1 text-[11px] leading-snug text-muted">
                {n}
              </p>
            ))}
          </div>
        )}

        {basemap === "fallback" && (
          <p
            role="status"
            className="absolute left-1/2 top-[76px] z-10 -translate-x-1/2 rounded-full border border-line bg-panel-solid px-3 py-1 text-xs text-fg"
          >
            Basemap unavailable. Showing tracts on a plain background.
          </p>
        )}

        <Legend layer={layer} stops={stops} />
      </div>

      {listsContainer &&
        createPortal(
          <div className="flex flex-col gap-2">
            <details className="group rounded-card border border-line">
              <summary className={SUMMARY}>All tracts ({sorted.length})</summary>
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
            </details>
            <details className="group rounded-card border border-line">
              <summary className={SUMMARY}>Telecom reports ({events.events.length})</summary>
              <PinList
                groups={groups}
                activeCount={activeCount}
                openPin={openPin}
                onOpen={(key, trigger) => {
                  pinReturnFocus.current = trigger;
                  setOpenPin(key);
                }}
              />
            </details>
          </div>,
          listsContainer,
        )}

      {popupEl && openGroup &&
        createPortal(
          <PinPopupContent
            group={openGroup}
            events={openGroup.eventIds.map((id) => eventById.get(id)).filter((e): e is TelecomEvent => !!e)}
            hour={hour}
          />,
          popupEl,
        )}
    </>
  );
}

const SUMMARY =
  "cursor-pointer select-none rounded-card px-2.5 py-2 text-xs font-medium text-muted hover:bg-line hover:text-fg " +
  "group-open:text-fg";

// ---------------------------------------------------------------- legend

function swatchFor(stops: readonly LegendStop[], v: number | null): string {
  if (v === null) return NO_VALUE_COLOR;
  let color = stops[0]?.color ?? NO_VALUE_COLOR;
  for (const s of stops) if (v >= s.value) color = s.color;
  return color;
}

/** Compact legend chip: layer name, the ramp as discrete swatches (no gradient), min/max as text,
 *  the no-value swatch and the telecom pin key. */
function Legend({ layer, stops }: { layer: Layer; stops: LegendStop[] }) {
  const first = stops[0]?.label ?? "0.00";
  const last = stops[stops.length - 1]?.label ?? "1.00";
  return (
    <section
      aria-label={`Legend: ${layerLabel(layer)} from ${first} to ${last}`}
      className="glass lifeline-legend absolute bottom-[116px] left-[calc(min(360px,28vw)+24px)] z-10 w-[232px] px-3 py-2.5 text-[11px] text-muted"
    >
      <p className="lifeline-legend-label">
        {layerLabel(layer)}
        <span className="sr-only">, {first} to {last}</span>
      </p>
      <ol className="mt-1.5 flex h-2 overflow-hidden rounded-full" aria-label={`${stops.length} color steps`}>
        {stops.map((s) => (
          <li key={s.label} className="h-full flex-1" style={{ background: s.color }}>
            <span className="sr-only">{s.label}</span>
          </li>
        ))}
      </ol>
      <p aria-hidden="true" className="mt-1 flex justify-between font-mono tabular-nums text-fg">
        <span>{first}</span>
        <span>{last}</span>
      </p>
      <p className="mt-1.5 flex items-center gap-1.5">
        <span aria-hidden="true" className="inline-block h-2 w-3 rounded-sm" style={{ background: NO_VALUE_COLOR }} />
        Darker is lower, brighter is higher. Near-black: no value.
      </p>
      <p className="mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-1">
        <span aria-hidden="true" className="lifeline-pin-key lifeline-pin-key--active" />
        Telecom event active at this hour
        <span aria-hidden="true" className="lifeline-pin-key ml-2" />
        Not active
      </p>
    </section>
  );
}

// ---------------------------------------------------------------- keyboard tract list

const ROW_BTN =
  "grid w-full grid-cols-[1.75rem_0.75rem_1fr_auto] items-center gap-2 rounded-card px-2 py-1 text-left text-[13px] " +
  "text-fg hover:bg-line focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-accent";

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
    <section aria-labelledby={headingId} className="px-1 pb-2">
      <h2 id={headingId} className="px-1 text-xs font-semibold text-fg">
        Tract list: {layerLabel(layer)} at {formatHour(hour)}, highest first
      </h2>
      <p id={hintId} className="px-1 pb-1 text-xs text-muted">
        Up and down arrows move between tracts. Enter selects a tract.
      </p>
      <ul aria-labelledby={headingId} aria-describedby={hintId} className="max-h-72 overflow-y-auto">
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
                className={`${ROW_BTN} ${selected ? "bg-line ring-1 ring-accent" : ""}`}
              >
                <span className="font-mono tabular-nums text-faint">{i + 1}</span>
                <span aria-hidden="true" className="h-3 w-3 rounded-sm" style={{ background: swatchFor(stops, r.value) }} />
                <span>
                  {r.ref.town} <span className="text-muted">{shortTractName(r.ref.name)}</span>
                </span>
                <span className="font-mono tabular-nums">{formatLayerValue(layer, r.value)}</span>
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
    <section aria-labelledby={headingId} className="px-1 pb-2">
      <h2 id={headingId} className="px-1 text-xs font-semibold text-fg">
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
                className="flex w-full items-center gap-2 rounded-card px-2 py-1 text-left text-[13px] text-fg hover:bg-line focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-accent"
              >
                <span
                  aria-hidden="true"
                  className={`lifeline-pin-key shrink-0 ${a > 0 ? "lifeline-pin-key--active" : ""}`}
                />
                <span className="flex-1">
                  {g.caption}: {n} {n === 1 ? "event" : "events"}
                </span>
                <span className="text-xs text-muted">{a > 0 ? `${a} active at this hour` : "none active"}</span>
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
    <div className="text-[13px] text-fg">
      <h3 className="pr-6 text-[15px] font-semibold">
        {group.caption}: {events.length} observed telecom {events.length === 1 ? "event" : "events"}
      </h3>
      <ul
        tabIndex={0}
        aria-label={`Telecom events at ${group.caption}`}
        className="mt-2 max-h-72 space-y-3 overflow-y-auto pr-1 focus-visible:outline-2 focus-visible:outline-accent"
      >
        {events.map((ev) => {
          const active = isEventActive(ev, hour);
          const end = ev.end_local
            ? formatHour(ev.end_local)
            : `${formatHour(ev.end_effective)}${ev.end_label ? ` (${ev.end_label})` : ""}`;
          return (
            <li key={ev.id} className="border-t border-line pt-2 first:border-t-0 first:pt-0">
              <p className="font-semibold">{humanize(ev.system)}</p>
              <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
                <dt className="text-muted">Status</dt>
                <dd>{humanize(ev.status)}</dd>
                <dt className="text-muted">Affects</dt>
                <dd>{humanize(ev.affects)}</dd>
                <dt className="text-muted">Area</dt>
                <dd>{ev.town_or_area}</dd>
                <dt className="text-muted">Start</dt>
                <dd className="font-mono">{formatHour(ev.start_local)}</dd>
                <dt className="text-muted">End</dt>
                <dd className="font-mono">{end}</dd>
                <dt className="text-muted">This hour</dt>
                <dd className={active ? "text-accent" : "text-muted"}>{active ? "Active" : "Not active"}</dd>
                <dt className="text-muted">Source</dt>
                <dd>
                  {isHttpUrl(ev.source_url) ? (
                    <a
                      href={ev.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-accent underline underline-offset-2 hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
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
                <p className="mt-1 text-xs text-muted">Map pin and briefing context only. It does not set the Reach channel.</p>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
