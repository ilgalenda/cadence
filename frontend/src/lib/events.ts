// The words the events surface uses, owned once.
//
// Nothing here touches the DOM or the network, so the vocabulary can be tested
// on its own — which matters more than usual, because two of these functions
// decide what colour a row is, and a row that renders green when it should render
// red is worse than no colour at all.
//
// The backend says how much is outstanding and when the next thing is owed; this
// only names it. Recomputing a deadline here would be a second implementation of
// the one rule the app exists for.

export type EventStatus = 'proposed' | 'approved' | 'declined' | 'attended';

/** One line of the checklist. Whether it is done lives in the spreadsheet. */
export interface ChecklistItem {
  id: string;
  phase: string;
  item: string;
  owner: string;
  due_on: string;
  registration_id: string | null;
}

export interface Registration {
  id: string;
  username: string;
  intent: string;
  needs_travel: number;
  travel_note: string;
  ticket_cost: number | null;
  ticket_currency: string;
  note: string;
  status: string;
}

export interface EventRow {
  id: string;
  name: string;
  year: number;
  location: string;
  country: string;
  starts_on: string;
  ends_on: string;
  status: EventStatus;
  days_until: number;
  days_to_decide: number | null;
  decide_by: string | null;
  /** The earliest checklist line still owed, as the sheet last reported it. */
  next_due: string | null;
  checklist_total: number;
  outstanding: number;
  ready: boolean;
  /** When the spreadsheet was last read, or null if never. */
  checked_at: string | null;
  rationale: string;
  attendee_count: number;
  invited: number;
  exhibiting: number;
  demo_required: number;
  demo_type: string;
  submission_deadline: string | null;
  exhibit_cost: number | null;
  exhibit_currency: string;
  quote_contact_name: string;
  quote_contact_email: string;
  decision_note: string;
  registrations?: Registration[];
  checklist?: ChecklistItem[];
}

/**
 * How far along a show is, as one mark.
 *
 * Cadence no longer tracks each line — the spreadsheet does — so this says only
 * what Sam asked it to: *"the only thing Cadence should show is when everything
 * is approved and everything is ready."* Late is spent on a deadline that has
 * actually passed, and on nothing else, or the page is red most of the time and
 * the word stops meaning anything.
 */
/**
 * Today, where the reader is.
 *
 * Not `toISOString()`, which is the **UTC** date: every deadline in this system
 * is a business date somebody in London or Geneva typed, and west of Greenwich
 * the UTC day rolls over first — so a reader in New York was told at 7pm that
 * something was late a day before it was.
 */
export function localToday(now: Date = new Date()): string {
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

/** An ISO date `days` later. Both ends are plain dates, so this stays in dates. */
export function addDays(iso: string, days: number): string {
  const at = new Date(`${iso}T00:00:00Z`);
  at.setUTCDate(at.getUTCDate() + days);
  return at.toISOString().slice(0, 10);
}

export function progressMark(
  event: Pick<EventRow, 'checklist_total' | 'outstanding' | 'ready' | 'next_due'>,
  today = localToday(),
): { className: string; label: string } {
  if (!event.checklist_total) return { className: 'ds-mark', label: 'nothing raised' };
  if (event.ready) return { className: 'ds-mark ds-mark--locked', label: 'ready' };
  if (event.next_due && event.next_due < today) {
    return { className: 'ds-mark ds-mark--fault', label: 'late' };
  }
  return { className: 'ds-mark ds-mark--drift', label: `${event.outstanding} to do` };
}

/**
 * The decide-by countdown, in the same three states the checklist uses.
 *
 * Only meaningful while an event is still proposed: once it is approved or
 * declined the decision has been taken, and a countdown to it would be noise.
 */
export function decideMark(daysToDecide: number | null): { className: string; label: string } | null {
  if (daysToDecide === null || daysToDecide === undefined) return null;
  if (daysToDecide < 0) return { className: 'ds-mark ds-mark--fault', label: 'decision overdue' };
  if (daysToDecide <= 7) return { className: 'ds-mark ds-mark--drift', label: `decide in ${daysToDecide}d` };
  return { className: 'ds-mark', label: `decide in ${daysToDecide}d` };
}

export function statusMark(status: EventStatus): { className: string; label: string } {
  switch (status) {
    case 'approved':
      return { className: 'ds-mark ds-mark--locked', label: 'going' };
    case 'declined':
      return { className: 'ds-mark', label: 'declined' };
    case 'attended':
      return { className: 'ds-mark', label: 'attended' };
    default:
      return { className: 'ds-mark ds-mark--drift', label: 'proposed' };
  }
}

/**
 * The month names, owned rather than asked for.
 *
 * `toLocaleString('en-GB', { month: 'short' })` returns "Sept" for September on
 * some ICU builds and "Sep" on others, so the same event renders differently in
 * two browsers. Twelve strings cost less than that.
 */
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** `28 Aug 2026`. One date, in the same voice as a range. */
export function formatDay(iso: string): string {
  const day = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(day.getTime())) return iso;
  return `${day.getDate()} ${MONTHS[day.getMonth()]} ${day.getFullYear()}`;
}

/** `11–14 Sep 2026`, or a single date where the show lasts one day. */
export function formatWhen(startsOn: string, endsOn: string): string {
  const start = new Date(`${startsOn}T00:00:00`);
  const end = new Date(`${endsOn}T00:00:00`);
  if (Number.isNaN(start.getTime())) return startsOn;

  const day = (d: Date) => d.getDate();
  const month = (d: Date) => MONTHS[d.getMonth()];

  if (startsOn === endsOn || Number.isNaN(end.getTime())) {
    return `${day(start)} ${month(start)} ${start.getFullYear()}`;
  }
  if (start.getMonth() === end.getMonth()) {
    return `${day(start)}–${day(end)} ${month(start)} ${start.getFullYear()}`;
  }
  return `${day(start)} ${month(start)} – ${day(end)} ${month(end)} ${end.getFullYear()}`;
}

/**
 * How far off the event is, said the way a person would say it.
 *
 * A negative count is the past, and it says so rather than showing a minus sign
 * — a table listing last year's shows is the normal case here, not an error.
 */
export function countdown(days: number): string {
  if (days === 0) return 'today';
  if (days === 1) return 'tomorrow';
  if (days > 0) return `in ${days} days`;
  if (days === -1) return 'yesterday';
  return `${Math.abs(days)} days ago`;
}

export function money(amount: number | null, currency: string): string {
  if (amount === null || amount === undefined) return '—';
  if (amount === 0) return 'free';
  return `${currency} ${amount.toLocaleString('en-GB', { minimumFractionDigits: 0 })}`;
}
