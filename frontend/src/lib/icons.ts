// The rail's icon set, declared once.
//
// The design system draws icons rather than typing them: 13–14px stroke SVGs at
// `stroke-width` 1.1–1.3, `currentColor`, sitting inside `.ds-row__icon`. The
// platform had been using typographic glyphs (`⊞ ◍ ⚙ ▸`) on three rows out of
// twelve, which is neither the system's drawing nor its rule — the shell card
// says *every path has its own icon*.
//
// They live here, in one module, for the same reason surfaces live in
// `platform.ts`: so no page can invent one and no glyph can stand in for one.
//
// **Provenance.** Most of these are lifted verbatim from the design project's
// screen cards (`preview/screen-cadence-home.html`, `preview/screen-shell.html`).
// Fifteen are additions, marked `ADDED` below: the cards have no vocabulary for a path,
// a quiz, a newsletter, a market recall, a touch sequence, a follow-up, a connected
// account or a watchlist, and the home card says as much about Projects and Recent.
// Each is drawn to the same geometry and weight, and each should be pushed up to the
// design project so the set stays in one place.

/** A 14×14 stroke icon body. Rendered inside `.ds-row__icon`. */
type IconBody = string;

const box = (body: IconBody, size = 13, viewBox = '0 0 14 14'): string =>
  `<svg width="${size}" height="${size}" viewBox="${viewBox}" fill="none" aria-hidden="true">${body}</svg>`;

// ── From the design cards ───────────────────────────────────────────────────

const HOME = box('<path d="M2 6.4 7 2.2l5 4.2V12H2z" stroke="currentColor" stroke-width="1.1" stroke-linejoin="round"/>');

/** The Owl mark itself — a solid head with the eyes and beak knocked out. */
const OWL = box(
  '<path d="M4.2 7.2 5.2 2.4 9.6 5.3ZM15.8 7.2 14.8 2.4 10.4 5.3Z" fill="currentColor"/>'
  // One compound path, even-odd: the eyes and beak are genuine holes rather than
  // shapes painted the rail's colour. They were `rgb(var(--chrome))`, which is only
  // the background while the row is inactive — on the active row, which inverts to
  // near-white, the knockouts stayed charcoal and the owl read as a dark blob.
  + '<path fill-rule="evenodd" clip-rule="evenodd" fill="currentColor" d="'
    + 'M4 10.2a6 6 0 0 1 12 0v1.4a6 6 0 0 1-12 0Z'
    + 'M5 9.9a2.5 2.5 0 1 0 5 0 2.5 2.5 0 1 0-5 0Z'
    + 'M10 9.9a2.5 2.5 0 1 0 5 0 2.5 2.5 0 1 0-5 0Z'
    + 'M10 11.6l1.15 2.1H8.85Z"/>'
  + '<circle cx="7.5" cy="9.9" r="1.15" fill="rgb(var(--accent-on-chrome))"/>'
  + '<circle cx="12.5" cy="9.9" r="1.15" fill="rgb(var(--accent-on-chrome))"/>',
  14, '0 0 20 20',
);

/** Bars at uneven heights — a call, read. */
const WAVEFORM = box(
  '<path d="M2 5.6v2.8M4.4 3.6v6.8M6.8 5v4M9.2 2.8v8.4M11.6 5.9v2.2" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"/>',
);

/** A target — scoring: how warm, and why. */
const TARGET = box('<circle cx="7" cy="7" r="5" stroke="currentColor" stroke-width="1.1"/><circle cx="7" cy="7" r="1.6" stroke="currentColor" stroke-width="1.1"/>');

/** A rising line — going after something that has not happened yet. */
const TREND = box(
  '<path d="M2 10l3.5-3.5 2.5 2L12 4" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>'
  + '<path d="M12 7V4H9" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>',
);

/** A magnifier that adds — X-ray finds people who were not on the list. */
const PERSON = box(
  '<circle cx="7" cy="4.9" r="2.2" stroke="currentColor" stroke-width="1.1"/>'
  + '<path d="M2.6 11.9a4.4 4.4 0 0 1 8.8 0" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"/>',
);

/** A document with lines — the brief. */
const DOC = box(
  '<path d="M3 2h6l2 2v8H3z" stroke="currentColor" stroke-width="1.1" stroke-linejoin="round"/>'
  + '<path d="M5 6.5h4M5 9h3" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"/>',
);

/** An envelope — the touches Composer writes. */
const ENVELOPE = box(
  '<rect x="2" y="3.5" width="10" height="7" rx="1" stroke="currentColor" stroke-width="1.1"/>'
  + '<path d="m2.4 4.2 4.6 3.3 4.6-3.3" stroke="currentColor" stroke-width="1.1" stroke-linejoin="round"/>',
);

/** An open book — the compiled wiki. */
const BOOK = box(
  '<path d="M2.5 3v8.2c1.5-.9 3-.9 4.5 0 1.5-.9 3-.9 4.5 0V3c-1.5-.9-3-.9-4.5 0-1.5-.9-3-.9-4.5 0z" stroke="currentColor" stroke-width="1.1" stroke-linejoin="round"/>'
  + '<path d="M7 3.1v8.1" stroke="currentColor" stroke-width="1.1"/>',
);

/** A node with edges — knowledge as a graph, which is what the vault is. */
const GRAPH = box(
  '<circle cx="7" cy="3.3" r="1.5" stroke="currentColor" stroke-width="1.1"/>'
  + '<circle cx="3.3" cy="10.3" r="1.5" stroke="currentColor" stroke-width="1.1"/>'
  + '<circle cx="10.7" cy="10.3" r="1.5" stroke="currentColor" stroke-width="1.1"/>'
  + '<path d="M6 4.6 4.3 8.9M8 4.6l1.7 4.3M4.8 10.3h4.4" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"/>',
);

/** A gear — system settings. */
const GEAR = box(
  '<circle cx="7" cy="7" r="2" stroke="currentColor" stroke-width="1.1"/>'
  + '<path d="M7 1.8v1.4M7 10.8v1.4M2.3 7h1.4M10.3 7h1.4M3.7 3.7l1 1M9.3 9.3l1 1M10.3 3.7l-1 1M4.7 9.3l-1 1" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"/>',
  14,
);

/** A chevron — a project, per the home card. */

// ── Additions. The cards have no vocabulary for these three. ────────────────

// A path is named by where its lead came from, not by being a path. All three
// drew the same line-of-dots, so collapsed they were one glyph three times over —
// and that line was also `SEQUENCE`. Each now carries its own entry.

/** ADDED — an arrow arriving at a wall: a lead that came to us. */
const INBOUND = box(
  '<path d="M11.8 2.6v8.8" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"/>'
  + '<path d="M2 7h7.2" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"/>'
  + '<path d="M6.6 4.4 9.2 7l-2.6 2.6" stroke="currentColor" stroke-width="1.1" stroke-linecap="round" stroke-linejoin="round"/>',
);

/** ADDED — a pointer: someone acted on the site. */
const POINTER = box(
  '<path d="M3.4 2.4 11 6.8l-3.3.9-.9 3.3z" stroke="currentColor" stroke-width="1.1" stroke-linejoin="round"/>',
);

/** ADDED — stacked segments: a market sliced by vertical. */
const LAYERS = box(
  '<path d="M7 2.2 12 4.9 7 7.6 2 4.9z" stroke="currentColor" stroke-width="1.1" stroke-linejoin="round"/>'
  + '<path d="M2 8.1 7 10.8l5-2.7" stroke="currentColor" stroke-width="1.1" stroke-linejoin="round"/>',
);

/** ADDED — two cards, one behind the other: practice, a deck to work through.
 *  Was a question mark inside a `r=5` ring, which is the same outer circle as the
 *  scoring target; at rail size only the ring survived. */
const CARDS = box(
  '<rect x="1.9" y="4.6" width="7.5" height="7" rx="1.2" stroke="currentColor" stroke-width="1.1"/>'
  + '<path d="M4.6 4.6V3.7a1.2 1.2 0 0 1 1.2-1.2h5.1a1.2 1.2 0 0 1 1.2 1.2v5a1.2 1.2 0 0 1-1.2 1.2h-.9" stroke="currentColor" stroke-width="1.1" stroke-linecap="round" stroke-linejoin="round"/>',
);

/** ADDED — a broadcast: one thing written for many to read. */
const BROADCAST = box(
  '<path d="M3 5.5h3l3.5-2.5v8L6 8.5H3z" stroke="currentColor" stroke-width="1.1" stroke-linejoin="round"/>'
  + '<path d="M11 5.2a2.6 2.6 0 0 1 0 3.6" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"/>',
);

/** ADDED — two speech bubbles, one behind the other: conversations already had. */
const RECALL = box(
  '<path d="M5.4 2.6H12v4.2" stroke="currentColor" stroke-width="1.1" stroke-linecap="round" stroke-linejoin="round"/>'
  + '<path d="M2 5.2h7.4v4.4H5.4L3.6 11.4V9.6H2z" stroke="currentColor" stroke-width="1.1" stroke-linejoin="round"/>',
);

/** ADDED — a funnel: many campaigns in, one chosen out. Was marks-on-a-line,
 *  which is the drawing the three paths were already using. */
const FUNNEL = box(
  '<path d="M1.9 2.9h10.2L8.2 7.5v4.1L5.8 10.2V7.5z" stroke="currentColor" stroke-width="1.1" stroke-linejoin="round"/>',
);

/** ADDED — two links joined: an external account connected to this one. */
const LINK = box(
  '<path d="M6 8.4 8.4 6" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"/>'
  + '<path d="M8.1 4.6 9.3 3.4a2 2 0 0 1 2.8 2.8L10.9 7.4" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"/>'
  + '<path d="M6.3 9.9 5.1 11.1a2 2 0 0 1-2.8-2.8L3.5 7.1" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"/>',
);

/** ADDED — a return arrow: the reply that follows a conversation. The envelope
 *  it used to sit on was the composer's envelope, so the two rows read alike;
 *  the arrow is the half that means *reply*, and alone it is unmistakable. */
const REPLY = box(
  '<path d="M5.4 3.2 2.1 6.5l3.3 3.3" stroke="currentColor" stroke-width="1.1" stroke-linecap="round" stroke-linejoin="round"/>'
  + '<path d="M2.5 6.5h5.1a4.2 4.2 0 0 1 4.2 4.2v.6" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"/>',
);

/** ADDED — a quiet line and one spike: watching a fixed set, and the moment
 *  something moves. Was concentric rings, indistinguishable from the scoring
 *  target once the 2px of inner detail dropped out. */
const PULSE = box(
  '<path d="M1.7 7.6h2.4l1.4-4.5 1.8 7.3 1.3-2.8h3.7" stroke="currentColor" stroke-width="1.1" stroke-linecap="round" stroke-linejoin="round"/>',
);

/** ADDED — four panes: the set of agents, as a desktop draws its applications.
 *  Was three dots, which reads as "more" or an overflow menu rather than as a
 *  destination holding eleven things. Nothing else in the set is a grid. */
const GRID = box(
  '<rect x="2" y="2" width="4.2" height="4.2" rx="1" stroke="currentColor" stroke-width="1.1"/>'
  + '<rect x="7.8" y="2" width="4.2" height="4.2" rx="1" stroke="currentColor" stroke-width="1.1"/>'
  + '<rect x="2" y="7.8" width="4.2" height="4.2" rx="1" stroke="currentColor" stroke-width="1.1"/>'
  + '<rect x="7.8" y="7.8" width="4.2" height="4.2" rx="1" stroke="currentColor" stroke-width="1.1"/>',
);

/** ADDED — an ellipsis: this opens onto more than it shows. */
const ELLIPSIS = box(
  '<circle cx="2.5" cy="7" r="1.1" fill="currentColor"/>'
  + '<circle cx="7" cy="7" r="1.1" fill="currentColor"/>'
  + '<circle cx="11.5" cy="7" r="1.1" fill="currentColor"/>',
);

/** ADDED — a pin: an agent the person chose to keep in the rail. */
const PIN = box(
  '<path d="M8.6 1.9 12.1 5.4l-1.6.5-2.4 2.4-.2 2.6-3.8-3.8-2.7 2.7 2.7-2.7L.7 3.9l2.6-.2L5.7 1.3z" stroke="currentColor" stroke-width="1.1" stroke-linejoin="round"/>',
);

/** ADDED — a chevron pointing back: one step up the trail. */
const CHEVRON_LEFT = box(
  '<path d="M8.5 3 4.5 7l4 4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>',
);

/**
 * ADDED — a chevron pointing right: a disclosure, turned down by `.ds-twisty`.
 *
 * The exact mirror of `CHEVRON_LEFT`, so the pair stays optically one family.
 * The design draws this glyph in `screen-owl-workspace.html`; Owl carries its
 * own local copy, which should collapse onto this one.
 */
const CHEVRON = box(
  '<path d="M5.5 3 9.5 7l-4 4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>',
);

/** ADDED — a cross: dismiss the thing that is open. */
const CROSS = box('<path d="M3.2 3.2l7.6 7.6M10.8 3.2l-7.6 7.6" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>');

/** ADDED — a pane split off the right edge: the run panel beside the work. */
const PANEL = box('<rect x="1.8" y="2.6" width="10.4" height="8.8" rx="1.4" stroke="currentColor" stroke-width="1.1"/><path d="M9 2.6v8.8" stroke="currentColor" stroke-width="1.1"/>');

/** ADDED — a clock: conversations already had, found by when. */
const CLOCK = box(
  '<circle cx="7" cy="7" r="5" stroke="currentColor" stroke-width="1.1"/>'
  + '<path d="M7 4.2V7l2 1.4" stroke="currentColor" stroke-width="1.1" stroke-linecap="round" stroke-linejoin="round"/>',
);

// ── The set ─────────────────────────────────────────────────────────────────

export const ICONS = {
  home: HOME,
  owl: OWL,
  // Agents
  scoring: TARGET,
  gtm: TREND,
  signals: PULSE,
  xray: PERSON,
  research: DOC,
  'campaign-intelligence': RECALL,
  'campaign-selection': FUNNEL,
  composer: ENVELOPE,
  'call-analysis': WAVEFORM,
  recap: REPLY,
  'newsletter-quiz': BROADCAST,
  // Learn
  knowledge: GRAPH,
  library: BOOK,
  practice: CARDS,
  // Paths — one each, by where the lead came from
  inbound: INBOUND,
  'website-lead': POINTER,
  'icp-vertical': LAYERS,
  // Navigation
  back: CHEVRON_LEFT,
  chevron: CHEVRON,
  // Ways in, from the home shortcuts
  agents: GRID,
  history: CLOCK,
  pin: PIN,
  more: ELLIPSIS,
  // Chrome
  integrations: LINK,
  admin: GEAR,
  close: CROSS,
  panel: PANEL,
} as const;

export type IconName = keyof typeof ICONS;

/**
 * One icon's markup, or an empty string when the name is unknown.
 *
 * Empty rather than a fallback glyph on purpose: a missing icon should look
 * missing in review, not be papered over with a character the system does not use.
 */
export function icon(name: string): string {
  return (ICONS as Record<string, string>)[name] ?? '';
}

/** Whether every name given has an icon — used by the rail's own test. */
export function allNamed(names: readonly string[]): string[] {
  return names.filter((n) => !icon(n));
}
