// The year, drawn once across, with every show on it.
//
// The table answers "what does this show need"; a year answers "what is the
// shape of the programme" — which shows crowd each other, and where a
// deadline for one falls inside the run-up to another. Four shows in a month
// grid is eleven near-empty screens; four shows on one year is a picture.
//
// **The design system draws no calendar**, so this is new — but only the track
// is. Everything on it is existing vocabulary: `.ds-mark` for progress,
// `.ds-mono` for a count, `.agent-page__sect` for the head, and the `ev__`
// compositions the table already uses.
//
// The arithmetic is separated from the drawing and tested as arithmetic. A bar
// in the wrong month is not something a build gate can see, and it is exactly
// the kind of thing an off-by-one produces.

import {
  countdown,
  formatDay,
  formatWhen,
  localToday,
  progressMark,
  statusMark,
  decideMark,
  type EventRow,
} from './events';

export const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                       'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const DAY = 86_400_000;

const startOfYear = (year: number) => Date.UTC(year, 0, 1);
const daysInYear = (year: number) => (Date.UTC(year + 1, 0, 1) - startOfYear(year)) / DAY;

/** A date as a fraction of the year, clamped to it. Invalid dates read as null. */
export function fraction(iso: string | null | undefined, year: number): number | null {
  if (!iso) return null;
  const at = Date.parse(`${iso}T00:00:00Z`);
  if (Number.isNaN(at)) return null;
  const offset = (at - startOfYear(year)) / DAY;
  return Math.min(Math.max(offset / daysInYear(year), 0), 1);
}

/**
 * Where a show's bar sits on the track, as percentages.
 *
 * Clamped at both ends: a show running from December into January belongs on
 * both years' tracks, and on each it should stop at the edge rather than
 * overflow it. A bar is never thinner than a day, so a one-day show is still
 * something you can see and point at.
 */
export function lane(
  startsOn: string, endsOn: string, year: number,
): { left: number; width: number } | null {
  const from = fraction(startsOn, year);
  if (from === null) return null;
  const to = fraction(endsOn, year) ?? from;

  const left = Math.min(from, to);
  const minimum = 1 / daysInYear(year);
  return { left: left * 100, width: Math.max(Math.abs(to - from), minimum) * 100 };
}

/** Where a single marker sits, as a percentage. */
export function markAt(iso: string | null, year: number): number | null {
  const at = fraction(iso, year);
  return at === null ? null : at * 100;
}

/**
 * The deadline this row should point at, and what it is.
 *
 * A proposal's live deadline is the decision; a committed show's is the next
 * checklist line still owed. The same rule the table's `stateMark` applies,
 * so the two views never disagree about what a show is waiting on.
 */
export function pointer(event: EventRow): { at: string; label: string; kind: string } | null {
  if (event.status === 'proposed') {
    return event.decide_by
      ? { at: event.decide_by, label: 'decide by', kind: 'decide' }
      : null;
  }
  if (event.status !== 'approved' || !event.next_due || event.ready) return null;
  const late = event.next_due < localToday();
  return { at: event.next_due, label: 'due by', kind: late ? 'breached' : 'due_soon' };
}

/** `3 of 27 done`, or nothing to say yet. */
export function progress(event: EventRow): string {
  if (!event.checklist_total) return 'nothing raised yet';
  return `${event.checklist_total - event.outstanding} of ${event.checklist_total} done`;
}

// ── Drawing ─────────────────────────────────────────────────────────────────

const el = <K extends keyof HTMLElementTagNameMap>(tag: K, className?: string) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
};

export interface TimelineHandlers {
  /** Fetch the full record. The row paints whatever comes back. */
  onOpen: (id: string) => Promise<EventRow>;
}

/** Rendered into the opened row — the same painter the table uses. */
export type RecordPainter = (host: HTMLElement, event: EventRow) => void;

/**
 * The whole year, one row per show.
 *
 * `year` is the track. With "All years" selected there is no single track to
 * draw, so the caller is expected to pick one — the page defaults to the
 * nearest year that has a show in it.
 */
export function paintTimeline(
  host: HTMLElement,
  events: EventRow[],
  year: number,
  handlers: TimelineHandlers,
  record: RecordPainter,
): void {
  host.replaceChildren();

  if (events.length === 0) {
    const empty = el('p', 'ds-caption ev__empty');
    empty.textContent = 'Nothing on your calendar for this year.';
    host.append(empty);
    return;
  }

  const track = el('div', 'tl');

  // The scale carries the row's own three-column frame, with the months nested
  // in the middle cell — so the labels sit on exactly the geometry the lanes
  // use rather than on a grid that merely looks like it.
  const scale = el('div', 'tl__scale');
  const months = el('div', 'tl__months');
  for (const month of MONTHS) {
    const cell = el('span', 'tl__month');
    cell.textContent = month;
    months.append(cell);
  }
  scale.append(el('span'), months, el('span'));
  track.append(scale);

  for (const event of events) {
    track.append(...rowFor(event, year, handlers, record));
  }

  host.append(track);
}

function rowFor(
  event: EventRow,
  year: number,
  handlers: TimelineHandlers,
  record: RecordPainter,
): HTMLElement[] {
  const row = el('button', 'tl__row');
  row.type = 'button';
  row.dataset.event = event.id;

  // Name, venue and state stack in one column rather than sitting in three.
  // A third column pushed the progress off the edge at the page's measure —
  // and the progress is the thing this view exists to show.
  const label = el('span', 'tl__label');
  const name = el('span', 'tl__name');
  name.textContent = event.name;
  const where = el('span', 'ds-caption tl__where');
  where.textContent = event.location;
  label.append(name, where);

  const lanes = el('span', 'tl__lane');
  for (let i = 0; i < 12; i += 1) lanes.append(el('span', 'tl__gridline'));

  const placed = lane(event.starts_on, event.ends_on, year);
  if (placed) {
    const bar = el('span', `tl__bar tl__bar--${event.status}`);
    bar.style.left = `${placed.left}%`;
    bar.style.width = `${placed.width}%`;
    bar.title = `${event.name} · ${formatWhen(event.starts_on, event.ends_on)}`;
    lanes.append(bar);
  }

  // The deadline sits on the track before the bar, which is the whole argument
  // for a timeline: you can see that the thing you must order falls inside the
  // run-up to something else.
  const point = pointer(event);
  const at = point ? markAt(point.at, year) : null;
  if (point && at !== null) {
    const flag = el('span', `tl__flag tl__flag--${point.kind}`);
    flag.style.left = `${at}%`;
    flag.title = `${point.label} ${formatDay(point.at)}`;
    lanes.append(flag);
  }

  const state = el('span', 'tl__state');
  const spec = event.status === 'proposed'
    ? (decideMark(event.days_to_decide) ?? statusMark(event.status))
    : event.status === 'approved'
      ? progressMark(event)
      : statusMark(event.status);
  const mark = el('span');
  mark.className = spec.className;
  mark.textContent = spec.label;

  const count = el('span', 'ds-mono tl__count');
  count.textContent = progress(event);
  state.append(mark, count);

  label.append(state);
  row.append(label, lanes);
  row.title = `${event.name} · ${countdown(event.days_until)}`;
  row.setAttribute('aria-expanded', 'false');

  // The track opens its own record rather than reaching into the table's. A
  // non-admin has no table, and a click that quietly opens something they
  // cannot see is worse than a row that does not invite one.
  const detail = el('div', 'tl__detail');
  detail.hidden = true;
  const body = el('div', 'ev__detail');
  detail.append(body);

  row.addEventListener('click', async () => {
    const opening = detail.hidden;
    detail.hidden = !opening;
    row.classList.toggle('is-open', opening);
    row.setAttribute('aria-expanded', String(opening));
    if (!opening) return;

    const loading = el('p', 'ds-caption ev__none');
    loading.textContent = 'Opening…';
    body.replaceChildren(loading);
    try {
      record(body, await handlers.onOpen(event.id));
    } catch (err: any) {
      const failed = el('p', 'ds-error');
      failed.textContent = err?.message || 'That show could not be opened.';
      body.replaceChildren(failed);
    }
  });

  return [row, detail];
}
