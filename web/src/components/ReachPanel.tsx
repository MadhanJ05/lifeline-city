import { useId, useRef, useState, type KeyboardEvent } from "react";
import { channelLabel } from "../queue";
import { safeUrl, telecomRuleView } from "../drawer";
import {
  DEFAULT_LANG,
  DOOR_KNOCK_EXPLANATION,
  DOOR_KNOCK_HEADING,
  LANG_LABEL,
  RADIO_HEADING,
  RADIO_MISSING,
  SEND_NOT_CONNECTED_NOTE,
  entryChipTexts,
  householdsText,
  langLabel,
  nextLang,
  radioLengthText,
  reachSections,
  segmentText,
} from "../reach";
import {
  LANGS,
  type CapeTimeline,
  type ContentResponse,
  type DoorKnockEntry,
  type Lang,
  type RadioText,
  type SmsText,
  type TractDetail,
} from "../types";
import { SimulatedBadge } from "./SimulatedBadge";

interface Props {
  detail: TractDetail;
  /** Content for the same tract-hour; null while it loads. */
  content: ContentResponse | null;
  telecomModel?: CapeTimeline["telecom_model"];
  /** "Send check-ins" handler; passed only for sms tract-hours. The button is disabled while absent. */
  onSend?: () => void;
  sending?: boolean;
  /** When set, the button is disabled and this note explains why (e.g. a run already exists). */
  sendNote?: string;
  /** Error text from the last send (e.g. a 409); shown as an alert next to the button. */
  sendError?: string | null;
}

const FOCUS = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";
const LABEL = "text-[11px] font-medium uppercase tracking-[0.06em] text-faint";
const CARD = "rounded-card border border-line p-3";

/** Reach channel, rule, language switcher, SMS preview or Door_Knock_List, and the AM radio script
 *  (Req 12.4 to 12.7, 15.1 to 15.3). Synthetic records carry the "Simulated" badge (Req 17.10). */
export function ReachPanel({ detail, content, telecomModel, onSend, sending = false, sendNote, sendError }: Props) {
  const [lang, setLang] = useState<Lang>(DEFAULT_LANG);
  const rule = telecomRuleView(detail, telecomModel);
  const sections = reachSections(detail.channel);
  const reach = content && content.geoid === detail.geoid && content.hour === detail.hour ? content.reach : null;
  const helpLine = content?.help_line.sentence[lang];

  return (
    <div className="flex flex-col gap-3 text-[13px]">
      <div className={CARD}>
        <p className="flex flex-wrap items-center gap-2">
          <span className={LABEL}>Channel</span>
          <span
            className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
              detail.channel === "sms" ? "bg-text-channel/12 text-text-channel" : "bg-knock/12 text-knock"
            }`}
          >
            {channelLabel(detail.channel)}
          </span>
          <span className="text-fg">{rule.headline}</span>
        </p>
        <p className="mt-1 text-xs text-muted">{rule.rule}</p>
        {rule.label && <p className="mt-0.5 text-[11px] text-faint">{rule.label}</p>}
        {rule.citations.length > 0 && (
          <ul className="mt-0.5 text-[11px] text-faint">
            {rule.citations.map((c) => {
              const href = safeUrl(c.source_url);
              return (
                <li key={c.event_id}>
                  Source:{" "}
                  {href ? (
                    <a href={href} target="_blank" rel="noreferrer" className={`text-accent underline ${FOCUS}`}>
                      {c.source_name}
                    </a>
                  ) : (
                    c.source_name
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <LanguageSwitcher value={lang} onChange={setLang} />

      {!reach && <p className="text-muted">Loading reach content…</p>}

      {reach && sections.smsPreview && (
        <SmsSection
          lang={lang}
          sms={reach.sms?.[lang] ?? null}
          households={detail.households.length}
          onSend={onSend}
          sending={sending}
          sendNote={sendNote}
          sendError={sendError ?? null}
        />
      )}

      {reach && sections.doorKnockList && (
        <DoorKnockSection entries={detail.door_knock ?? []} lang={lang} preview={reach.doorstep[lang] ?? null} />
      )}

      {reach && sections.radio && <RadioSection lang={lang} radio={reach.radio?.[lang] ?? null} />}

      {helpLine && (
        <p className="text-[11px] text-faint">
          Help line in every message: <span lang={lang}>{helpLine}</span>
        </p>
      )}
    </div>
  );
}

function LanguageSwitcher({ value, onChange }: { value: Lang; onChange: (l: Lang) => void }) {
  const labelId = useId();
  const refs = useRef<Partial<Record<Lang, HTMLButtonElement | null>>>({});
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const next = nextLang(value, e.key);
    if (!next) return;
    e.preventDefault();
    e.stopPropagation();
    onChange(next);
    refs.current[next]?.focus();
  };
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <span id={labelId} className={LABEL}>
        Preview language
      </span>
      <div role="radiogroup" aria-labelledby={labelId} onKeyDown={onKeyDown} className="inline-flex gap-0.5 rounded-full border border-line p-0.5">
        {LANGS.map((l) => {
          const checked = l === value;
          return (
            <button
              key={l}
              ref={(el) => {
                refs.current[l] = el;
              }}
              type="button"
              role="radio"
              aria-checked={checked}
              tabIndex={checked ? 0 : -1}
              onClick={() => onChange(l)}
              className={`rounded-full border px-2.5 py-0.5 text-xs ${FOCUS} ${
                checked ? "border-line-strong bg-bg font-medium text-fg" : "border-transparent text-muted hover:text-fg"
              }`}
            >
              {LANG_LABEL[l]}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function SmsSection({
  lang,
  sms,
  households,
  onSend,
  sending,
  sendNote,
  sendError,
}: {
  lang: Lang;
  sms: SmsText | null;
  households: number;
  onSend?: () => void;
  sending: boolean;
  sendNote?: string;
  sendError: string | null;
}) {
  const headingId = useId();
  const noteId = useId();
  const note = !onSend ? SEND_NOT_CONNECTED_NOTE : sendNote;
  const disabled = !onSend || sending || households === 0 || !!sendNote;
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-2">
      <h4 id={headingId} className="font-semibold">
        SMS check-in preview ({langLabel(lang)})
      </h4>
      {sms ? (
        <figure className="flex flex-col gap-1.5">
          {/* Sender and "Simulated" label sit outside the bubble (Req 14.8). */}
          <figcaption className="flex items-center justify-center gap-1.5 text-[11px] text-muted">
            <span>Lifeline City</span> <span aria-hidden="true">·</span> <SimulatedBadge />
          </figcaption>
          <div className="mx-auto w-full max-w-[22rem] rounded-[24px] border border-line-strong bg-bg p-3">
            <p lang={lang} className="max-w-[90%] whitespace-pre-line rounded-2xl rounded-tl-sm border border-line bg-panel px-3 py-2 text-fg">
              {sms.text}
            </p>
          </div>
          <p className="text-center font-mono text-[11px] text-faint">{segmentText(sms)}</p>
        </figure>
      ) : (
        <p className="text-muted">No SMS check-in cached in {langLabel(lang)} for this town.</p>
      )}
      <p className="flex items-center gap-1.5 text-xs text-muted">
        <SimulatedBadge /> {householdsText(households)}
      </p>
      <button
        type="button"
        onClick={onSend}
        disabled={disabled}
        aria-describedby={note ? noteId : undefined}
        className={`w-full rounded-card bg-accent px-3 py-2 font-semibold text-on-accent hover:bg-accent/90 disabled:cursor-not-allowed disabled:border disabled:border-line-strong disabled:bg-transparent disabled:text-muted ${FOCUS}`}
      >
        {sending ? "Sending check-ins…" : "Send check-ins"}
      </button>
      {note && (
        <p id={noteId} className="text-xs text-muted">
          {note}
        </p>
      )}
      {sendError && (
        <p role="alert" className="rounded-card border border-line border-l-2 border-l-help bg-help/10 px-2 py-1 text-xs">
          {sendError}
        </p>
      )}
    </section>
  );
}

function DoorKnockSection({ entries, lang, preview }: { entries: DoorKnockEntry[]; lang: Lang; preview: string | null }) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-2">
      <h4 id={headingId} className="font-semibold">
        {DOOR_KNOCK_HEADING}
      </h4>
      <p className="text-xs text-muted">{DOOR_KNOCK_EXPLANATION}</p>
      {preview && (
        <div className="flex flex-col gap-1">
          <p className={LABEL}>Doorstep script preview ({langLabel(lang)})</p>
          <p lang={lang} className="rounded-card border border-line bg-bg p-2.5">
            {preview}
          </p>
        </div>
      )}
      {entries.length === 0 ? (
        <p className="text-muted">No simulated households in this tract.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {entries.map((e) => (
            <DoorKnockItem key={e.household_label} entry={e} />
          ))}
        </ul>
      )}
    </section>
  );
}

function HazardIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" className="mt-0.5 shrink-0">
      <path d="M8 2l6.5 11.5h-13z" />
      <path d="M8 6.5v3.2M8 11.6v.2" strokeLinecap="round" />
    </svg>
  );
}

function DoorKnockItem({ entry }: { entry: DoorKnockEntry }) {
  return (
    <li className="flex flex-col gap-2 rounded-card border border-line p-3">
      <p className="flex flex-wrap items-center gap-1.5 font-semibold">
        {entry.household_label} <SimulatedBadge />
      </p>
      {entry.access_hazard && (
        <p role="note" className="flex items-start gap-1.5 rounded-card border border-help/40 bg-help/10 px-2 py-1.5 text-xs font-medium text-help">
          <HazardIcon />
          <span>Access hazard: {entry.access_hazard}</span>
        </p>
      )}
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
        <dt className="text-faint">Language</dt>
        <dd>{langLabel(entry.lang)}</dd>
        <dt className="text-faint">Responder</dt>
        <dd>{entry.responder_label}</dd>
        <dt className="text-faint">Why flagged</dt>
        <dd className="flex flex-wrap gap-1">
          {entryChipTexts(entry).map((t) => (
            <span key={t} className="rounded-full border border-line px-1.5 py-px text-[11px] text-muted">
              {t}
            </span>
          ))}
        </dd>
      </dl>
      <details className="text-xs">
        <summary className={`cursor-pointer rounded text-accent ${FOCUS}`}>
          Doorstep script ({langLabel(entry.lang)})
        </summary>
        <p lang={entry.lang} className="mt-1 text-[13px]">
          {entry.doorstep_script}
        </p>
      </details>
    </li>
  );
}

function RadioSection({ lang, radio }: { lang: Lang; radio: RadioText | null }) {
  const headingId = useId();
  return (
    <details className="rounded-card border border-line">
      <summary className={`cursor-pointer rounded-card px-3 py-2 text-xs font-medium text-fg ${FOCUS}`}>
        AM radio script (30 s)
      </summary>
      <section aria-labelledby={headingId} className="flex flex-col gap-1 px-3 pb-3">
        <h4 id={headingId} className="font-semibold">
          {RADIO_HEADING} ({langLabel(lang)})
        </h4>
        {radio ? (
          <>
            <p lang={lang} className="rounded-card border border-line bg-bg p-2.5">
              {radio.text}
            </p>
            <p className="font-mono text-[11px] text-faint">{radioLengthText(radio)}</p>
          </>
        ) : (
          <p className="text-muted">{RADIO_MISSING}</p>
        )}
      </section>
    </details>
  );
}
