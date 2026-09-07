// The tracker, and one account opened inside it.
//
// **A `.ds-table`, grouped by where each account is in the sequence.** The page
// this replaces was a flat list of 51 rows with three filter dropdowns, which
// makes "who am I owed a touch on today" a question you answer by filtering
// rather than by looking. `lib/eventsView.ts` had already worked this out for the
// calendar — group by what the row is asking of you, and let the marks carry
// urgency within the group — and that is followed here rather than re-argued.
//
// **The account opens in place, on the system's own `.ds-twisty`.** No drawer:
// the platform had exactly one and deleted it, because it was "closed by default
// behind an unlabelled icon, and hidden outright below 72rem". The open row is
// where the trail lives — what was sent, when, and by whom — which is the thing
// the published artefact could not hold at all and the reason this surface exists.
//
// **The filters stay.** Grouping answers "what is owed"; the filters answer
// "show me the jamming campaign in the Baltics", which is a different question
// and one the campaign copy is actually organised around.
//
// Every text run is set with `textContent`. None of this is model output, but the
// notes are whatever was typed into a research pass, and a surface careful only
// with untrusted input is one where somebody has to remember which is which. The
// page it replaces escaped by hand into `innerHTML`; this does not have to.

import {
  CAMPAIGN_LABELS,
  STATUS_LABELS,
  STATUS_ORDER,
  TIER_LABELS,
  dueMark,
  localToday,
  money,
  type Campaign,
  type Counters,
  type CounterTile,
  type RowStatus,
  type TrackerRow,
  type TrailEntry,
} from './outbound';
import { icon } from './icons';

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

// ── Filtering ───────────────────────────────────────────────────────────────

export interface Filters {
  tier: string;
  campaign: string;
  status: string;
  query: string;
}

export const NO_FILTERS: Filters = { tier: '', campaign: '', status: '', query: '' };

/**
 * Whether a row survives the filters.
 *
 * The search runs over the fields somebody would actually type: the account, its
 * segment, its geography and its trigger. Not the notes — they are long, they
 * mention competitors and other accounts by name, and matching them makes the
 * search return rows that have nothing to do with the words typed.
 */
export function matches(row: TrackerRow, filters: Filters): boolean {
  if (filters.tier && String(row.tier) !== filters.tier) return false;
  if (filters.campaign && row.campaign !== filters.campaign) return false;
  if (filters.status && row.status !== filters.status) return false;

  const query = filters.query.trim().toLowerCase();
  if (!query) return true;

  return [row.account, row.segment, row.geography, row.trigger_text].some((field) =>
    (field || '').toLowerCase().includes(query),
  );
}

// ── Grouping ────────────────────────────────────────────────────────────────

export interface RowGroup {
  key: RowStatus;
  title: string;
  /** Said on the heading, where it explains the whole group at once. */
  note: string;
  /** Nothing is owed on these, so they start out of the way. */
  collapsed: boolean;
  rows: TrackerRow[];
}

const GROUP_NOTES: Record<RowStatus, string> = {
  not_started: 'nothing sent yet',
  sequencing: 'mid-sequence — these are the ones that go stale',
  replied: 'waiting on you, not on the sequence',
  meeting: 'booked',
  qualified: 'in the pipeline',
  dead: 'no longer being worked',
};

/**
 * The rows, in the order the sequence runs, with the empty groups dropped.
 *
 * Within a group the sort is **overdue first, then by tier**: a stale
 * mid-sequence account is the thing that costs a reply, and tier is the
 * tie-break because a spec author's hour is worth more than an end user's.
 */
export function groupRows(rows: TrackerRow[], today = localToday()): RowGroup[] {
  const buckets = new Map<RowStatus, TrackerRow[]>();
  for (const status of STATUS_ORDER) buckets.set(status, []);
  for (const row of rows) {
    const bucket = buckets.get(row.status);
    if (bucket) bucket.push(row);
  }

  const groups: RowGroup[] = [];
  for (const status of STATUS_ORDER) {
    const bucket = buckets.get(status) ?? [];
    if (!bucket.length) continue;
    bucket.sort((a, b) => {
      const overdue = Number(isOverdue(b, today)) - Number(isOverdue(a, today));
      if (overdue) return overdue;
      if (a.tier !== b.tier) return a.tier - b.tier;
      return a.account.localeCompare(b.account);
    });
    groups.push({
      key: status,
      title: STATUS_LABELS[status],
      note: GROUP_NOTES[status],
      collapsed: status === 'dead',
      rows: bucket,
    });
  }
  return groups;
}

function isOverdue(row: TrackerRow, today: string): boolean {
  const due = dueMark(row, today);
  return due?.label === 'overdue';
}

// ── The counter strip ───────────────────────────────────────────────────────

/**
 * One tile: the figure, what it is measured against, and a meter when there is a
 * goal. Without a goal the meter is omitted rather than drawn empty, because a
 * bar that is always empty teaches a reader to stop looking at bars.
 */
export function counterTile(tile: CounterTile): HTMLElement {
  const node = el('div', 'ob__tile');

  const value = el('span', 'ob__tilenum ds-numeric');
  value.textContent = tile.value;
  node.append(value);

  const label = el('span', 'ds-caption ob__tilelabel');
  label.textContent = tile.against ? `${tile.label} · ${tile.against}` : tile.label;
  node.append(label);

  if (tile.fraction > 0 || tile.against) {
    const meter = el('div', tile.tone === 'plain' ? 'ds-meter' : `ds-meter ds-meter--${tile.tone}`);
    const fill = el('div', 'ds-meter__fill');
    fill.style.width = `${Math.round(tile.fraction * 100)}%`;
    meter.append(fill);
    node.append(meter);
  }

  return node;
}

// ── One row ─────────────────────────────────────────────────────────────────

export interface RowHandlers {
  onTouch: (row: TrackerRow, index: number, fired: boolean) => void;
  onStatus: (row: TrackerRow, status: RowStatus) => void;
  onEdit: (row: TrackerRow, field: string, value: string) => void;
  onOpen: (row: TrackerRow) => void;
}

/**
 * The five ticks.
 *
 * Real checkboxes rather than five small buttons: a touch is a boolean, the
 * system already draws `.ds-check`, and a checkbox is reachable by keyboard and
 * announced by a screen reader without any of that being re-invented. Each one
 * names the touch it is — "LinkedIn message", not "2" — because the numbers mean
 * nothing without the playbook open beside you.
 */
export function touchCell(row: TrackerRow, handlers: RowHandlers): HTMLElement {
  const cell = el('div', 'ob__touches');
  for (const touch of row.touches) {
    const box = el('input', 'ds-check') as HTMLInputElement;
    box.type = 'checkbox';
    box.checked = touch.fired;
    box.setAttribute('aria-label', `Touch ${touch.index} · ${touch.label}`);
    box.title = touch.fired
      ? `${touch.label} — sent ${formatStamp(touch.at)} by ${touch.actor}`
      : `${touch.label} — not sent`;
    box.addEventListener('change', () => handlers.onTouch(row, touch.index, box.checked));
    cell.append(box);
  }
  return cell;
}

export function statusSelect(row: TrackerRow, handlers: RowHandlers): HTMLSelectElement {
  const select = el('select', 'ds-select ob__status') as HTMLSelectElement;
  select.setAttribute('aria-label', `Status for ${row.account}`);
  for (const status of STATUS_ORDER) {
    const option = el('option') as HTMLOptionElement;
    option.value = status;
    option.textContent = STATUS_LABELS[status];
    option.selected = status === row.status;
    select.append(option);
  }
  select.addEventListener('change', () => handlers.onStatus(row, select.value as RowStatus));
  return select;
}

/** The account, its segment, and the marks that say what it is asking for. */
export function accountCell(row: TrackerRow, today = localToday()): HTMLElement {
  const cell = el('td');

  const name = el('span', 'ds-table__primary');
  name.textContent = row.account;
  cell.append(name);

  const sub = el('span', 'ds-table__sub');
  sub.textContent = [row.segment, row.geography].filter(Boolean).join(' · ');
  cell.append(sub);

  const marks = el('div', 'ob__marks');
  const due = dueMark(row, today);
  if (due) marks.append(mark(due));
  if (!row.trigger_text) marks.append(mark({ className: 'ds-mark ds-mark--idle', label: 'no trigger' }));
  if (marks.childElementCount) cell.append(marks);

  return cell;
}

export function tierTag(tier: number): HTMLElement {
  const tag = el('span', 'ds-tag');
  tag.textContent = TIER_LABELS[tier] ?? `Tier ${tier}`;
  return tag;
}

export function campaignTag(campaign: string): HTMLElement {
  const tag = el('span', 'ds-tag');
  tag.textContent = CAMPAIGN_LABELS[campaign as Campaign] ?? (campaign || '—');
  return tag;
}

/**
 * The value cell.
 *
 * `unpriced` is set in the muted style rather than as a figure, so a gap does not
 * sit in the column looking like a number.
 */
export function valueCell(row: TrackerRow): HTMLElement {
  const cell = el('td', 'ds-table__num');
  cell.textContent = money(row.value_est_gbp);
  if (row.value_est_gbp === null) cell.classList.add('ob__unpriced');
  cell.title = row.value_note || '';
  return cell;
}

// ── The open account ────────────────────────────────────────────────────────

/**
 * What the trail says, in the order it happened.
 *
 * This is the whole gain over the page it replaces. A tick in that page was a `1`
 * in an array; here it is "Email sent 21 Aug by sam", and a status that moved
 * twice says so — which is what makes suppression decidable rather than
 * remembered.
 */
export function trail(entries: TrailEntry[]): HTMLElement {
  const list = el('ol', 'ds-log ds-log--tight ob__trail');
  if (!entries.length) {
    const empty = el('li', 'ds-caption');
    empty.textContent = 'Nothing has happened on this account yet.';
    list.append(empty);
    return list;
  }
  for (const entry of entries) {
    const item = el('li');
    const when = el('span', 'ds-mono ob__stamp');
    when.textContent = formatStamp(entry.at);
    item.append(when);

    const said = el('span');
    said.textContent = describe(entry);
    item.append(said);
    list.append(item);
  }
  return list;
}

/** One trail entry, in words rather than as a from/to pair. */
export function describe(entry: TrailEntry): string {
  const by = entry.actor ? ` by ${entry.actor}` : '';
  const via = entry.source ? ` (${entry.source})` : '';

  if (entry.kind === 'touch') {
    const sent = entry.to_value === 'fired' ? 'sent' : 'retracted';
    return `Touch ${entry.touch_index} ${sent}${by}${via}`;
  }
  if (entry.kind === 'status') {
    const from = STATUS_LABELS[entry.from_value as RowStatus] ?? entry.from_value;
    const to = STATUS_LABELS[entry.to_value as RowStatus] ?? entry.to_value;
    return `${from} → ${to}${by}${via}`;
  }
  if (entry.kind === 'value') {
    return `Value ${entry.from_value} → ${entry.to_value}${via}`;
  }
  if (entry.kind === 'edit') {
    return `${entry.to_value}${by}`;
  }
  return `${entry.kind}${by}${via}`;
}

/** A field a person owns, edited in place and saved when it loses focus. */
export function editable(
  row: TrackerRow,
  field: 'next_due' | 'procurement_route',
  label: string,
  handlers: RowHandlers,
): HTMLElement {
  const wrap = el('div', 'ob__field');

  const caption = el('label', 'ds-label');
  caption.textContent = label;
  const input = el('input', 'ds-field') as HTMLInputElement;
  input.id = `${field}-${row.id}`;
  input.value = (row as unknown as Record<string, string>)[field] ?? '';
  if (field === 'next_due') input.type = 'date';
  input.placeholder = field === 'next_due' ? '' : 'e.g. via an ERP-qualified reseller';
  caption.htmlFor = input.id;

  // Saved on blur rather than on every keystroke: each save is an appended audit
  // event, and a trail with one entry per character is a trail nobody can read.
  input.addEventListener('blur', () => {
    const current = (row as unknown as Record<string, string>)[field] ?? '';
    if (input.value !== current) handlers.onEdit(row, field, input.value);
  });

  wrap.append(caption, input);
  return wrap;
}

/**
 * How the deal is composed, or that it is not.
 *
 * A carried-over figure says so, because it cannot be repriced when the
 * catalogue moves and that is worth knowing before it is quoted.
 */
export function composition(row: TrackerRow): HTMLElement {
  const wrap = el('div', 'ob__deal');

  const heading = el('h4', 'ds-eyebrow');
  heading.textContent = 'First-deal figure';
  wrap.append(heading);

  const figure = el('p', 'ds-body');
  figure.textContent = money(row.value_est_gbp);
  wrap.append(figure);

  const note = el('p', 'ds-caption');
  note.textContent = row.value_note || 'No composition recorded.';
  wrap.append(note);

  if (!row.deal_lines.length && row.value_est_gbp !== null) {
    wrap.append(
      mark({ className: 'ds-mark ds-mark--drift', label: 'cannot be repriced' }),
    );
  }
  return wrap;
}

/**
 * A timestamp, short.
 *
 * The record stores full ISO instants; a trail of thirty of them at full length
 * is unreadable, and the year is almost never the thing in question.
 */
export function formatStamp(iso: string): string {
  if (!iso) return '—';
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return `${at.getDate()} ${months[at.getMonth()]}`;
}

// ── Assembly ────────────────────────────────────────────────────────────────

/**
 * One account, as the row you scan and the panel you open.
 *
 * Two `<tr>`s rather than a nested table: the detail row spans the full width, so
 * the columns above it stay aligned. Its contents are built the first time it is
 * opened — fifty-one trails rendered into a hidden row is work nobody asked for.
 */
export function rowPair(
  row: TrackerRow,
  handlers: RowHandlers,
  today = localToday(),
): [HTMLTableRowElement, HTMLTableRowElement] {
  const tr = el('tr', 'ob__row') as HTMLTableRowElement;
  tr.dataset.account = row.account;

  const toggleCell = el('td', 'ds-table__pick') as HTMLTableCellElement;
  const toggle = el('button', 'ob__twisty') as HTMLButtonElement;
  toggle.type = 'button';
  toggle.setAttribute('aria-expanded', 'false');
  toggle.setAttribute('aria-label', `Open ${row.account}`);
  toggle.innerHTML = `<span class="ds-twisty" data-twisty>${icon('chevron')}</span>`;
  toggleCell.append(toggle);
  tr.append(toggleCell);

  tr.append(accountCell(row, today));

  const tierTd = el('td') as HTMLTableCellElement;
  tierTd.append(tierTag(row.tier));
  tr.append(tierTd);

  const campaignTd = el('td') as HTMLTableCellElement;
  campaignTd.append(campaignTag(row.campaign));
  tr.append(campaignTd);

  const triggerTd = el('td', 'ob__trigger') as HTMLTableCellElement;
  triggerTd.textContent = row.trigger_text || '—';
  tr.append(triggerTd);

  const touchTd = el('td') as HTMLTableCellElement;
  touchTd.append(touchCell(row, handlers));
  tr.append(touchTd);

  const statusTd = el('td') as HTMLTableCellElement;
  statusTd.append(statusSelect(row, handlers));
  tr.append(statusTd);

  tr.append(valueCell(row));

  const detail = el('tr', 'ob__detail') as HTMLTableRowElement;
  detail.hidden = true;
  const detailCell = el('td') as HTMLTableCellElement;
  detailCell.colSpan = tr.childElementCount;
  detail.append(detailCell);

  // Built on first open, not up front. Fifty-one panels, each with a full audit
  // trail, is several hundred nodes nobody has asked to see — and the trail is
  // the longest part of the whole page.
  let built = false;

  toggle.addEventListener('click', () => {
    const opening = detail.hidden;
    if (opening && !built) {
      detailCell.append(accountPanel(row, handlers));
      built = true;
    }
    detail.hidden = !opening;
    toggle.setAttribute('aria-expanded', String(opening));
    toggle.querySelector('[data-twisty]')?.classList.toggle('is-open', opening);
    if (opening) handlers.onOpen(row);
  });

  return [tr, detail];
}

/** Everything about one account that does not belong in a scannable row. */
export function accountPanel(row: TrackerRow, handlers: RowHandlers): HTMLElement {
  const panel = el('div', 'ob__panel');

  const left = el('div', 'ob__panelcol');

  if (row.target_roles) {
    const roles = el('p', 'ds-body');
    roles.textContent = row.target_roles;
    const rolesHead = el('h4', 'ds-eyebrow');
    rolesHead.textContent = 'Who to approach';
    left.append(rolesHead, roles);
  }

  if (row.notes) {
    const notesHead = el('h4', 'ds-eyebrow');
    notesHead.textContent = 'Notes';
    const notes = el('p', 'ds-body');
    notes.textContent = row.notes;
    left.append(notesHead, notes);
  }

  if (row.trigger_text) {
    const head = el('h4', 'ds-eyebrow');
    head.textContent = 'Trigger';
    const body = el('p', 'ds-body');
    body.textContent = row.trigger_text;
    const source = el('p', 'ds-caption');
    source.textContent = `Source: ${row.trigger_source || 'not recorded'}`;
    left.append(head, body, source);
  }

  left.append(editable(row, 'next_due', 'Next touch due', handlers));
  left.append(editable(row, 'procurement_route', 'Procurement route', handlers));

  const right = el('div', 'ob__panelcol');
  right.append(composition(row));

  const trailHead = el('h4', 'ds-eyebrow');
  trailHead.textContent = 'What has happened';
  right.append(trailHead, trail(row.history));

  panel.append(left, right);
  return panel;
}

/** One group of accounts, with its own heading row. */
export function groupSection(
  group: RowGroup,
  handlers: RowHandlers,
  today = localToday(),
): HTMLTableSectionElement {
  const body = el('tbody', 'ob__group') as HTMLTableSectionElement;
  body.dataset.group = group.key;

  const heading = el('tr', 'ob__grouphead') as HTMLTableRowElement;
  const cell = el('th') as HTMLTableCellElement;
  cell.colSpan = 8;

  const title = el('span', 'ds-eyebrow');
  title.textContent = `${group.title} · ${group.rows.length}`;
  const note = el('span', 'ds-caption ob__groupnote');
  note.textContent = group.note;
  cell.append(title, note);
  heading.append(cell);
  body.append(heading);

  for (const row of group.rows) {
    const [tr, detail] = rowPair(row, handlers, today);
    body.append(tr, detail);
  }
  return body;
}

/** The whole table, or the reason there is nothing in it. */
export function renderTable(
  groups: RowGroup[],
  handlers: RowHandlers,
  today = localToday(),
): HTMLElement {
  if (!groups.length) {
    const empty = el('div', 'ds-empty ds-empty--inline');
    const title = el('p', 'ds-empty__title');
    title.textContent = 'No accounts match';
    const body = el('p', 'ds-empty__body');
    body.textContent = 'Clear a filter, or widen the search.';
    empty.append(title, body);
    return empty;
  }

  const wrap = el('div', 'ob__tablewrap');
  const table = el('table', 'ds-table ob__table');
  const head = el('thead');
  const headRow = el('tr');
  for (const label of ['', 'Account', 'Tier', 'Campaign', 'Trigger', 'Touches', 'Status', 'First deal']) {
    const th = el('th');
    th.textContent = label;
    headRow.append(th);
  }
  head.append(headRow);
  table.append(head);
  for (const group of groups) table.append(groupSection(group, handlers, today));
  wrap.append(table);
  return wrap;
}

// ── Choosing between campaigns ──────────────────────────────────────────────

export interface CampaignTab {
  id: string;
  name: string;
  /** Said under the name: how far this campaign has got, at a glance. */
  progress: string;
  active: boolean;
}

/**
 * One tab per live campaign, including when there is only one.
 *
 * **The strip is the campaign's identity band, not a switcher.** An earlier
 * version hid it below two campaigns, on the grounds that a lone tab offers no
 * choice — but that made the header change shape as campaigns came and went, so
 * the same page had two different layouts depending on a count nobody is
 * thinking about. A single tab still does the work: it names the campaign and
 * says how far it has got, which is what the band is for.
 *
 * The counts sit on the tab because that is the question you come to the strip to
 * answer — which of these is moving — and reading it would otherwise mean
 * selecting each in turn.
 *
 * Empty only when there is no campaign at all, which is when the whole section
 * is hidden anyway.
 */
export function campaignTabs(
  campaigns: Array<{ id: string; name: string; counters: Counters }>,
  activeId: string,
): CampaignTab[] {
  return campaigns.map((campaign) => ({
    id: campaign.id,
    name: campaign.name,
    progress: tabProgress(campaign.counters),
    active: campaign.id === activeId,
  }));
}

/**
 * What a tab says about its campaign, beyond its name.
 *
 * Qualified where there is any, because that is the number the goal is measured
 * in; otherwise how much is in sequence, because that is the next thing to move.
 * A campaign nobody has started says so rather than showing two zeros.
 */
export function tabProgress(counters: Counters): string {
  if (counters.qualified) {
    return `${counters.qualified} qualified · ${counters.targets} accounts`;
  }
  if (counters.in_sequence) {
    return `${counters.in_sequence} of ${counters.targets} in sequence`;
  }
  return `${counters.targets} accounts, none started`;
}

/** The strip itself. `onSelect` is called with the campaign's id. */
export function renderCampaignTabs(
  tabs: CampaignTab[],
  onSelect: (id: string) => void,
): HTMLElement {
  const strip = el('div', 'ds-tabs camp__tabs');
  strip.setAttribute('role', 'tablist');
  strip.setAttribute('aria-label', 'Active campaigns');

  for (const tab of tabs) {
    const button = el('button', tab.active ? 'ds-tab is-active' : 'ds-tab') as HTMLButtonElement;
    button.type = 'button';
    button.setAttribute('role', 'tab');
    button.setAttribute('aria-selected', String(tab.active));
    if (!tab.active) button.tabIndex = -1;
    button.dataset.campaign = tab.id;

    const name = el('span', 'camp__tabname');
    name.textContent = tab.name;
    const progress = el('span', 'ds-caption camp__tabprogress');
    progress.textContent = tab.progress;
    button.append(name, progress);

    button.addEventListener('click', () => onSelect(tab.id));
    strip.append(button);
  }
  return strip;
}
