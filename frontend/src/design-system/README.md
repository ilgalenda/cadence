# Cadence Design System

The visual and behavioural language for the Cadence platform. Everything the UI renders
traces back to this directory.

> **Source of truth: the Cadence Design System project on claude.ai/design.** This directory
> mirrors it. Change the design project first, then pull the change down here — never the
> reverse. The only intended divergence is the brand fonts (see *Fonts* below).

## The position

**"The studio"** — rebuilt 2026-08-19, replacing "the instrument". Acme sells precision
timing, and the interface earns that credibility by being **calm, white and unhurried**: a
white field, soft grey wells, pill geometry, generous air, and charcoal spent only where the
user commits. The consequences:

1. **White is the field, not a surface on a frame.** There is no charcoal frame. The rail is
   white, a hairline away from the content; depth comes from soft grey wells pressed into the
   field and cards lifted gently off it.
2. **Charcoal is an accent.** It appears as objects — the primary pill button, the bulk bar, a
   toast, a tooltip — never as a region. `.ds-chrome` now names those objects.
3. **Controls are pills; containers are soft cards.** `--radius-full` for every button, chip
   and input; `--radius-lg` (24px) for cards, panels, dialogs and the composer. The old
   machined 9px ceiling is retired.
4. **Hierarchy is size and weight together.** Big, bold, tight headlines over calm regular
   body. Roboto carries everything readable.
5. **Kode Mono is a whisper.** Timestamps, ids, counts, keyboard hints — short identifiers
   only. A mono sentence is in the wrong face. Eyebrows and table headers are sans now.
6. **Colour arrives as fields.** Occasional full-bleed colour surfaces — a featured card, an
   insights panel — built from the brand secondaries (`--field-blue/sky/amber/gold`). At most
   one per view. A field says "look here"; a signal colour says "this is the condition"; the
   two never trade jobs.
7. **State is stated in sync language.** `locked` · `drift` · `fault` · `live` · `canon`, now
   worn as soft wash pills. Colour as identity survives in exactly two disjoint palettes:
   series (charts) and app marks (agents).
8. **Motion is critically damped.** Unchanged: things arrive and stop. Overshoot only when the
   user's own gesture carried momentum into it.
9. **Glass survives on the floating layer only.** Menus, dialogs, toasts, tooltips, the
   palette, the floating drawer. Everything structural is solid. Never glass on glass.

The brand guidelines (v1.0, Oct 2024) remain binding: White and Charcoal are the
primary pair, Blue/Green/Amber/Gold the secondaries, Roboto the brand face, Kode Mono the
caption face. Two deliberate positions beyond them, both flagged in the previews:

- **`--signal-fault`** is an extension. The guidelines define no red, and an interface must be
  able to say something is wrong. It is tuned to sit beside amber rather than shout over it.
- **Gold is held to one meaning:** canonical, promoted knowledge — as a signal (`canon`) and as
  the one gold colour field.

## Series colour

`--series-1` … `--series-6` encode identity in charts: which series, not what state. Six
slots, fixed order, never cycled — the order is the colour-blindness safety mechanism. Green,
amber, red and gold are absent: status colours never impersonate a series. **The cap is
hard:** six slots are safe where only neighbours touch; all-pairs forms (scatter, map,
node-link) separate only the first three, and those need a second channel. Beyond three, fold
into `--series-other`, facet, or change the encoding.
Full derivation: `preview/foundations-series.html`.

## Marks

Two, not interchangeable. **Cadence** — four bars at uneven heights, the third in blue — is
the platform: favicon, app icon, rail, documents. **Owl** — a solid head with eyes and beak
knocked out — is the assistant: bylines, agent runs. Source: `assets/mark.svg`,
`assets/logo.svg`; served to the app as `/images/cadence-mark.svg` and
`/images/cadence-logo.svg`.

## Files

| File | What it is |
|---|---|
| `tokens.css` | The single source of truth — colour, type, space, motion, elevation. |
| `primitives.css` | The component layer: type, buttons, fields, rows, surfaces, chat. Imports `components.css`. |
| `components.css` | The second layer: choice controls, select, segment, table, meter, avatar, banner, tooltip, drawer, sources, palette. |
| `assets/*.svg` | Brand marks. |
| `grow.ts` | The `field-sizing` fallback. One delegated listener. |
| `springs.ts` | The spring vocabulary, translated once. |

Layout stays with Tailwind in the app. `primitives.css` owns what markup should not hold:
state machines, focus behaviour, motion, and the parts of the language that must not drift.

## Using it

Both layers are imported once by `src/styles/global.css`. Colours are space-separated RGB
channels so Tailwind can apply opacity: `rgb(var(--accent) / 0.12)`. Tailwind's semantic
names map onto these tokens in `tailwind.config.mjs`.

## Fonts

The app installs both faces from npm rather than self-hosting:

```
@fontsource-variable/roboto         variable, weight axis
@fontsource-variable/kode-mono      variable, weight axis
```

**Use the variable builds, not the static ones.** Google redrew Roboto in 2022;
`@fontsource/roboto` ships the older static drawing. fontsource registers its variable builds
under invented family names, so `design-system/fonts.css` re-declares them under the real
names — that indirection lets `tokens.css` stay byte-identical to the design project.

## Rules

- **No literal values in components.** If a value is not in `tokens.css`, add it there with a
  reason or use the nearest token.
- **Charcoal is an object, never a region.** If a whole pane is dark, it is wrong.
- **One colour field per view, at most.** A field is a featured surface, never a state.
  `--field-blue` carries white display text only; the other fields carry charcoal ink.
- **Glass only where content passes beneath** — the floating layer. Structural surfaces are
  solid.
- **Small text never uses `--accent`.** 3.66:1 on white — legal for fills and large text, not
  body copy. Accent-coloured text uses `--accent-ink`.
- **`--ink-muted` is the lightest permitted ink** (5.0:1 on white). Nothing lighter ships.
- **Mono is for identifiers.** A timestamp, an id, a count, a key hint. Never a sentence,
  never a label that names a section.
- **Selection is a grey well, never blue and never charcoal.** Blue means live; charcoal
  commits.
- **Ambient motion appears only on something genuinely in progress.** One pattern, the beat.
- **Every interactive element has a visible focus state** and every hover-revealed action is
  also reachable by keyboard (`:focus-within`).
- **Signal colours have on-chrome variants** for text on charcoal objects (toasts, bulk bar).
- **One charcoal.** `--surface-ink` and `--chrome` are the same value.

## Growing fields

Text areas and the composer expand as typed into and stop at a ceiling, then scroll
(`field-sizing: content`; fallback `enableGrowingFields()` from `grow.ts`). Never a fixed
`rows` height, never unbounded growth.

## The rail

```html
<aside class="ds-rail ds-scroll">…</aside>
```

The rail is white and sits on the field, separated by a hairline. Closed — glyphs only,
`--rail-closed` (56px) — is the default posture; it opens to `--rail-open` (216px) with
labels. No `.ds-chrome` on rails: the frame doctrine is retired.

## Material

Two tiers, decided by one question: **does content pass beneath it?**

**The floating layer — glass.** Menus, dialogs (and the palette), toasts, tooltips, the
floating drawer. Translucent, blurred, saturated, lifted by a real shadow, with a bright top
edge. Blur scales with the surface: `--blur-thin` tooltips, `--blur-regular` menus and toasts,
`--blur-thick` dialogs and the drawer.

**The structural layer — solid.** The field, cards, wells, tables, rows. Text over blur is
measurably harder to read, and this layer is what people came for. **Never glass on glass.**

```css
background: rgb(var(--surface) / var(--glass-light));
backdrop-filter: blur(var(--blur-regular)) saturate(var(--glass-saturate));
-webkit-backdrop-filter: blur(var(--blur-regular)) saturate(var(--glass-saturate));
box-shadow: var(--shadow-lifted);
```

`-webkit-` is written by hand — nothing prefixes at build time.

**Translucency is a preference.** `prefers-reduced-transparency`, `prefers-contrast: more`
and `forced-colors` all collapse the material structurally in `tokens.css`; no component
carries its own branch.

## Elevation

| Token | Meaning |
|---|---|
| `--shadow-flat` | seated in the field — wells, tables |
| `--shadow-raised` | a card you could pick up |
| `--shadow-lifted` | genuinely off the plane — the floating layer |
| `--shadow-overlay` | above everything, over a scrim — a blocking dialog |

Shadows are soft and diffuse. A shadow is never a border substitute.

## Enforcement

`_adherence.oxlintrc.json` is the contract. The platform ports it to a build gate that runs on
every `npm run build` and fails on: token inventory drift in either direction; any colour
outside the palette; any font outside the system; raw `px` values increasing (ratcheted per
file against a recorded baseline).

## Contrast, measured

All figures against the white field:

| Token | Ratio |
|---|---|
| `--ink` | 18.1:1 |
| `--ink-secondary` | 6.7:1 |
| `--ink-muted` | **5.0:1** — the AA floor |
| `--accent` | 3.66:1 — fills and large text only |
| `--accent-ink` | 6.7:1 |
| `--chrome-ink` on charcoal | 15.8:1 |
| `--chrome-ink-muted` on charcoal | **5.8:1** — the floor there |
| `--field-amber` under charcoal ink | 9.1:1 |
| `--field-blue` under white ink | 3.7:1 — display text only |

## Interaction rules

- **⌘K is the only shortcut anyone must know.** Everything clickable is reachable from the
  palette.
- **Work runs beside the conversation, not over it.** Long agent runs live in `.ds-drawer`; a
  dialog is only for a decision that blocks.
- **Every claim is traceable.** An answer that used tools carries `.ds-sources`; inline
  `.ds-cite` markers point into them. An untraceable inference says so — `.ds-banner--drift`.
- **A selection always states its count** and its actions sit in the charcoal `.ds-bulk` pill.
- **Hover-revealed actions are always also `:focus-within`-revealed.** Nothing is mouse-only.
- **Blue is never selection.** Selection is a grey well; blue means live.
