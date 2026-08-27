// Rendering a lead's verdict.
//
// The page's whole claim is that the number is computed and the model only reads
// (`agents/scoring.astro`), so the two halves are drawn apart: the deterministic
// breakdown and its signals on one side, the model's interpretation on the other.
//
// The shaping is pure and tested; the painting is a thin pass over it. That split
// is deliberate — this suite runs without jsdom (see `dom.test.ts`), so anything
// worth being sure of lives in a function that never touches `document`.
//
// Every text run is set with `textContent`. A verdict carries model output built
// from a pasted lead signal, so it is untrusted by construction and never becomes
// markup.

export interface BreakdownRow {
  label?: string;
  points?: number;
  /** The component's ceiling — negative for friction, which has a floor instead. */
  max?: number;
  detail?: string;
}

export interface PageView {
  url?: string;
  seconds?: number;
  type?: string;
}

export interface Threshold {
  grade?: string;
  /** null on the lowest band, which has no floor. */
  min?: number | null;
}

export interface Lead {
  contact_name?: string;
  company?: string;
  role?: string;
  signal_strength?: string;
  signal_strength_reasoning?: string;
  confidence?: string;
  signal_type?: string;
  product_fit?: string;
  suggested_campaign_type?: string;
  suggested_campaign_reasoning?: string;
  source?: string;
  lead_score?: number;
  lead_max_score?: number;
  lead_grade?: string;
  lead_thresholds?: Threshold[];
  score_breakdown?: BreakdownRow[];
  score_signals?: string[];
  score_page_views?: PageView[];
}

/** A breakdown row, shaped for the table. */
export interface ScoreRow {
  label: string;
  detail: string;
  points: string;
  /** " / 45" for a capped component, empty for friction. */
  cap: string;
}

/** One key/value of the model's read. */
export interface Fact {
  label: string;
  value: string;
}

const el = <K extends keyof HTMLElementTagNameMap>(tag: K, className?: string) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
};

const text = (value: unknown): string => (typeof value === 'string' ? value.trim() : '');

// ── Shaping ─────────────────────────────────────────────────────────────────

/**
 * Points as they read in the table.
 *
 * A penalty keeps its minus sign — friction subtracts, and a breakdown that hid
 * that would not add up to the score printed above it. A contribution does not
 * need a plus: it is shown against its own ceiling, which says which way it runs.
 * Trailing `.0` is dropped; the scorer rounds to one dehaldenl, so most components
 * land whole and `15.0` is noise.
 */
export function formatPoints(points: unknown): string {
  const value = Number(points);
  if (!Number.isFinite(value)) return '—';
  const magnitude = Math.abs(value).toFixed(1).replace(/\.0$/, '');
  return `${value < 0 ? '−' : ''}${magnitude}`;
}

/**
 * A component's ceiling, as it reads beside its points.
 *
 * Friction carries a floor rather than a ceiling — "−5 / −15" invites you to read
 * a penalty as progress towards something, so it is shown bare.
 */
export function formatCap(max: unknown): string {
  const value = Number(max);
  if (!Number.isFinite(value) || value <= 0) return '';
  return ` / ${value.toFixed(1).replace(/\.0$/, '')}`;
}

/**
 * The breakdown, shaped for the table.
 *
 * The scorer returns a list of `{label, points, max, detail}`
 * (`services/lead_scoring.py`) — one row per capped component, and they sum to the
 * headline score. Anything else — an object, a null, a row with no label — is
 * dropped rather than rendered, because a row nobody can read is worse than a row
 * that is not there.
 */
export function normaliseBreakdown(raw: unknown): ScoreRow[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((row): row is BreakdownRow => Boolean(row) && typeof row === 'object')
    .map((row) => ({
      // Labels are built from the scorer's page types (`case_studies page`),
      // which are identifiers rather than English.
      label: text(row.label).replace(/_/g, ' '),
      detail: text(row.detail),
      points: formatPoints(row.points),
      cap: formatCap(row.max),
    }))
    .filter((row) => row.label !== '');
}

/** The mark a signal strength wears: hot is locked, warm drifts, cold is idle. */
export function strengthMark(strength: unknown): string {
  switch (text(strength).toLowerCase()) {
    case 'hot': return 'ds-mark ds-mark--locked';
    case 'warm': return 'ds-mark ds-mark--drift';
    case 'cold': return 'ds-mark ds-mark--idle';
    default: return 'ds-mark ds-mark--idle';
  }
}

/**
 * Grade colours follow the sync vocabulary, one-to-one with `strengthMark`.
 *
 * A/B/C map onto the same three tones as Hot/Warm/Cold deliberately: the computed
 * grade and the model's read sit side by side on the page, and matching their
 * vocabulary is what makes agreeing — or disagreeing — visible at a glance. Under
 * the old scale A and B shared a colour, which was honest then, because A covered
 * everything from 42 to 350 and B meant little.
 */
export function gradeColour(grade: unknown): string {
  switch (text(grade).toUpperCase()) {
    case 'A': return 'signal-locked';
    case 'B': return 'signal-drift';
    case 'C': return 'ink-muted';
    default: return 'ink-muted';
  }
}

/**
 * Where each grade begins, as one line — "A ≥ 55 · B ≥ 30".
 *
 * The bands travel with every score so no surface carries its own copy of the
 * numbers; the lowest band has no floor and says nothing.
 */
export function describeThresholds(thresholds: unknown): string {
  if (!Array.isArray(thresholds)) return '';
  return thresholds
    .filter((band): band is Threshold => Boolean(band) && typeof band === 'object')
    .filter((band) => typeof band.min === 'number')
    .map((band) => `${text(band.grade)} ≥ ${band.min}`)
    .join(' · ');
}

/**
 * The model's read, as facts worth showing.
 *
 * The prompt returns an empty string for anything it could not infer, so a naive
 * render is a column of dashes that says nothing. Only what was actually read
 * appears.
 */
export function readFacts(lead: Lead | null | undefined): Fact[] {
  const source = lead ?? {};
  const candidates: Fact[] = [
    { label: 'role', value: text(source.role) },
    { label: 'signal', value: text(source.signal_type) },
    { label: 'confidence', value: text(source.confidence) },
    { label: 'product fit', value: text(source.product_fit) },
    { label: 'came from', value: text(source.source) },
    { label: 'reach by', value: text(source.suggested_campaign_type) },
  ];
  return candidates.filter((fact) => fact.value !== '');
}

/**
 * Whether the model read anything worth a panel of its own.
 *
 * The strength itself does not count — it belongs to the verdict band, so a lead
 * the model only graded would otherwise open an empty panel.
 */
export function hasRead(lead: Lead | null | undefined): boolean {
  const source = lead ?? {};
  return readFacts(source).length > 0
    || text(source.signal_strength_reasoning) !== ''
    || text(source.suggested_campaign_reasoning) !== '';
}

/**
 * The pasted signal on one line, for the collapsed ask.
 *
 * `.ds-step__summary` clips with an ellipsis, so this only has to join the lines
 * — the width decides how much of it survives.
 */
export function summariseSignal(signal: unknown): string {
  return text(signal)
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .join(' · ');
}

// ── Painting ────────────────────────────────────────────────────────────────

/**
 * Draw the breakdown into a `<tbody>`, replacing whatever was there, and say how
 * many rows it drew — a caller with none should drop the column headings rather
 * than stand them over an empty table.
 *
 * The factor and the evidence for it share one cell: `.ds-table__sub` exists to
 * carry the second line under a primary, and a two-column table stays readable
 * where a three-column one would squeeze the URL to nothing.
 */
export function paintBreakdown(tbody: HTMLElement, breakdown: unknown): number {
  tbody.replaceChildren();
  const rows = normaliseBreakdown(breakdown);

  if (!rows.length) {
    const empty = el('tr');
    const cell = el('td', 'ds-caption');
    cell.colSpan = 2;
    cell.textContent = 'nothing scored — no recognisable page visits';
    empty.append(cell);
    tbody.append(empty);
    return 0;
  }

  for (const row of rows) {
    const tr = el('tr');

    const factor = el('td');
    const label = el('span', 'ds-table__primary');
    label.textContent = row.label;
    factor.append(label);
    if (row.detail) {
      const detail = el('span', 'ds-table__sub');
      detail.textContent = row.detail;
      detail.title = row.detail;
      factor.append(detail);
    }

    const points = el('td', 'ds-table__num');
    points.textContent = row.points;
    if (row.cap) {
      const cap = el('span', 'score-cap');
      cap.textContent = row.cap;
      points.append(cap);
    }

    tr.append(factor, points);
    tbody.append(tr);
  }
  return rows.length;
}

/**
 * A dwell in seconds, as it reads: "45s", "2m 10s".
 */
export function formatDwell(seconds: unknown): string {
  const value = Number(seconds);
  if (!Number.isFinite(value) || value <= 0) return '';
  const minutes = Math.floor(value / 60);
  const rest = Math.round(value % 60);
  if (!minutes) return `${rest}s`;
  return rest ? `${minutes}m ${rest}s` : `${minutes}m`;
}

/** The path of a visited URL — the host is always ours and never worth the width. */
export function pagePath(url: unknown): string {
  const raw = text(url);
  if (!raw) return '';
  try {
    return new URL(raw).pathname || '/';
  } catch {
    return raw;
  }
}

/**
 * Draw what was actually visited, under the components that were computed from it.
 * Returns how many pages there were.
 *
 * "2 page(s) of real interest" is a component's reason, not its evidence. Without
 * this list the breakdown says how much each part contributed and gives you no way
 * to see which pages it was reading, which is the inspectability the whole model
 * is justified by.
 */
export function paintPages(host: HTMLElement, views: unknown): number {
  host.replaceChildren();
  const pages = Array.isArray(views)
    ? views.filter((v): v is PageView => Boolean(v) && typeof v === 'object')
    : [];

  for (const view of pages) {
    const row = el('li', 'pages__row');

    const kind = el('span', 'ds-caption pages__kind');
    kind.textContent = text(view.type).replace(/_/g, ' ');

    const path = el('span', 'ds-small pages__path');
    path.textContent = pagePath(view.url);
    path.title = text(view.url);

    const dwell = el('span', 'ds-mono pages__dwell');
    dwell.textContent = formatDwell(view.seconds);

    row.append(kind, path, dwell);
    host.append(row);
  }
  return pages.length;
}

/** What `GET /leads/scale` answers with: the shape of the model, before a score. */
export interface Scale {
  max_score?: number;
  components?: BreakdownRow[];
  thresholds?: Threshold[];
}

/**
 * Draw what the scorer measures, out of what. Returns how many rows it drew, so a
 * caller can leave the panel hidden rather than showing an empty explanation.
 *
 * A ceiling reads as "45"; friction carries a floor, so it keeps its sign and
 * says "−15" — the same rule the result table follows, because this screen is
 * teaching the vocabulary that screen will use.
 */
export function paintScale(host: HTMLElement, components: unknown): number {
  host.replaceChildren();
  const rows = Array.isArray(components)
    ? components.filter((c): c is BreakdownRow => Boolean(c) && typeof c === 'object')
      .filter((c) => text(c.label) !== '')
    : [];

  for (const row of rows) {
    const term = el('dt', 'scale__row');
    const name = el('span', 'ds-small scale__name');
    name.textContent = text(row.label);
    const detail = el('span', 'ds-caption scale__detail');
    detail.textContent = text(row.detail);
    term.append(name, detail);

    const cap = el('dd', 'ds-mono scale__cap');
    cap.textContent = formatPoints(row.max);

    host.append(term, cap);
  }
  return rows.length;
}

/** Draw the behavioural signals as chips. Returns how many there were. */
export function paintSignals(host: HTMLElement, signals: unknown): number {
  host.replaceChildren();
  const found = Array.isArray(signals) ? signals.map(text).filter(Boolean) : [];

  for (const signal of found) {
    const tag = el('span', 'ds-tag');
    tag.textContent = signal;
    host.append(tag);
  }
  return found.length;
}

/**
 * Draw the model's read: why it landed where it did, the facts it inferred, and
 * how it would approach them. The strength itself is in the verdict band.
 */
export function paintRead(host: HTMLElement, lead: Lead): void {
  host.replaceChildren();

  const why = text(lead.signal_strength_reasoning);
  if (why) {
    const prose = el('p', 'ds-small read__why');
    prose.textContent = why;
    host.append(prose);
  }

  const facts = readFacts(lead);
  if (facts.length) {
    const list = el('dl', 'read__facts');
    for (const fact of facts) {
      const key = el('dt', 'ds-caption');
      key.textContent = fact.label;
      const value = el('dd', 'ds-small');
      value.textContent = fact.value;
      list.append(key, value);
    }
    host.append(list);
  }

  const approach = text(lead.suggested_campaign_reasoning);
  if (approach) {
    const prose = el('p', 'ds-small read__why');
    prose.textContent = approach;
    host.append(prose);
  }
}
