// The words the outbound tracker uses, owned once.
//
// Nothing here touches the DOM or the network, so the vocabulary can be tested on
// its own — which matters more than usual, because three of these decide what
// colour a row is, and a row that reads "on track" when a touch is a fortnight
// overdue is worse than no colour at all.
//
// The backend owns the counters and the figures; this only names them.
// Recomputing a total here would be a second implementation of the one thing the
// tracker exists to report.
//
// **`unpriced` is not `£0`.** The valuation refuses to guess, so `value_est_gbp`
// arrives as `null` for an account whose deal composition nobody has settled.
// Rendering that as a zero would put "worth nothing" on a £30k opportunity.

export type RowStatus =
  | 'not_started'
  | 'sequencing'
  | 'replied'
  | 'meeting'
  | 'qualified'
  | 'dead';

export type Campaign = 'A-jamming' | 'B-tdd' | 'C-finance';

export type Confidence = 'high' | 'medium' | 'low';

export interface Touch {
  index: number;
  label: string;
  fired: boolean;
  at: string;
  actor: string;
}

export interface TrailEntry {
  id: string;
  kind: string;
  touch_index: number | null;
  from_value: string;
  to_value: string;
  actor: string;
  source: string;
  at: string;
}

export interface DealLine {
  shape: string;
  quantity: number;
}

export interface TrackerRow {
  id: string;
  tracker_id: string;
  account: string;
  domain: string;
  segment: string;
  tier: number;
  campaign: string;
  trigger_text: string;
  trigger_source: string;
  geography: string;
  target_roles: string;
  confidence: Confidence;
  deal_lines: DealLine[];
  attach_support: boolean;
  fleet_insight_units: number;
  value_est_gbp: number | null;
  value_note: string;
  notes: string;
  procurement_route: string;
  status: RowStatus;
  next_due: string;
  touches: Touch[];
  history: TrailEntry[];
}

export interface Counters {
  targets: number;
  touches: number;
  target_touches: number;
  in_sequence: number;
  replies: number;
  target_replies: number;
  calls: number;
  target_calls: number;
  qualified: number;
  target_qualified: number;
  qualified_value_gbp: number;
  total_value_gbp: number;
  unpriced: number;
  uncomposed: number;
  goal_gbp: number;
}

export interface Tracker {
  id: string;
  name: string;
  username: string;
  goal_gbp: number;
  artifact_url: string;
  created_at: string;
  updated_at: string;
}

/** In the order the sequence is worked, which is the order the page groups by. */
export const STATUS_ORDER: RowStatus[] = [
  'not_started',
  'sequencing',
  'replied',
  'meeting',
  'qualified',
  'dead',
];

export const STATUS_LABELS: Record<RowStatus, string> = {
  not_started: 'Not started',
  sequencing: 'In sequence',
  replied: 'Replied',
  meeting: 'Meeting booked',
  qualified: 'Qualified',
  dead: 'Closed out',
};

export const CAMPAIGN_LABELS: Record<Campaign, string> = {
  'A-jamming': 'Jamming',
  'B-tdd': '5G TDD',
  'C-finance': 'Finance',
};

/**
 * What each tier is *for*, said on the row.
 *
 * A bare "Tier 1" is a number somebody has to remember the meaning of, and the
 * meanings are not intuitive — tier 1 is not "best account", it is the person who
 * writes Acme into someone else's design and may never buy anything directly.
 */
export const TIER_LABELS: Record<number, string> = {
  1: 'Spec author',
  2: 'Trigger-qualified',
  3: 'OEM / embed',
};

/**
 * Today, where the reader is.
 *
 * Not `toISOString()`, which is the UTC date: every due date here is a business
 * date somebody typed, and west of Greenwich the UTC day rolls over first — so a
 * reader in New York would be told at 7pm that a touch was late a day early.
 * Same reasoning, and same fix, as `events.localToday`.
 */
export function localToday(now: Date = new Date()): string {
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

export function statusMark(status: RowStatus): { className: string; label: string } {
  switch (status) {
    case 'qualified':
      return { className: 'ds-mark ds-mark--locked', label: 'qualified' };
    case 'meeting':
      return { className: 'ds-mark ds-mark--live', label: 'meeting booked' };
    case 'replied':
      return { className: 'ds-mark ds-mark--live', label: 'replied' };
    case 'sequencing':
      return { className: 'ds-mark ds-mark--drift', label: 'in sequence' };
    case 'dead':
      return { className: 'ds-mark ds-mark--idle', label: 'closed out' };
    default:
      return { className: 'ds-mark ds-mark--idle', label: 'not started' };
  }
}

/**
 * Whether this account is owed a touch, as one mark — or nothing.
 *
 * **Only a sequence already under way can be overdue.** An account that has
 * replied is waiting on a person, one that is closed is waiting on nobody, and
 * one that has never been touched is not late on a touch — it has not begun, and
 * the group it sits in already says so. Marking those too put a red pill on
 * thirty-four of fifty-one rows on the first real list, which is how "late" comes
 * to mean "old" and the colour stops being worth looking at.
 *
 * A half-worked sequence is the case worth colouring: it decays, and it is the
 * one thing on this page that costs a reply if it is left.
 */
export function dueMark(
  row: Pick<TrackerRow, 'next_due' | 'status'>,
  today = localToday(),
): { className: string; label: string } | null {
  if (row.status !== 'sequencing' || !row.next_due) return null;
  if (row.next_due < today) return { className: 'ds-mark ds-mark--fault', label: 'overdue' };
  if (row.next_due === today) return { className: 'ds-mark ds-mark--drift', label: 'due today' };
  return null;
}

/** How far into the five touches this account is. */
export function touchesFired(row: Pick<TrackerRow, 'touches'>): number {
  return row.touches.filter((touch) => touch.fired).length;
}

/**
 * A figure in pounds, or the word for not having one.
 *
 * Whole pounds throughout: every price on the catalogue is a whole number, and
 * pence on a £1,000 quorum reads as spurious precision.
 */
export function money(gbp: number | null): string {
  if (gbp === null || gbp === undefined) return 'unpriced';
  return `£${gbp.toLocaleString('en-GB', { maximumFractionDigits: 0 })}`;
}

/** `£1.7m`, `£340k`, `£995` — for a counter tile, where the column is narrow. */
export function shortMoney(gbp: number): string {
  if (Math.abs(gbp) >= 1_000_000) {
    const millions = gbp / 1_000_000;
    return `£${millions.toFixed(millions >= 10 ? 0 : 2)}m`;
  }
  if (Math.abs(gbp) >= 1_000) return `£${Math.round(gbp / 1_000)}k`;
  return `£${gbp}`;
}

/** A ratio for a `.ds-meter`, clamped, and 0 rather than NaN when nothing is owed. */
export function progress(done: number, target: number): number {
  if (!target || target <= 0) return 0;
  return Math.max(0, Math.min(1, done / target));
}

export interface CounterTile {
  key: string;
  label: string;
  value: string;
  /** Said under the figure when there is a goal to read it against. */
  against: string;
  fraction: number;
  /** `live` for the counters that are the point; plain for the rest. */
  tone: 'live' | 'locked' | 'plain';
}

/**
 * The header strip.
 *
 * The order is the funnel — targets, touches, in sequence, replies, calls,
 * qualified, value — so the strip reads left to right as the sequence actually
 * runs rather than as whichever number is most flattering.
 *
 * A counter with no goal gets no meter and no "of N", because a bar against an
 * unset target is a bar that always reads full or always reads empty.
 */
export function counterTiles(counters: Counters): CounterTile[] {
  const tiles: CounterTile[] = [
    {
      key: 'targets',
      label: 'targets',
      value: String(counters.targets),
      against: '',
      fraction: 0,
      tone: 'plain',
    },
    {
      key: 'touches',
      label: 'touch actions',
      value: String(counters.touches),
      against: counters.target_touches ? `of ${counters.target_touches}` : '',
      fraction: progress(counters.touches, counters.target_touches),
      tone: 'live',
    },
    {
      key: 'in_sequence',
      label: 'in sequence',
      value: String(counters.in_sequence),
      against: counters.targets ? `of ${counters.targets}` : '',
      fraction: progress(counters.in_sequence, counters.targets),
      tone: 'plain',
    },
    {
      key: 'replies',
      label: 'replies',
      value: String(counters.replies),
      against: counters.target_replies ? `of ${counters.target_replies}` : '',
      fraction: progress(counters.replies, counters.target_replies),
      tone: 'live',
    },
    {
      key: 'calls',
      label: 'calls',
      value: String(counters.calls),
      against: counters.target_calls ? `of ${counters.target_calls}` : '',
      fraction: progress(counters.calls, counters.target_calls),
      tone: 'live',
    },
    {
      key: 'qualified',
      label: 'qualified',
      value: String(counters.qualified),
      against: counters.target_qualified ? `of ${counters.target_qualified}` : '',
      fraction: progress(counters.qualified, counters.target_qualified),
      tone: 'locked',
    },
    {
      key: 'qualified_value',
      label: 'qualified value',
      value: shortMoney(counters.qualified_value_gbp),
      against: counters.goal_gbp ? `of ${shortMoney(counters.goal_gbp)}` : '',
      fraction: progress(counters.qualified_value_gbp, counters.goal_gbp),
      tone: 'locked',
    },
  ];
  return tiles;
}

/**
 * What the total covers, and what it does not.
 *
 * Said next to the total rather than folded into it. A sum that silently omits
 * ten accounts reads as complete, and this list has ten whose composition nobody
 * has settled — so the omission is the sentence, not a footnote.
 */
export function coverageNote(counters: Counters): string {
  const total = money(counters.total_value_gbp);
  const caveats: string[] = [];

  if (counters.unpriced) {
    caveats.push(`${counters.unpriced} carry no figure at all`);
  }
  if (counters.uncomposed) {
    caveats.push(
      `${counters.uncomposed} carry a figure with no recorded composition, so they cannot be repriced`,
    );
  }

  const priced = counters.targets - counters.unpriced;
  const covered = counters.unpriced
    ? `${total} across ${priced} of ${counters.targets} accounts`
    : `${total} across all ${counters.targets} accounts`;

  if (!caveats.length) return `${covered}.`;
  return `${covered} — ${caveats.join(', and ')}.`;
}
