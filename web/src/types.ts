// Types for every file in data/processed/ and every API response model.
// Sources of truth: pipeline/export.py (file shapes), api/data.py (pydantic models),
// api/main.py (TractDetail, Components, HouseholdStatus, content endpoint) and api/reach.py.
// All hour keys are "YYYY-MM-DDTHH:MM" in America/New_York local time.

export type HourKey = string;
export type Geoid = string;
export type Town = string;

export type Lang = "en" | "pt" | "es";
export const LANGS: readonly Lang[] = ["en", "pt", "es"];

export type Indicator =
  | "seniors_alone"
  | "disability"
  | "limited_english"
  | "no_vehicle"
  | "renter"
  | "elec_dependent";
export type Component = "out_pct" | "hours_dark" | "wires" | "telecom";
export type TelecomRule = "none" | "observed" | "modeled" | "both";
export type Channel = "sms" | "door_knock";

// ---------------------------------------------------------------- shared pieces

/** Why_Chip or briefing claim: every number carries the metrics field it came from. */
export interface Chip {
  text: string;
  field: string;
  value: number;
}
export type Claim = Chip;

export interface QueueRow {
  rank: number;
  geoid: Geoid;
  town: Town;
  priority: number;
  need_t: number;
  channel: Channel;
  why_chips: Chip[];
}

export interface NeedValue {
  raw: number | null;
  pct: number | null;
  unit: "share" | "per_1000";
}

/** Minimal GeoJSON geometry types (no extra dependency). */
export type Position = [number, number] | number[];
export type Geometry =
  | { type: "Polygon"; coordinates: Position[][] }
  | { type: "MultiPolygon"; coordinates: Position[][][] };

export interface Feature<P> {
  type: "Feature";
  properties: P;
  geometry: Geometry;
}

export interface FeatureCollection<P> {
  type: "FeatureCollection";
  tz: string;
  features: Feature<P>[];
}

// ---------------------------------------------------------------- cape_tracts.geojson

export interface TractProps {
  geoid: Geoid;
  name: string;
  town: Town;
  town_assignment: "centroid" | "nearest";
  population: number;
  need_t: number;
  need: Partial<Record<Indicator, NeedValue>>;
  need_missing: Indicator[];
  empower_masked: boolean;
  households_n: number;
  customers: number;
  customers_label: string | null;
  empower?: { dme_allocated: number; medicare_benes_allocated: number };
}
export type CapeTracts = FeatureCollection<TractProps>;

// ---------------------------------------------------------------- cape_towns.geojson

export interface TownProps {
  name: Town;
  customers: number;
  customers_source: string;
  /** "Estimated from ACS housing units." for Sandwich and Chatham, else null. */
  customers_label: string | null;
  /** 0 means no town reports: out_pct is the Cape-wide share (see NO_TOWN_REPORTS_LABEL). */
  anchor_count: number;
  label_point: [number, number];
}
export type CapeTowns = FeatureCollection<TownProps>;

// ---------------------------------------------------------------- cape_timeline.json

/** Town-hour components; every array is aligned with CapeTimeline.hours. */
export interface TownSeries {
  out_pct: number[];
  hours_dark: number[];
  wires_raw: number[];
  wires: number[];
  telecom: (0 | 1)[];
  telecom_rule: TelecomRule[];
  telecom_event_ids: string[][];
  contrib: Record<Component, number[]>;
  lifelines: number[];
  pinned: boolean[];
  lower_bound: (number | null)[];
  customers_label: string | null;
}

export interface TractSeries {
  town: Town;
  priority: number[];
  channel: Channel[];
  rank: (number | null)[];
}

export interface CapeTimeline {
  tz: string;
  hours: HourKey[];
  key_demo_hours: HourKey[];
  weights: Record<Component, number>;
  hours_dark_cap: number;
  dark_threshold: number;
  telecom_model: { out_pct_threshold: number; consecutive_hours: number };
  labels: Record<string, string>; // reconstructed, modeled_telecom, acs_customers
  provenance: Record<string, string>; // out_pct, hours_dark
  cape_total: number[];
  towns: Record<Town, TownSeries>;
  tracts: Record<Geoid, TractSeries>;
  queue: Record<HourKey, QueueRow[]>;
}

// ---------------------------------------------------------------- telecom_events.json

export interface TelecomPin {
  kind: "town" | "cape_wide";
  town: Town | null;
  caption: string;
  lon: number;
  lat: number;
}

export interface TelecomEvent {
  id: string;
  system: string;
  status: string;
  affects: "residents" | "responders";
  start_local: string;
  end_local: string | null;
  end_effective: string;
  end_assumed: boolean;
  /** "Assumed duration: 12 hours (no end time reported)" when end_assumed, else null. */
  end_label: string | null;
  source_name: string;
  source_url: string;
  drives_reach_flag: boolean;
  town_or_area: string;
  areas: string[];
  matched_towns: Town[];
  note: string | null;
  pins: TelecomPin[];
}

export interface TelecomEvents {
  tz: string;
  events: TelecomEvent[];
}

// ---------------------------------------------------------------- content.json (Content_Cache)

export interface SmsText {
  text: string;
  encoding: "gsm7" | "ucs2";
  units: number;
  segments: 1 | 2;
}

export interface RadioText {
  text: string;
  words: number;
}

export interface Briefing {
  kind: "verified" | "template";
  headline: string;
  claims: Claim[];
  action: string;
  verifier: "pass" | "regenerated" | "fallback";
}

export interface HelpLine {
  number: string;
  sentence: Record<Lang, string>;
}

export type SmsKind = "checkin" | "confirm" | "reprompt";

export interface ContentCache {
  tz: string;
  region: string;
  help_line: HelpLine;
  sms: Record<Town, Partial<Record<Lang, Record<SmsKind, SmsText>>>>;
  doorstep: Record<Town, Partial<Record<Lang, string>>>;
  radio: Record<HourKey, Record<Town, Partial<Record<Lang, RadioText>>>>;
  briefings: Record<HourKey, Record<Geoid, Briefing>>;
}

// ---------------------------------------------------------------- households.json, responders.json (synthetic)

export interface Household {
  id: string;
  geoid: Geoid;
  town: Town;
  number: number;
  label: string; // "Simulated household #N"
  lang: Lang;
  lon: number;
  lat: number;
  is_operator: boolean;
  synthetic: true;
}

export interface Responder {
  id: string;
  town: Town;
  role: string;
  label: string; // role label, e.g. "Falmouth COA driver (Simulated)"
  synthetic: true;
}

export interface HouseholdsFile {
  tz: string;
  households: Household[];
}

export interface RespondersFile {
  tz: string;
  responders: Responder[];
}

// ---------------------------------------------------------------- scale_catalog.json

export interface CatalogEntry {
  id: string;
  place: string;
  hazard: string;
  hazard_label: string;
  tier: 1 | 2;
  mode: "live" | "preview";
  lost_lifelines_inputs: string[];
  need_inputs: string[];
  data_endpoint?: string; // live entries only
  label?: string; // "Configuration preview" on previews; previews never carry scores
}

export interface ScaleCatalog {
  tz: string;
  entries: CatalogEntry[];
}

// ---------------------------------------------------------------- sources.json

export interface SourceInput {
  file: string;
  row: number;
  source_name: string;
  source_url: string;
  used_in: string[];
}

export interface WorkbookInput {
  file: string;
  sheet: string;
  source_name: string;
  source_url: string;
  used_in: string[];
  note?: string;
}

export interface Sources {
  tz: string;
  provenance_labels: Record<string, string>;
  inputs: SourceInput[];
  workbook_inputs: WorkbookInput[];
  excluded: { file: string; row: number; reason: string }[];
  tab5_unmatched_towns: { town: string; calls: number }[];
  tab5_blank_received_calls: number;
  unmatched_hours: { hour: HourKey; unmatched_customers: number }[];
  towns_without_anchors: Town[];
  customer_count_sources: Record<Town, string>;
  tract_town_nearest: { geoid: Geoid; town: Town }[];
  assumptions: { key: string; value: string | number; label: string }[];
  fetches: { name: string; url: string; vintage?: number }[];
  acs_vintage: Record<string, number>;
  acs_variables: { geo: string; id: string; label: string; vintage: number }[];
  empower_masked_zips: string[];
}

// ---------------------------------------------------------------- verifier_log.json

export interface VerifierLog {
  tz: string;
  counts: { pass: number; regenerated: number; fallback: number };
  template_briefings: { checked: number; pass: number };
  outreach: Record<"sms" | "doorstep" | "radio" | "why_chip", { checked: number }>;
  failures: { kind: "briefing"; key: string; attempt: 1 | 2; reasons: string[] }[];
  llm_step: "ran" | "no_llm" | "no_key" | "skipped_key_hours";
  key_hour_channels: Record<
    HourKey,
    { sms: { count: number; towns: Town[] }; door_knock: { count: number; towns: Town[] } }
  >;
  has_mixed_hour: boolean;
}

// ---------------------------------------------------------------- boston_voice.geojson (optional block)

export interface BostonProps {
  geoid: Geoid;
  name: string;
  population: number;
  need_t: number;
  need: Partial<Record<Indicator, NeedValue>>;
  need_missing: Indicator[];
  observed: number;
  expected: number;
  ratio: number;
  p: number;
  acute: number;
  acute_pct: number;
  rate_pc: number;
  structural: number;
  silence: number;
  priority: number;
  rank: number;
}

export interface BostonVoice extends FeatureCollection<BostonProps> {
  metadata?: Record<string, unknown> | null;
}

// ---------------------------------------------------------------- API-only models

/** GET /api/health */
export interface Health {
  ok: boolean;
  boston_voice: boolean;
  sms_mode: "simulator" | "twilio";
}

/** GET /api/hours */
export interface Hours {
  tz: string;
  hours: HourKey[];
  key_demo_hours: HourKey[];
}

/** api/main.py Components */
export interface Components {
  out_pct: number;
  hours_dark: number;
  wires: number; // percentile rank across the 15 towns at the hour
  wires_raw: number; // urgent downed-wire calls per 1,000 customers, cumulative
  telecom: 0 | 1;
  pinned: boolean;
  lower_bound: number | null;
}

/** Household status inside a Check_In_Run (api/state.py). "sent" = awaiting a reply. */
export type RunHouseholdStatus = "sent" | "ok" | "escalated" | "silent";

/** api/main.py HouseholdStatus: the run status when a run exists for the tract-hour, else the
 *  derived channel status (awaiting_door_knock on door_knock tract-hours, never silent; Req 20.2). */
export interface HouseholdStatus {
  id: string;
  label: string;
  lang: Lang;
  status: RunHouseholdStatus | "awaiting_door_knock" | "not_contacted";
  synthetic: true;
}

/** One message in a household thread (api/state.py `_send_out` / `_apply_reply`). `at` is run-relative seconds. */
export interface RunMessage {
  direction: "out" | "in";
  kind: "checkin" | "confirm" | "reprompt" | "reply";
  text: string;
  at: number;
  channel?: "simulator" | "twilio"; // outbound only
  simulated: boolean;
  generated?: boolean; // inbound only: true for seeded replies
  label?: string; // "Simulated" on generated replies
  class?: "ok" | "help" | null; // inbound only: reply classification
  synthetic: true;
}

export interface RunHousehold {
  id: string;
  label: string; // "Simulated household #N"
  number: number;
  lang: Lang;
  status: RunHouseholdStatus;
  is_operator: boolean;
  phone: string | null; // already masked by the API; pass through maskPhone anyway
  messages: RunMessage[];
  reprompts: number;
  unrecognized: number;
  escalation_id: string | null;
  silent_reason: "no_reply" | "unclear_reply" | null;
  synthetic: true;
}

/** Status counts; they sum to the number of households. `sent` = still awaiting a reply. */
export interface RunCounters {
  sent: number;
  ok: number;
  need_help: number;
  silent: number;
}

/** An Escalation routed to a simulated responder (a person). `created_at` is run-relative seconds. */
export interface Escalation {
  id: string;
  run_id: string;
  geoid: Geoid;
  hour: HourKey;
  town: Town;
  household_id: string;
  household_label: string;
  lang: Lang;
  responder_id: string;
  responder_label: string;
  created_at: number;
  status: "assigned";
  synthetic: true;
}

/** Check_In_Run JSON from POST /api/checkins/send, GET /api/checkins/{id}, POST /api/simulator/reply. */
export interface Run {
  id: string;
  geoid: Geoid;
  town: Town;
  hour: HourKey;
  telecom: 0 | 1;
  created_at: number; // API clock value, not wall time; use elapsed_s for display
  elapsed_s: number;
  timeout_s: number;
  households: RunHousehold[]; // household-number order
  counters: RunCounters;
  complete: boolean;
  status: "active" | "complete";
  synthetic: true;
  escalations: Escalation[];
}

/** 409 body detail from POST /api/checkins/send. */
export type SendRejectCode = "phones_degraded" | "no_households";

/** api/reach.py Citation */
export interface Citation {
  event_id: string;
  system: string;
  source_name: string;
  source_url: string;
}

/** api/reach.py ReachChannel */
export interface ReachChannel {
  channel: Channel;
  telecom: 0 | 1;
  telecom_rule: TelecomRule;
  label: string | null;
  citations: Citation[];
}

/** api/reach.py DoorKnockEntry */
export interface DoorKnockEntry {
  household_label: string;
  lang: Lang;
  why_chips: Chip[];
  responder_label: string;
  doorstep_script: string;
  access_hazard: string | null; // "Downed wires reported nearby. Treat every wire as live."
  synthetic: true;
}

/** Active events in TractDetail are TelecomEvent without pins. */
export type ActiveTelecomEvent = Omit<TelecomEvent, "pins">;

/** GET /api/tracts/{geoid}?hour= (api/main.py TractDetail) */
export interface TractDetail {
  geoid: Geoid;
  name: string;
  town: Town;
  hour: HourKey;
  rank: number | null;
  priority: number;
  need_t: number;
  need: Partial<Record<Indicator, NeedValue>>;
  need_missing: Indicator[];
  empower_masked: boolean;
  components: Components;
  weights: Record<Component, number>;
  contributions: Record<Component, number>;
  lifelines: number;
  metrics: Record<string, number>;
  telecom_rule: TelecomRule;
  telecom_label: string | null;
  telecom_citations: Citation[];
  /** Provenance of out_pct / hours_dark; NO_TOWN_REPORTS_LABEL for Chatham. */
  out_pct_label: string;
  customers_label: string | null;
  why_chips: Chip[];
  active_events: ActiveTelecomEvent[];
  channel: Channel;
  door_knock: DoorKnockEntry[] | null;
  households: HouseholdStatus[];
  /** The advanced run for this tract-hour, or null when no check-in was sent (always null for door_knock). */
  run: Run | null;
  escalations: Escalation[];
}

/** GET /api/content/{geoid}?hour= */
export interface ContentResponse {
  geoid: Geoid;
  town: Town;
  hour: HourKey;
  briefing: Briefing | null;
  reach: {
    channel: Channel;
    rule: TelecomRule;
    label: string | null;
    citations: Citation[];
    sms: Partial<Record<Lang, SmsText>> | null; // check-in text, only when channel is sms
    doorstep: Partial<Record<Lang, string>>;
    radio: Partial<Record<Lang, RadioText>> | null;
  };
  help_line: HelpLine;
}

/** POST /api/demo/reset */
export interface ResetResponse {
  ok: boolean;
}

/** Everything the app loads once at startup (useStaticData). */
export interface StaticData {
  hours: Hours;
  towns: CapeTowns;
  tracts: CapeTracts;
  timeline: CapeTimeline;
  events: TelecomEvents;
  sources: Sources;
  catalog: ScaleCatalog;
}
