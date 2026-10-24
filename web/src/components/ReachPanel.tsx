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

const FOCUS = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-300";

/** Reach channel, rule, language switcher, SMS preview or Door_Knock_List, and the AM radio script
 *  (Req 12.4 to 12.7, 15.1 to 15.3). Synthetic records carry the "Simulated" badge (Req 17.10). */
export function ReachPanel({ detail, content, telecomModel, onSend, sending = false, sendNote, sendError }: Props) {
  const [lang, setLang] = useState<Lang>(DEFAULT_LANG);
  const rule = telecomRuleView(detail, telecomModel);
  const sections = reachSections(detail.channel);
  const reach = content && content.geoid === detail.geoid && content.hour === detail.hour ? content.reach : null;
  const helpLine = content?.help_line.sentence[lang];

  return (
    <div className="flex flex-col gap-3 text-sm">
      <div>
        <p>
          <span className="font-semibold">Channel:</span>{" "}
          <span className="rounded border border-slate-500 bg-slate-800 px-1.5 py-0.5 text-xs font-semibold">
            {channelLabel(detail.channel)}
          </span>{" "}
          <span>{rule.headline}</span>
        </p>
        <p className="mt-1 text-xs text-slate-300">{rule.rule}</p>
        {rule.label && <p className="text-xs text-slate-300">{rule.label}</p>}
        {rule.citations.length > 0 && (
          <ul className="text-xs text-slate-300">
            {rule.citations.map((c) => {
              const href = safeUrl(c.source_url);
              return (
                <li key={c.event_id}>
                  Source:{" "}
                  {href ? (
                    <a href={href} target="_blank" rel="noreferrer" className={`text-sky-300 underline ${FOCUS}`}>
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

      {!reach && <p className="text-slate-300">Loading reach content…</p>}

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
        <p className="text-xs text-slate-300">
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
    onChange(next);
    refs.current[next]?.focus();
  };
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span id={labelId} className="text-xs font-semibold text-slate-200">
        Preview language
      </span>
      <div role="radiogroup" aria-labelledby={labelId} onKeyDown={onKeyDown} className="inline-flex rounded-md border border-slate-600">
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
              className={`px-2 py-1 text-xs first:rounded-l-md last:rounded-r-md ${FOCUS} ${
                checked ? "bg-sky-200 font-semibold text-slate-950" : "bg-slate-800 text-slate-100 hover:bg-slate-700"
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
        <figure className="flex flex-col gap-1">
          <figcaption className="flex items-center gap-1.5 text-xs text-slate-300">
            <SimulatedBadge /> <span>· Lifeline City</span>
          </figcaption>
          <p lang={lang} className="max-w-[22rem] whitespace-pre-line rounded-2xl rounded-tl-sm bg-slate-800 px-3 py-2 text-slate-100">
            {sms.text}
          </p>
          <p className="text-xs text-slate-300">{segmentText(sms)}</p>
        </figure>
      ) : (
        <p className="text-slate-300">No SMS check-in cached in {langLabel(lang)} for this town.</p>
      )}
      <p className="flex items-center gap-1.5 text-xs text-slate-200">
        <SimulatedBadge /> {householdsText(households)}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onSend}
          disabled={disabled}
          aria-describedby={note ? noteId : undefined}
          className={`rounded-md border border-sky-300 bg-sky-200 px-3 py-1 font-semibold text-slate-950 hover:bg-sky-100 disabled:cursor-not-allowed disabled:border-slate-600 disabled:bg-slate-800 disabled:text-slate-300 ${FOCUS}`}
        >
          {sending ? "Sending check-ins…" : "Send check-ins"}
        </button>
        {note && (
          <span id={noteId} className="text-xs text-slate-300">
            {note}
          </span>
        )}
      </div>
      {sendError && (
        <p role="alert" className="rounded border border-rose-400/70 bg-rose-950/60 px-2 py-1 text-xs">
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
      <p className="text-slate-200">{DOOR_KNOCK_EXPLANATION}</p>
      {preview && (
        <div>
          <p className="text-xs font-semibold text-slate-200">Doorstep script preview ({langLabel(lang)})</p>
          <p lang={lang} className="rounded-md border border-slate-700 bg-slate-900 p-2">
            {preview}
          </p>
        </div>
      )}
      {entries.length === 0 ? (
        <p className="text-slate-300">No simulated households in this tract.</p>
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

function DoorKnockItem({ entry }: { entry: DoorKnockEntry }) {
  return (
    <li className="flex flex-col gap-1 rounded-md border border-slate-700 bg-slate-900 p-2">
      <p className="flex flex-wrap items-center gap-1.5 font-semibold">
        {entry.household_label} <SimulatedBadge />
      </p>
      {entry.access_hazard && (
        <p role="note" className="rounded border border-amber-300 bg-amber-950 px-2 py-1 font-semibold text-amber-100">
          <span aria-hidden="true">⚠ </span>Access hazard: {entry.access_hazard}
        </p>
      )}
      <dl className="grid grid-cols-[auto_1fr] gap-x-2 text-xs">
        <dt className="text-slate-400">Language</dt>
        <dd>{langLabel(entry.lang)}</dd>
        <dt className="text-slate-400">Responder</dt>
        <dd>{entry.responder_label}</dd>
        <dt className="text-slate-400">Why flagged</dt>
        <dd>{entryChipTexts(entry).join(" · ")}</dd>
      </dl>
      <details className="text-xs">
        <summary className={`cursor-pointer rounded text-sky-200 ${FOCUS}`}>
          Doorstep script ({langLabel(entry.lang)})
        </summary>
        <p lang={entry.lang} className="mt-1 text-sm">
          {entry.doorstep_script}
        </p>
      </details>
    </li>
  );
}

function RadioSection({ lang, radio }: { lang: Lang; radio: RadioText | null }) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-1">
      <h4 id={headingId} className="font-semibold">
        {RADIO_HEADING} ({langLabel(lang)})
      </h4>
      {radio ? (
        <>
          <p lang={lang} className="rounded-md border border-slate-700 bg-slate-900 p-2">
            {radio.text}
          </p>
          <p className="text-xs text-slate-300">{radioLengthText(radio)}</p>
        </>
      ) : (
        <p className="text-slate-300">{RADIO_MISSING}</p>
      )}
    </section>
  );
}
