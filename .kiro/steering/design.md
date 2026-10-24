# Design System: Lifeline City operator console

Applies to everything under `web/`. Goal: **premium and simple**. A calm, map-first operations console an emergency manager could use at 3 AM: one screen, no page scroll, quiet chrome, color only where it means something. Function, labels and accessibility rules from the other steering files and the spec stay exactly as they are; this file changes only how things look and where they sit.

## Principles

1. **The map is the canvas.** It fills the viewport. Everything else floats on it as a few glass panels.
2. **One idea per panel.** Top bar = context and controls. Left panel = the priority list. Bottom bar = time. Right drawer = one tract.
3. **Color is information.** Neutrals everywhere; color only for the map scale, the channel (Text vs Door-knock), and check-in status.
4. **Numbers are the hero.** Big, tabular, monospaced. Labels small and quiet.
5. **Hide the plumbing.** Provenance, sources and long lists stay available but collapsed, never deleted.

## Tokens (define once in `web/src/index.css` with Tailwind v4 `@theme`, use everywhere; no raw `slate-*`/`sky-*` classes)

```
Fonts (Google Fonts link in index.html): "Geist" 400/500/600 for UI, "Geist Mono" 400/500 for numbers and times.
Fallbacks: system-ui, -apple-system, sans-serif / ui-monospace, "SF Mono", monospace.

--bg:            #0A0E13   page and map fallback background
--panel:         rgba(16, 21, 28, 0.82)  floating panels, with backdrop-filter: blur(16px) saturate(140%)
--panel-solid:   #10151C   drawer background, popovers
--line:          rgba(255, 255, 255, 0.07)  hairlines and panel borders
--line-strong:   rgba(255, 255, 255, 0.14)
--text:          #E9EEF3
--text-muted:    #8C98A6
--text-faint:    #5C6876
--accent:        #F2A541   brand + priority emphasis (warm signal amber)
--text-channel:  #3DD6B5   "Text check-in" channel (teal)
--knock-channel: #F2A541   "Door-knock" channel (amber, same family as accent)
--ok:            #4ADE80
--help:          #FF6B6B   need help / escalated
--silent:        #A3AEBB
--simulated:     #B79CFF   "Simulated" tag text and 1px border at 40% alpha

Radius: 14px panels, 10px cards/rows, 999px pills. Spacing scale: 4/8/12/16/24. Panel padding 16px.
Shadow: 0 10px 40px rgba(0,0,0,0.45). Border: 1px solid var(--line) on every panel.
Type scale: 11px labels (uppercase, letter-spacing 0.06em, --text-faint) · 13px body · 15px/600 titles · 22px/500 Geist Mono for the big time and priority numbers.
Focus: 2px outline var(--accent), offset 2px, on every control (focus-visible only).
Motion: 160ms ease-out for drawer slide and hover; none on map updates; respect prefers-reduced-motion.
```

## Map colors (single-hue sequential ramps, dark → bright; replace viridis)

- Priority: `#151A21 → #3A2A17 → #7A4512 → #C46A17 → #F2A541 → #FFD38A`
- Need: `#151A21 → #2A2140 → #4B3577 → #7651B8 → #A985F0 → #D9C8FF`
- Lost lifelines: `#151A21 → #3A1D22 → #6E2A2F → #AE3B3B → #EE5F55 → #FFA594`
- Tract fill opacity 0.78, tract outline rgba(255,255,255,0.06) 0.5px; town boundaries rgba(255,255,255,0.28) 1px; hovered tract outline 1.5px --text; selected tract outline 2.5px --accent.
- Town labels: 11px Geist 500, uppercase, letter-spacing 0.08em, --text-muted, subtle text-shadow.
- Telecom pins: 7px circles with 2px ring. Active at the hour = --accent fill; inactive = transparent with --text-faint ring. The Cape-wide marker is one pin with a small count badge.
- Basemap: CARTO dark-matter-nolabels if available, else dark-matter; keep the plain-background fallback.

## Layout (1440×900 target, must also work at 1280×800; no page scroll)

```
┌────────────────────────────────────────────────────────────────────────────┐
│ TOP BAR (floating, 12px from edges, height 52)                             │
│ ● Lifeline   Cape Cod · Blizzard of 2026 replay │ [Place & hazard ▾]       │
│                         [Priority | Need | Lost lifelines]  (i)  ↺ Reset   │
├──────────────┬─────────────────────────────────────────────┬───────────────┤
│ LEFT PANEL   │                                             │ RIGHT DRAWER  │
│ 360px        │              MAP (full-bleed canvas)        │ 440px, slides │
│ Priority list│                                             │ in on select  │
│              │                                             │               │
│              │  legend chip (bottom-left of map area)      │               │
├──────────────┴─────────────────────────────────────────────┴───────────────┤
│ TIME BAR (floating, height ~92): ◀ ▶  Mon Feb 23 · 5 PM   [sparkline+slider]│
└────────────────────────────────────────────────────────────────────────────┘
```

### Top bar
- Left: an amber 8px dot + "Lifeline" (15px/600) and, muted, "Cape Cod · Blizzard of 2026 replay" (or the selected place/hazard).
- Center-right: place & hazard selector as a pill-shaped native `<select>` styled to match; layer switch as a segmented control (radio group, selected segment = --panel-solid with --line-strong border, label --text; others --text-muted).
- Right: an (i) icon button "Sources & assumptions" opening a popover with all provenance labels and source badges (replaces the always-visible SourceBadges row); a ghost "Reset demo" button with a ↺ icon and visible text.

### Left panel: Priority list
- Header: 11px label "PRIORITY LIST" + the hour ("Mon Feb 23 · 5 PM") + a one-line summary: "6 door-knock · 4 text" using the channel colors as small dots.
- 10 rows, each a button (10px radius, 10px padding): rank in Geist Mono --text-faint; town (13px/600) + tract ("Tract 153") muted; a thin 3px priority bar (width = priority / max, --accent) with the value in Geist Mono at the right; a channel pill (Text = teal tint 12% bg + teal text; Door-knock = amber tint + amber text); the first why-chip as one muted line under the name. Hover = --line background; selected = --line-strong border + 2px --accent left inset.
- Below the rows, two collapsed disclosures (closed by default, `<details>`): "All tracts (56)" (the existing keyboard tract list) and "Telecom reports (14)". Keep their behavior; just collapse them.

### Bottom time bar
- Prev/next icon buttons (aria-labels), the hour as 22px Geist Mono ("Mon Feb 23 · 5 PM").
- Behind the range slider, a 32px-tall area sparkline of `timeline.cape_total` (Cape customers out, --accent at 20% fill, 1.5px line). Same x scale as the slider. Caption on hover: "Cape customers without power".
- Key demo hours as small tick buttons under the track with short labels ("Mon 9 AM", "Mon 5 PM", "Tue 9 AM", "Wed 3 PM", "Thu 1 PM"); the active one in --accent.
- Custom-styled range input: 2px track --line-strong, filled part --accent, 14px round thumb --text with --accent ring.

### Right drawer (one tract)
- Slides in from the right (160ms), full height between top bar and time bar, --panel-solid, scrolls internally. Esc closes, focus moves in (keep existing behavior).
- Header: town + tract (17px/600); a row of three stat blocks: Rank, Priority (Geist Mono 22px), Channel pill. The channel note ("Phones likely degraded · Modeled") on one muted line.
- Tabs (real tablist, arrow-key navigation): **Briefing · Why flagged · Reach**. Default tab: Reach when a check-in run exists, else Briefing.
  - Briefing: "Verified" (--ok tint) or "Template" (neutral) tag; headline 15px/600; claims as a clean list with the value in Geist Mono at the right and the field name in 11px --text-faint; recommended action as a quiet callout with a 2px --accent left border.
  - Why flagged: two compact sections, "Need" and "Lost lifelines", each row = label · thin bar · value. Weights and contributions in Geist Mono. Provenance labels as 11px --text-faint lines under the section.
  - Reach: a channel card at the top. Text channel: the SMS preview inside an iPhone-like rounded frame (24px radius, --bg inside), language segmented control (English / Português / Español), primary button "Send check-ins" (--accent background, #1A1206 text, 10px radius, full width). Door-knock: the list as cards with a "Simulated" tag, language, responder, and the access-hazard note in --help tint when present. Radio script in a collapsed `<details>` "AM radio script (30 s)".
  - After sending: check-in status as 4 stat tiles (Awaiting · OK · Need help · Silent, each with its status color) + a thin progress bar for the reply window; escalations as compact rows; the phone simulator below (same phone frame, chat bubbles: outbound = --panel with --line border, inbound = --text-channel 14% tint), reply input + quick-reply chips (1, 2, AJUDA…).

### Small components
- "Simulated" tag: 10px uppercase, letter-spacing 0.08em, --simulated text, 1px --simulated/40% border, 999px radius, no fill.
- Pills and tags never use more than one color.
- Empty and loading states: one muted line, no spinners larger than 14px.
- API-unreachable banner: a floating toast at top center in --panel-solid with a --help left border and a Retry button.

## Do not
- No page scroll at 1440×900; panels scroll internally.
- No gradients except the sparkline fill; no emoji; no all-caps headings larger than 11px; no more than one accent color.
- Do not remove any label, provenance text, "Simulated" tag, aria attribute, keyboard path or test-covered behavior. Do not change the API, pipeline or `data/processed/`.
