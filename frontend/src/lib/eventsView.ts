// The calendar, and one show opened inside it.
//
// **A `.ds-table`, grouped by what the show needs from you.** This was a column
// of custom flex rows with a detail pane bolted underneath, which is not the
// system: `design-system/preview/components-data.html` had already drawn the
// readout — hairline rows, a small muted header, no zebra, tabular figures —
// and `lib/peopleList.ts` had already worked out how a record opens inside one.
// Both are followed here rather than re-argued.
//
// **The record opens in place, on the system's own `.ds-twisty`.** No drawer:
// the platform had exactly one and deleted it, because it was "closed by default
// behind an unlabelled icon, and hidden outright below 72rem" — see
// `lib/xrayRun.ts`. A disclosure row keeps the calendar on screen while one show
// is read, which is the comparison a calendar exists to support.
//
// **The grouping is the decision.** A proposal wants an answer; a committed show
// wants its checklist worked through; a closed one wants nothing. Sorting all three into
// one list by date buries the rows somebody has to act on today, which is what
// the first version did.
//
// Every text run is set with `textContent`. None of this is model output, but it
// is whatever a colleague typed into a form, and a surface careful only with
// untrusted input is one where somebody has to remember which is which.

import { icon } from './icons';
import {
  addDays,
  countdown,
  decideMark,
  formatDay,
  formatWhen,
  localToday,
  money,
  progressMark,
  statusMark,
  type ChecklistItem,
  type EventRow,
  type Registration,
} from './events';

const el = <K extends keyof HTMLElementTagNameMap>(tag: K, className?: string) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
};

function mark(spec: { className: string; label: string }): HTMLElement {
  const node = el('span');
  node.className = spec.className;
  node.textContent = spec.label;
  return node;
}

/**
 * The mark a row wears: whichever clock is actually running on it.
 *
 * A proposal's live deadline is the decision; an approved show's is its
 * checklist. Showing both would put two amber pills on one row and leave the
 * reader to work out which one is asking for something.
 */
export function stateMark(event: EventRow): { className: string; label: string } {
  if (event.status === 'proposed') {
    return decideMark(event.days_to_decide) ?? statusMark(event.status);
  }
  if (event.status === 'approved') return progressMark(event);
  return statusMark(event.status);
}

// ── The groups ──────────────────────────────────────────────────────────────

export interface EventGroup {
  key: string;
  title: string;
  /** Said on the heading, where it explains the whole group at once. */
  note?: string;
  /** Nothing is owed on these, so they start out of the way. */
  collapsed?: boolean;
  events: EventRow[];
}

const GROUPS: Array<Omit<EventGroup, 'events'>> = [
  { key: 'decide', title: 'Needs a decision', note: 'nothing is ordered until you decide' },
  { key: 'going', title: 'We are going' },
  { key: 'closed', title: 'Closed', note: 'turned down, or already been', collapsed: true },
];

const groupKey = (event: EventRow): string =>
  event.status === 'proposed' ? 'decide' : event.status === 'approved' ? 'going' : 'closed';

/**
 * Split the calendar into the groups the page shows, dropping empty ones.
 *
 * Pure, so the grouping can be tested without a browser — this repo has no jsdom
 * on purpose (see `dom.test.ts`).
 */
export function groupEvents(events: EventRow[]): EventGroup[] {
  return GROUPS
    .map((spec) => ({ ...spec, events: events.filter((e) => groupKey(e) === spec.key) }))
    .filter((group) => group.events.length > 0);
}

// ── The table ───────────────────────────────────────────────────────────────

export interface TableHandlers {
  /** Fetch the full record. The row paints whatever comes back. */
  onOpen: (id: string) => Promise<EventRow>;
}

/** Rendered into the opened row. Passed in, so the table holds no opinion. */
export type RecordPainter = (host: HTMLElement, event: EventRow) => void;

const COLUMNS = 5;

export function paintTable(
  host: HTMLElement,
  events: EventRow[],
  handlers: TableHandlers,
  record: RecordPainter,
): void {
  host.replaceChildren();

  if (events.length === 0) {
    const empty = el('p', 'ds-caption ev__empty');
    empty.textContent = 'No shows for this year yet.';
    host.append(empty);
    return;
  }

  const wrap = el('div', 'ev__tablewrap');
  wrap.innerHTML = `<table class="ds-table"><thead><tr>
    <th>Show</th>
    <th>When</th>
    <th class="ds-table__num">In</th>
    <th>State</th>
    <th class="ds-table__num">Going</th>
  </tr></thead></table>`;
  const table = wrap.querySelector('table')!;

  for (const group of groupEvents(events)) {
    table.append(bandFor(group, handlers, record));
  }

  host.append(wrap);
}

function bandFor(
  group: EventGroup,
  handlers: TableHandlers,
  record: RecordPainter,
): HTMLElement {
  const band = el('tbody', 'ev__band');
  let open = !group.collapsed;

  // The section head the platform already uses: eyebrow left, hairline to sit
  // on, the count in mono on the right, because the count is the machine
  // talking. The disclosure lives on the eyebrow so the count stays a readout
  // rather than becoming part of a control.
  const head = el('tr', 'ev__grouprow');
  head.innerHTML = `
    <td colspan="${COLUMNS}">
      <div class="agent-page__sect">
        <button class="ev__grouphead" type="button" data-toggle aria-expanded="${open}">
          <span class="ds-twisty${open ? ' is-open' : ''}" data-twisty>${icon('chevron')}</span>
          <span class="ds-eyebrow" data-title></span>
          <span class="ev__groupnote" data-note></span>
        </button>
        <span class="ds-mono" data-count></span>
      </div>
    </td>`;
  head.querySelector('[data-title]')!.textContent = group.title;
  head.querySelector('[data-note]')!.textContent = group.note ?? '';
  head.querySelector('[data-count]')!.textContent = String(group.events.length);
  band.append(head);

  const rows: HTMLElement[] = [];
  for (const event of group.events) rows.push(...rowsFor(event, handlers, record));
  band.append(...rows);

  const toggle = head.querySelector('[data-toggle]') as HTMLButtonElement;
  toggle.addEventListener('click', () => {
    open = !open;
    head.querySelector('[data-twisty]')!.classList.toggle('is-open', open);
    toggle.setAttribute('aria-expanded', String(open));
    // Collapsing a band hides everything in it; reopening restores the shows but
    // not whatever detail was expanded inside them — reopening a group is not a
    // request to reopen every record somebody had read.
    for (const row of rows) {
      row.hidden = open ? row.classList.contains('ev__detailrow') : true;
      if (open && row.classList.contains('ev__row')) collapseRow(row);
    }
  });

  if (!open) for (const row of rows) row.hidden = true;
  return band;
}

/** Put a row back to closed, so a band's state and its rows' agree. */
function collapseRow(row: HTMLElement): void {
  row.classList.remove('is-open');
  row.querySelector('[data-twisty]')?.classList.remove('is-open');
  row.querySelector('[data-toggle]')?.setAttribute('aria-expanded', 'false');
}

function rowsFor(
  event: EventRow,
  handlers: TableHandlers,
  record: RecordPainter,
): HTMLElement[] {
  const row = el('tr', 'ev__row');
  // The handle an emailed link finds the row by.
  row.dataset.event = event.id;
  row.innerHTML = `
    <td class="ev__colwide">
      <div class="ev__who">
        <button class="ev__twisty" type="button" data-toggle aria-expanded="false">
          <span class="ds-twisty" data-twisty>${icon('chevron')}</span>
        </button>
        <span class="ev__whoname">
          <span class="ds-table__primary" data-name></span>
          <span class="ds-table__sub" data-where></span>
        </span>
      </div>
    </td>
    <td class="ev__when ds-mono" data-when></td>
    <td class="ds-table__num" data-in></td>
    <td data-state></td>
    <td class="ds-table__num" data-going></td>`;

  row.querySelector('[data-name]')!.textContent = event.name;
  // `.ds-table__sub` is specified `max-width: 26ch` and ellipsised, so it holds
  // the venue alone — the part that tells one show from another. The country
  // stays in the tooltip rather than eating the venue's characters.
  const whereCell = row.querySelector('[data-where]') as HTMLElement;
  whereCell.textContent = event.location;
  const full = [event.location, event.country].filter(Boolean).join(' · ');
  if (full) whereCell.title = full;

  row.querySelector('[data-when]')!.textContent = formatWhen(event.starts_on, event.ends_on);
  const inCell = row.querySelector('[data-in]') as HTMLElement;
  inCell.textContent = event.days_until >= 0 ? `${event.days_until}d` : 'passed';
  inCell.title = countdown(event.days_until);
  row.querySelector('[data-state]')!.append(mark(stateMark(event)));
  row.querySelector('[data-going]')!.textContent = String(event.attendee_count);

  const detail = el('tr', 'ev__detailrow');
  detail.hidden = true;
  detail.innerHTML = `<td colspan="${COLUMNS}"><div class="ev__detail" data-body></div></td>`;
  const body = detail.querySelector('[data-body]') as HTMLElement;

  const toggle = row.querySelector('[data-toggle]') as HTMLButtonElement;
  toggle.setAttribute('aria-label', `Open ${event.name}`);
  toggle.addEventListener('click', async () => {
    const opening = detail.hidden;
    detail.hidden = !opening;
    row.classList.toggle('is-open', opening);
    row.querySelector('[data-twisty]')!.classList.toggle('is-open', opening);
    toggle.setAttribute('aria-expanded', String(opening));
    if (!opening) return;

    // Always refetched on open: the list carries no people and no checklist, and
    // a record cached from an earlier open would show a deadline somebody has
    // since moved.
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

// ── One record ──────────────────────────────────────────────────────────────

export interface RecordHandlers {
  onApprove: (id: string) => void;
  onDecline: (id: string) => void;
  onApproveRegistration: (id: string) => void;
  /** Confirmation belongs to the caller — this only asks. */
  onDelete: (event: EventRow) => void;
}

/** `3 of 27 done`, from the two numbers the sheet last reported. */
export function progressLabel(event: EventRow): string {
  const done = event.checklist_total - event.outstanding;
  return `${done} of ${event.checklist_total} done`;
}

/** One labelled fact. The record is mostly these, so they are built once. */
function fact(label: string, value: string): HTMLElement {
  const row = el('div', 'ev__fact');
  const key = el('span', 'ds-caption ev__key');
  key.textContent = label;
  const val = el('span', 'ev__value');
  val.textContent = value || '—';
  row.append(key, val);
  return row;
}

function subhead(title: string, count: string): HTMLElement {
  const head = el('div', 'agent-page__sect');
  const heading = el('h3', 'ds-eyebrow');
  heading.textContent = title;
  const tally = el('span', 'ds-mono');
  tally.textContent = count;
  head.append(heading, tally);
  return head;
}

function paintChecklistLine(item: ChecklistItem, whose: string): HTMLElement {
    const row = el('div', 'ev__item');

  const head = el('div', 'ev__itemhead');
  const name = el('span', 'ev__itemname');
  name.textContent = item.item;
  head.append(name);

  const due = el('p', 'ds-caption ev__due');
  // The date and the owner, and nothing about whether it is done — that lives in
  // the spreadsheet, and a state shown here would be a second answer to it.
  due.textContent = `by ${formatDay(item.due_on)} · ${item.owner || 'unassigned'}`
    + (whose ? ` · ${whose}` : '');

  row.append(head, due);
  return row;
}


function paintRegistration(
  registration: Registration,
  handlers: RecordHandlers,
  canDecide: boolean,
): HTMLElement {
  const row = el('div', 'ev__item');

  const head = el('div', 'ev__itemhead');
  const who = el('span', 'ev__itemname');
  who.textContent = registration.username;
  const confirmed = registration.status === 'approved';
  const state = el('span', confirmed ? 'ds-mark ds-mark--locked' : 'ds-mark ds-mark--idle');
  state.textContent = confirmed ? 'confirmed' : registration.status;
  head.append(who, state);

  const detail = el('p', 'ds-caption ev__due');
  const parts = [registration.intent];
  if (registration.needs_travel) parts.push('needs travel');
  parts.push(`ticket ${money(registration.ticket_cost, registration.ticket_currency)}`);
  detail.textContent = parts.join(' · ');

  row.append(head, detail);

  if (canDecide && registration.status === 'proposed') {
    const actions = el('div', 'ev__acts');
    const approve = el('button', 'ds-btn ds-btn--secondary ds-btn--sm');
    approve.type = 'button';
    approve.textContent = 'Confirm place';
    approve.addEventListener('click', () => handlers.onApproveRegistration(registration.id));
    actions.append(approve);
    row.append(actions);
  }

  return row;
}

/**
 * One show, opened inside its own row.
 *
 * The case for going leads, because it is what an approval turns on — a record
 * that opened on stand costs would be asking the reader to decide on price.
 *
 * `canDecide` hides approve and decline from somebody who cannot use them. That
 * is a courtesy, not a control: the backend refuses them either way, and hiding
 * a button a person cannot press beats showing them a 403.
 */
export function paintRecord(
  host: HTMLElement,
  event: EventRow,
  handlers: RecordHandlers,
  canDecide: boolean,
): void {
  host.replaceChildren();

  if (event.rationale) {
    const why = el('div', 'ev__why');
    const label = el('p', 'ds-caption ev__key');
    label.textContent = 'Why we should go';
    const body = el('p', 'ev__case');
    body.textContent = event.rationale;
    why.append(label, body);
    host.append(why);
  }

  // Only what this show actually asked for. A column of "Stand cost —" against a
  // conference is the same noise the form avoids by not asking the question.
  const facts = el('div', 'ev__facts');
  // Only while it is still a question. On an approved show the decide-by date is
  // a deadline that was met, and the decision note below says what was decided.
  if (event.decide_by && event.status === 'proposed') {
    facts.append(fact('Decide by',
      `${formatDay(event.decide_by)} · ${countdown(event.days_to_decide ?? 0)}`));
  }
  facts.append(fact('Invited', event.invited ? 'yes' : 'no'));
  facts.append(fact('Exhibiting', event.exhibiting ? 'yes' : 'no'));
  if (event.exhibiting) {
    facts.append(fact('Stand cost', money(event.exhibit_cost, event.exhibit_currency)));
    facts.append(fact('Quote contact', [event.quote_contact_name, event.quote_contact_email]
      .filter(Boolean).join(' · ')));
  }
  if (event.demo_required) facts.append(fact('Demo', event.demo_type || 'yes'));
  if (event.submission_deadline) {
    facts.append(fact('Submit by', formatDay(event.submission_deadline)));
  }
  if (event.decision_note) facts.append(fact('Decision', event.decision_note));
  host.append(facts);

  if (canDecide && event.status === 'proposed') {
    const actions = el('div', 'ev__acts ev__acts--decide');
    const approve = el('button', 'ds-btn ds-btn--primary');
    approve.type = 'button';
    approve.textContent = 'Approve';
    approve.addEventListener('click', () => handlers.onApprove(event.id));

    const decline = el('button', 'ds-btn ds-btn--ghost');
    decline.type = 'button';
    decline.textContent = 'Decline';
    decline.addEventListener('click', () => handlers.onDecline(event.id));

    actions.append(approve, decline);
    host.append(actions);
  }

  const registrations = event.registrations ?? [];
  host.append(subhead('Who is going', String(registrations.length)));
  const people = el('div', 'ev__items');
  if (registrations.length === 0) {
    const none = el('p', 'ds-caption ev__none');
    none.textContent = 'Nobody has registered yet.';
    people.append(none);
  } else {
    for (const registration of registrations) {
      people.append(paintRegistration(registration, handlers, canDecide));
    }
  }
  host.append(people);

  // The checklist, read-only and grouped by phase. Ticking happens in the shared
  // spreadsheet, where the people doing the work are — Cadence raises the lines
  // and shows what is left, and does not pretend to know more than that.
  const items = event.checklist ?? [];
  host.append(subhead('What needs doing', items.length ? progressLabel(event) : '0'));
  const checklist = el('div', 'ev__items');
  if (items.length === 0) {
    const none = el('p', 'ds-caption ev__none');
    none.textContent = 'Nothing raised yet — the checklist appears when the show is approved.';
    checklist.append(none);
  } else {
    let phase = '';
    for (const item of items) {
      if (item.phase !== phase) {
        phase = item.phase;
        const head = el('p', 'ds-eyebrow ev__phase');
        head.textContent = phase;
        checklist.append(head);
      }
      const whose = item.registration_id
        ? (event.registrations ?? []).find((r) => r.id === item.registration_id)?.username ?? ''
        : '';
      checklist.append(paintChecklistLine(item, whose));
    }
  }
  host.append(checklist);

  if (items.length) {
    const where = el('p', 'ds-caption ev__none ev__sheetnote');
    // Told to go somewhere, and now told where. The address is served rather
    // than written here, and is absent until a document exists — so the link is
    // simply not drawn instead of pointing at nothing.
    where.append('Tick these off in ');
    if (sheetUrl) {
      const link = el('a', 'ds-link');
      link.href = sheetUrl;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = 'the shared spreadsheet';
      where.append(link, '.');
    } else {
      where.append('the shared spreadsheet.');
    }
    host.append(where);
  }

  // Last, and on its own. The routine decisions are at the top where they are
  // read; a destructive one sitting beside "Approve" is a mis-click waiting to
  // happen. Admin only — which the backend enforces whatever the page draws.
  if (canDecide) {
    const remove = el('div', 'ev__remove');
    const button = el('button', 'ds-btn ds-btn--danger ds-btn--sm');
    button.type = 'button';
    button.textContent = 'Delete this show';
    button.addEventListener('click', () => handlers.onDelete(event));

    const why = el('p', 'ds-caption ev__none');
    why.textContent = 'Removes it, everyone on it and everything raised for it.';

    remove.append(button, why);
    host.append(remove);
  }
}

// ── Oversight ───────────────────────────────────────────────────────────────

/**
 * What is outstanding, across every show on the calendar.
 *
 * The table answers "which show"; this answers "is anybody behind" — the whole
 * of the oversight job, stated as a count. On the system's own `.ds-banner`,
 * which already carries the three sync states, so the line takes its colour from
 * the worst thing in it rather than choosing one for itself.
 */
/**
 * Where the checklist lives, as the backend reports it.
 *
 * Module state rather than a parameter threaded through five painters: it is
 * one address for the whole page, it changes only when Cadence is reconfigured,
 * and every call site that would have to pass it is one more place to forget.
 */
let sheetUrl: string | null = null;

export function setSheetUrl(url: string | null): void {
  sheetUrl = url;
}

/** How near a deadline has to be before it is worth interrupting somebody. */
const SOON_DAYS = 14;

/**
 * What the banner should say, decided before anything is drawn.
 *
 * Pure, so the three states can be pinned without a browser — and they need
 * pinning, because all three were wrong: an empty calendar read as an all-clear,
 * any approved show made it permanently amber, and a show approved inside six
 * weeks was instantly red.
 */
export function oversight(events: EventRow[], today = localToday()): {
  tone: string; label: string; body: string;
} {
  // Nothing at all is its own state, and it is not a good one.
  if (!events.length) {
    return {
      tone: 'ds-banner--idle',
      label: 'Nothing on the calendar',
      body: 'Register the first show below.',
    };
  }

  const horizon = addDays(today, SOON_DAYS);
  const late = events.filter(
    (e) => e.status === 'approved' && !e.ready && e.next_due && e.next_due < today,
  ).length;
  // **Bounded.** This was any future deadline at all, and approving a show is
  // what raises its checklist — so every approved show qualified for most of its
  // life and the banner sat permanently amber. A fortnight is the window the
  // playbook's own lead times turn on: business cards at 14 days.
  const soon = events.filter(
    (e) => e.status === 'approved' && !e.ready && e.next_due
      && e.next_due >= today && e.next_due <= horizon,
  ).length;
  const undecided = events.filter(
    (e) => e.status === 'proposed' && e.days_to_decide !== null && e.days_to_decide <= 7,
  ).length;

  if (!late && !soon && !undecided) {
    return {
      tone: 'ds-banner--locked',
      label: 'Nothing outstanding',
      body: 'Every deadline is in hand.',
    };
  }

  const said: string[] = [];
  if (late) said.push(`${late} ${late === 1 ? 'show is' : 'shows are'} past a deadline`);
  if (soon) said.push(`${soon} ${soon === 1 ? 'has work' : 'have work'} due soon`);
  if (undecided) {
    said.push(`${undecided} ${undecided === 1 ? 'proposal needs' : 'proposals need'} a decision`);
  }

  return {
    tone: late ? 'ds-banner--fault' : 'ds-banner--drift',
    label: late ? 'Something is late' : 'Deadlines are close',
    body: `${said.join('. ')}.`,
  };
}


export function paintOversight(host: HTMLElement, events: EventRow[]): void {
  host.replaceChildren();

  const { tone, label: title, body: text } = oversight(events);
  const banner = el('div', 'ds-banner');
  banner.classList.add(tone);

  const label = el('span', 'ds-banner__label');
  label.textContent = title;
  const body = el('span');
  body.textContent = text;

  banner.append(label, body);
  host.append(banner);
}
