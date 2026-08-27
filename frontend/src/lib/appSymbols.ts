// The agents, drawn as applications.
//
// The pull-down of `marks-v3.json` and `preview/foundations-app-marks.html` from
// the Cadence Design System project (2026-08-20). The drawings and their solved
// transforms are the design project's; this module is how the app emits them.
//
// A second set, not the rail's glyphs made bigger. `lib/icons.ts` is drawn for a
// 13–17px row: fine detail, low ink, a 1.1 stroke. Scaled 2.3× onto a 4rem tile
// those drawings were the wrong ones — measured, they ranged from 12.7% to 25.9%
// ink coverage, so half the set read bold and half read faint beside it. Optical
// size is a property of the drawing, not of the transform.
//
// ── What the marks mean ─────────────────────────────────────────────────────
//
// Every symbol is drawn from **what the agent does to the data**, never as a
// picture of the tool — no magnifier for research, no pen for writing, no
// speaker for signals. A picture of a tool ages, collides with whatever else
// uses that picture, and says nothing about the work.
//
// Because the marks are abstract they can be made to **rhyme**, which a set of
// literal pictures cannot do: Signals is one event on a flat line and Call
// analysis is the same line with no event; Campaign selection opens one road
// into two and Recap closes two into one; Lead scoring ranks across the surface
// and Research is held at depth beneath it. A rhyme is deliberate — a pair built
// the same way and differing on one legible axis. A collision is not.
//
// ── Construction ────────────────────────────────────────────────────────────
//
//   Canvas      32×32.
//   Safe area   4 → 28. Nothing is drawn outside it.
//   Pen         One width, round-capped and round-joined, for the whole set.
//   Ink         9.5–12% of the canvas, measured on the FACE ALONE — the edge is
//               a function of the face, so measuring after inlay would let a
//               heavy mark hide behind its own light. `scripts/check-symbols.mjs`
//               rasterises the face and enforces the band.
//   Detail      Three elements at most, and nothing narrower than the pen.
//
// Scale and offset are solved by measurement in two passes: scale about the ink
// centre until the mark carries the band's coverage, then clamp into the safe
// area. Where the passes disagree the *path* changes rather than the numbers —
// Signals ran to 29.6 at full ink, and clamping cost it two points of coverage,
// so its baseline was shortened and re-solved.
//
// ── The inlay ───────────────────────────────────────────────────────────────
//
// The symbol is not printed on the tile; it is inlaid into it. A charcoal face
// (`--app-face`) sits on a saturated edge (`--app-edge`) carried down-right —
// lit from top-left. The edge is built by drawing the same path four times at
// stepped offsets beneath the face, which keeps it a fixed 1.2 units in canvas
// space: it thins with the mark and never becomes a second outline. At 24px what
// survives is a warm or cool cast along one side, which is how the stage should
// register at that size.
//
// Depth was faked before it was earned. An earlier attempt extruded the symbol
// in a flat grey wall — a colour the palette does not contain, invented to
// imitate a shadow. Moving the wall from paint into light fixed it: the edge is
// a hue the system already owns, which is also why the set needs no dark-mode
// artwork. On chrome the tile drops out and `--app-face` alone flips to white.
//
// The caller supplies the stage: it sets `--app-edge` (and the tile's wash) from
// the agent's stage, so one drawing serves all three stages and nothing here
// knows which stage it is being rendered for.

/**
 * The pen.
 *
 * One width for all eleven, round-capped and round-joined. A per-symbol weight is
 * how a set drifts into looking like several hands, and a round terminal is the
 * difference between a drawn mark and a cut one.
 *
 * It also fixes the smallest gap the set may hold: anything narrower closes up at
 * 32px. A constraint worth having rather than a limitation.
 */
const PEN = 2.4;

/**
 * The inlay: how deep the edge runs, and in how many steps.
 *
 * Four copies is what makes the rim read as continuous at 4rem without banding;
 * the depth is under one pen width, so the edge stays a rim on the face rather
 * than reading as a second, offset drawing.
 */
const EDGE_DEPTH = 1.2;
const EDGE_STEPS = 4;

/**
 * A mark on the 32 canvas: stroked geometry, optically sized, inlaid.
 *
 * The optical transform is applied to the drawing and the offset to the copy, so
 * every layer carries the identical solved geometry and the edge can never drift
 * out of register with its face.
 *
 * Each layer sets `color` as well as `stroke`, so a filled detail (`currentColor`
 * on a dot) belongs to the layer it sits in — the design project's card leaves
 * those dots on the inherited colour, which drops them out of the inlay.
 */
const mark = (body: string, scale: number, dx = 0, dy = 0): string => {
  const round = (value: number) => Number(value.toFixed(3));
  const drawn =
    `<g transform="translate(${round(16 + dx)} ${round(16 + dy)}) scale(${scale}) translate(-16 -16)">`
    + `${body}</g>`;

  let layers = '';
  // Furthest first, so each copy is painted behind the one in front of it.
  for (let step = EDGE_STEPS; step >= 1; step -= 1) {
    const offset = ((EDGE_DEPTH * step) / EDGE_STEPS).toFixed(2);
    layers += `<g transform="translate(${offset} ${offset})"`
      + ` stroke="rgb(var(--app-edge))" color="rgb(var(--app-edge))">${drawn}</g>`;
  }
  // The face, and the layer the measuring rig reads: `data-face` is the hook
  // `scripts/check-symbols.mjs` keys on, so ink is never measured through light.
  layers += `<g data-face stroke="rgb(var(--app-face))" color="rgb(var(--app-face))">${drawn}</g>`;

  return `<svg width="32" height="32" viewBox="0 0 32 32" fill="none"`
    + ` stroke-width="${PEN}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"`
    + ` style="filter:drop-shadow(0 .05em .045em rgb(var(--ink) / .20))">${layers}</svg>`;
};

/** A ranked wedge. Scoring is sorting, not aiming. */
const RANK = mark(
  '<path d="M6 9h20"/>'
  + '<path d="M6 16h13"/>'
  + '<path d="M6 23h6"/>', 1.0062, 0.737, 2.289);

/** An arrow crossing a boundary. A threshold, not a building. */
const THRESHOLD = mark(
  '<path d="M8 5v22"/>'
  + '<path d="M8 16h15"/>'
  + '<path d="M17.8 10.8 23 16l-5.2 5.2"/>', 0.935, 2.535, 0.08);

/** A circle half drawn, half dashed, split on its axis. A section cut, not a lens. */
const SECTION = mark(
  '<path d="M16 5.5a10.5 10.5 0 0 0 0 21"/>'
  + '<path d="M16 5.5a10.5 10.5 0 0 1 0 21" stroke-dasharray="1.4 3.4"/>'
  + '<path d="M16 5.5v21"/>', 0.7817, 0.848, 0.063);

/** A flat baseline and one spike. The event, not the transmitter. */
const EVENT = mark(
  '<path d="M6.2 22.5h4.6L15.8 7.5l5 15h4.8"/>'
  + '<circle cx="15.8" cy="7.5" r="1.6" fill="currentColor" stroke="none"/>', 1.0315, 0.233, -0.882);

/** A probe held at depth past three strata. No arrowhead — nothing is being fetched. */
const DEPTH = mark(
  '<path d="M5.5 9h21"/>'
  + '<path d="M5.5 16h21"/>'
  + '<path d="M5.5 23h21"/>'
  + '<path d="M11.5 4.6v18"/>'
  + '<circle cx="11.5" cy="25.6" r="1.9" fill="currentColor" stroke="none"/>', 0.7236, 0.747, 0.081);

/** A message with a six-point spark inside it. */
const SPARK_SAID = mark(
  '<path d="M7 6h18a3 3 0 0 1 3 3v8.6a3 3 0 0 1-3 3h-8.4L10 26v-5.4H7a3 3 0 0 1-3-3V9a3 3 0 0 1 3-3Z"/>'
  + '<path d="M16 9.4v7.8M12.6 11.35l6.8 3.9M19.4 11.35l-6.8 3.9"/>', 0.67, 0.3, 1.337);

/** One road in, two out. The fan opens right. */
const FAN_OPEN = mark(
  '<path d="M4.5 16h7"/>'
  + '<path d="M11.5 16c6.2 0 5-7.6 11.2-7.6"/>'
  + '<path d="M11.5 16c6.2 0 5 7.6 11.2 7.6"/>', 1.1274, 2.47, 0.081);

/** An I-beam caret and a spark. Where text appears, and what puts it there. */
const CARET_SPARK = mark(
  '<path d="M9.6 6h8.8M14 6v20M9.6 26h8.8"/>'
  + '<path d="M23.4 9.6v6.4M20.2 12.8h6.4"/>', 0.925, -0.364, 0.89);

/** Two roads in, one out. The same fan, mirrored. */
const FAN_CLOSE = mark(
  '<path d="M27.5 16h-7"/>'
  + '<path d="M20.5 16c-6.2 0-5-7.6-11.2-7.6"/>'
  + '<path d="M20.5 16c-6.2 0-5 7.6-11.2 7.6"/>', 1.1274, -2.31, 0.078);

/** An even waveform. Signals owns the spike, so calls own the level. */
const LEVEL = mark(
  '<path d="M6 13.5v5M12 8v16M18 10.6v10.8M24 14v4"/>', 1.0227, 1.691, 0.079);

/** Two arcs holding a question open, the answer at the centre. */
const HELD_OPEN = mark(
  '<path d="M11.4 5.6C7.2 7.4 4.6 11.3 4.6 16s2.6 8.6 6.8 10.4"/>'
  + '<path d="M20.6 5.6c4.2 1.8 6.8 5.7 6.8 10.4s-2.6 8.6-6.8 10.4"/>'
  + '<circle cx="16" cy="16" r="2.1" fill="currentColor" stroke="none"/>', 0.8543, 0.078, 0.082);

export const APP_SYMBOLS = {
  scoring: RANK,
  gtm: THRESHOLD,
  xray: SECTION,
  signals: EVENT,
  research: DEPTH,
  'campaign-intelligence': SPARK_SAID,
  'campaign-selection': FAN_OPEN,
  composer: CARET_SPARK,
  'call-analysis': LEVEL,
  recap: FAN_CLOSE,
  'newsletter-quiz': HELD_OPEN,
} as const;

export type AppSymbolName = keyof typeof APP_SYMBOLS;

/**
 * One agent's app symbol, or an empty string when there is none.
 *
 * Empty rather than a fallback, for the same reason `icon()` is: a missing
 * symbol should look missing in review. `appSymbols.test.ts` fails the build if
 * an agent reaches this without one.
 */
export function appSymbol(slug: string): string {
  return (APP_SYMBOLS as Record<string, string>)[slug] ?? '';
}
