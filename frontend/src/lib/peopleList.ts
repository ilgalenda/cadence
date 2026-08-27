// The people X-ray found, and the two things you can do with them.
//
// Extracted from `work/agents/xray.astro` so the X-ray page and a path's X-ray
// step share one list rather than two that drift. What matters is not the
// markup — it is that the **rules about spending credit live in one place**:
//
//   * discovery is free and broad; enrichment only ever runs on rows a human
//     ticked, never on the whole result set;
//   * email arrives with the record, but the phone is a separate action per
//     person, because it spends again;
//   * a person who already has contact details shows them instead of offering
//     to buy them a second time.
//
// A second implementation of this in the runner would be a second opinion about
// when it is acceptable to spend money.
//
// **A `.ds-table`, grouped by what you can do with the person.**
//
// This went table → records → cards before arriving back here, and the reason
// the round trip happened is worth stating: **the design system had already
// drawn this screen and nobody opened the card.**
// `design-system/preview/components-data.html` specifies X-ray's people table
// person for person — pick · Person · Signal · Contact · Fit — with a `.ds-bulk`
// bar above it and a note explaining why Fit is mono and right-aligned.
//
// The two complaints that drove the earlier retreat were both real, and both
// are answered inside the system rather than by leaving it:
//
//   * the 11–33 Fit score "meant nothing to a reader" because it had **no column
//     header**. The demo gives it one. A labelled column is the fix; deleting
//     the number was not.
//   * the argument was truncated to 34 characters because it was forced into
//     `.ds-table__sub`, which is specified `max-width: 26ch` and ellipsised —
//     a one-line secondary for *role · company*, which is exactly what the demo
//     puts in it. The argument was never that cell's job.
//
// So **the argument gets a disclosure row**: each person is one scannable row,
// and the name opens a full-width `<td colspan>` carrying `match_reason` at
// `--measure-read`, on the system's own `.ds-twisty`. The table stays comparable
// down its columns and no sentence is cut.
//
// The backend's `recommended_path` grouping *is* the decision — a confirmed
// profile you can write to, a profile that needs an email bought, and a name
// some page mentioned — so it stays, as `.agent-page__sect` heads, with "Context
// only" collapsed because nobody is approaching those people.
//
// One thing the cards had is deliberately dropped: the sky field on the primary
// group. The reasoning that put it there ("white cards on a sky ground keep
// every wash pill and muted line at the contrast it was drawn for") argues
// against it now the container is a table — `tr:hover` at 0.03 ink and
// `tr.is-selected` at `--accent-wash` are drawn for the white field, and a
// tinted region underneath them is the thing that would flatten both.
//
// Screen design: `design-system/preview/screen-xray.html`,
// table spec: `design-system/preview/components-data.html`.

import { icon } from './icons';
import { notify, promptText, toast } from './overlays';
import type { Person } from './paths';

/** Confidence reads through the sync vocabulary: high locked, medium drift. */
const CONFIDENCE_MARK: Record<string, string> = {
  high: 'ds-mark--locked', medium: 'ds-mark--drift', low: 'ds-mark--idle',
};

/**
 * LinkedIn URLs that are not a person.
 *
 * The exact mirror of `ranking.NON_PROFILE_LINKEDIN` in the backend, which
 * exists because these reach Lusha as a match key and, in canon's words, "both
 * waste credit and corrupt dedupe". The backend only *penalises* them by two
 * points of actionability, which pushes such a row down inside its tier and
 * leaves it perfectly selectable — and `services/enrichment.py` still forwards
 * whatever URL the row carries. So the guard has to exist here too, at the point
 * where the spending decision is actually made.
 */
const NON_PROFILE_LINKEDIN = /linkedin\.com\/(search|company|pub\/dir|jobs)\//i;

/**
 * Whether this is a real profile URL — one worth linking, and safe to enrich on.
 *
 * Pure, so it can be tested without a browser (this repo has no jsdom on
 * purpose, see `dom.test.ts`).
 */
export function isProfileUrl(url: unknown): boolean {
  const value = typeof url === 'string' ? url.trim() : '';
  if (!value) return false;
  if (!/linkedin\.com\//i.test(value)) return false;
  return !NON_PROFILE_LINKEDIN.test(value);
}

/**
 * Who an automatic email reveal should actually run on.
 *
 * Two exclusions, and both save real money rather than being tidiness:
 *
 *   * **a non-profile URL** would be sent to Lusha as the match key and buy a
 *     credit against a search page — the defect `isProfileUrl` exists for;
 *   * **`campaign_context`** people had their profile *inferred, not confirmed*,
 *     which the group heading says out loud. Nobody approaches them, so buying
 *     an address for them is spending on a row that exists to be read.
 *
 * A person who already has an email is never re-bought, which is the rule this
 * module has always held.
 */
export function autoEnrichTargets(people: Person[]): Person[] {
  return people.filter((person) => !person._email
    && person.recommended_path !== 'campaign_context'
    && (isProfileUrl(person.linkedin_url) || Boolean(person.company_domain)));
}

/**
 * The person as the provider should see them, with a corrupt match key removed.
 *
 * `services/enrichment.py` forwards whatever `linkedin_url` the row carries,
 * with no validation — so a people-search URL becomes the key Lusha matches on,
 * which canon says "both wastes credit and corrupts dedupe". Excluding the
 * person would be the wrong fix: their name and company domain are a perfectly
 * good key, and the search page is the only bad part of the row.
 *
 * So the URL is dropped from the *payload* and the person is left alone. Pure,
 * and returns the same object when there is nothing to strip, so the position
 * join the enrich response depends on is never disturbed.
 */
export function enrichPayload(person: Person): Person {
  if (!person.linkedin_url || isProfileUrl(person.linkedin_url)) return person;
  const { linkedin_url: _dropped, ...rest } = person;
  return rest;
}

/** A stable key per person, so selection survives a re-render. */
const keyOf = (person: Person, index: number): string =>
  person.linkedin_url || `${person.full_name}-${index}`;

// ── The groups ──────────────────────────────────────────────────────────────

export interface PersonGroup {
  path: string;
  title: string;
  /** Said on the heading, where it explains the whole group at once. */
  note?: string;
  /** Nobody approaches these, so they start out of the way. */
  collapsed?: boolean;
  people: Person[];
}

const GROUP_ORDER: Array<Omit<PersonGroup, 'people'>> = [
  {
    path: 'linkedin_direct',
    title: 'Ready to approach',
  },
  {
    path: 'email_enrichment',
    title: 'Found, needs an email',
  },
  {
    path: 'campaign_context',
    title: 'Context only',
    note: 'the profile was inferred, not confirmed',
    collapsed: true,
  },
];

/** Signal sweeps return people unranked and ungrouped, so they get one heading. */
const UNGROUPED: Omit<PersonGroup, 'people'> = { path: '', title: 'Found' };

/**
 * Split people into the groups the page shows, in order, dropping empty ones.
 *
 * Pure, so the grouping can be tested without a browser — this repo has no jsdom
 * on purpose (see `dom.test.ts`).
 */
export function groupPeople(people: Person[]): PersonGroup[] {
  const known = new Set(GROUP_ORDER.map((g) => g.path));
  const groups: PersonGroup[] = [];

  for (const spec of GROUP_ORDER) {
    const matching = people.filter((p) => p.recommended_path === spec.path);
    if (matching.length) groups.push({ ...spec, people: matching });
  }

  // Anything with no recommended_path at all — a signal sweep — still has to
  // appear, and appear last, since it carries no claim about reachability.
  const rest = people.filter((p) => !known.has(p.recommended_path));
  if (rest.length) groups.push({ ...UNGROUPED, people: rest });

  return groups;
}

/** The confidence the model reported, and the mark that states it. */
export function confidenceOf(person: Person): { label: string; mark: string } {
  const label = String(person.confidence || 'low').toLowerCase();
  return { label, mark: CONFIDENCE_MARK[label] ?? 'ds-mark--idle' };
}

/**
 * A per-person way onward.
 *
 * Deliberately a link and not a callback. Every action this module owns spends
 * provider credit and is written above; anything a *caller* injects must not,
 * and an `href` cannot. The type is the rule.
 */
export interface PersonAction {
  label: string;
  href: (person: Person) => string;
  title?: string;
}

export interface PeopleListOptions {
  /** Everyone starts ticked — used when reopening a saved shortlist. */
  selectAll?: boolean;
  /** Offer "Save shortlist". Off where a run has nowhere to save to yet. */
  allowSave?: boolean;
  /** What produced these people — stored with a saved shortlist. */
  source?: string;
  /** Called whenever the selection changes, with the current count. */
  onSelectionChange?: (count: number) => void;
  /** Called after a shortlist is saved, so a caller can refresh its list. */
  onSaved?: () => void;
  /**
   * Render the bulk bar here instead of inside the list.
   *
   * The workspace pins it above the scroller, so it has to live outside the
   * element that scrolls. Given nothing, it stays where it always was.
   */
  bulkMount?: HTMLElement;
  /** Ways onward from a single person. Navigation only — see `PersonAction`. */
  personActions?: PersonAction[];
  /**
   * Buy an email for every approachable person as soon as they arrive.
   *
   * Off unless a caller asks, because it is the one option here that spends
   * money without anybody pressing anything. See `autoEnrich`.
   */
  autoEnrich?: boolean;
}

export interface PeopleList {
  /** The people on screen, carrying any details revealed since. */
  people: Person[];
  /** Those currently ticked, in list order. */
  selected(): Person[];
  /** Re-render with a different set, resetting selection. */
  render(people: Person[], options?: PeopleListOptions): void;
  /** Placeholder records while a search runs, so the page keeps its shape. */
  skeleton(rows?: number): void;
  /** Empty the list and the selection. */
  clear(): void;
  /** The saved shortlist this list is currently showing, if any. */
  openShortlist: { id: string; name: string } | null;
}

/**
 * Build the list into `mount`, which must be empty — it owns its markup.
 *
 * Returns a handle rather than exposing the DOM, so callers can read the
 * selection and re-render without knowing how any of it is drawn.
 */
export function createPeopleList(mount: HTMLElement, options: PeopleListOptions = {}): PeopleList {
  let settings: PeopleListOptions = { ...options };
  let people: Person[] = [];
  const selected = new Set<string>();
  /** Group paths the person has opened or shut by hand, so a re-render obeys them. */
  const overridden = new Map<string, boolean>();

  const personActions = settings.personActions ?? [];

  // The bulk bar is a charcoal pill that states the count, with the actions as
  // pills inside it. Saving is the committing action, so it wears primary;
  // revealing spends provider credit, so it stays a secondary the person
  // reaches for rather than the default.
  const bulkMarkup = `
    <div class="pl__bulk" data-bulk hidden>
      <div class="ds-bulk">
        <span class="ds-bulk__count" data-count></span>
        <span class="ds-bulk__spacer"></span>
        <button class="ds-btn ds-btn--secondary ds-btn--sm" type="button" data-enrich>Reveal emails</button>
        <button class="ds-btn ds-btn--primary ds-btn--sm" type="button" data-save hidden>Save shortlist</button>
      </div>
    </div>`;

  const bulkHost = settings.bulkMount;
  if (bulkHost) bulkHost.innerHTML = bulkMarkup;

  mount.innerHTML = `${bulkHost ? '' : bulkMarkup}`
    + '<p class="pl__auto" data-auto hidden><span class="ds-mark ds-mark--live" data-auto-text></span></p>'
    + '<div data-groups></div>';

  // The bulk bar may now live outside `mount`, so look for each part where it is.
  const find = <T extends HTMLElement>(attr: string) =>
    (bulkHost?.querySelector(`[${attr}]`) ?? mount.querySelector(`[${attr}]`)) as T;
  const bulk = find('data-bulk');
  const countLabel = find('data-count');
  const saveBtn = find<HTMLButtonElement>('data-save');
  const enrichBtn = find<HTMLButtonElement>('data-enrich');
  const groupHost = mount.querySelector('[data-groups]') as HTMLElement;
  // The paragraph is what hides, not the mark inside it: an empty `<p>` keeps
  // its bottom margin and left a permanent gap above every table.
  const autoRow = mount.querySelector('[data-auto]') as HTMLElement;
  const autoMark = mount.querySelector('[data-auto-text]') as HTMLElement;

  const list: PeopleList = {
    get people() { return people; },
    selected: () => people.filter((person, i) => selected.has(keyOf(person, i))),
    render,
    skeleton,
    clear,
    openShortlist: null,
  };

  function render(next: Person[], override: PeopleListOptions = {}): void {
    settings = { ...settings, ...override };
    const selectAll = Boolean(settings.selectAll);

    people = next;
    selected.clear();
    if (selectAll) people.forEach((person, i) => selected.add(keyOf(person, i)));

    groupHost.innerHTML = '';
    groupHost.appendChild(tableFor(groupPeople(people), selectAll));
    refreshBulk();

    // After the rows exist, so an address lands in a cell that is already on
    // screen rather than arriving with the table.
    if (settings.autoEnrich) autoEnrich();
  }

  /**
   * Every group in **one** table.
   *
   * A table per group was the first attempt and it was wrong twice over: each
   * table sized its own columns, so "Ready to approach" and "Found, needs an
   * email" did not line up under each other — and a table exists so that a
   * person can be compared with the one below them. It also repeated the column
   * headers once per group, which is three rows of `Person · Signal · Contact ·
   * Fit` on a page with three groups.
   *
   * One `<table>`, one `<thead>`, and a `<tbody>` per group — which is what
   * multiple tbodies are for. The group's heading is a full-width row inside it,
   * so the hairline and the mono count still read as the platform's section head
   * while living in the table the columns belong to.
   */
  /**
   * The column header, shared by the real table and the skeleton.
   *
   * Shared because the skeleton exists to stop the page jumping when the answer
   * lands, and a skeleton without the header sizes its columns differently from
   * the table that replaces it — which is the jump, just delayed.
   *
   * `pick` carries the select-all only when there is something to select.
   */
  function headMarkup(pick: boolean): string {
    return `
      <thead>
        <tr>
          <th class="ds-table__pick">${pick
            ? '<input class="ds-check" type="checkbox" data-all aria-label="Select everyone found" />'
            : ''}</th>
          <th class="pl__colwide">Person</th>
          <th title="How sure the model is that this is the right person — its own word, not a verification.">Confidence</th>
          <th>Email</th>
          <th>Phone</th>
          <th class="ds-table__num" title="Ranked from reachability and the model's own confidence. Mechanical, not a judgement of whether the person is worth approaching.">Fit</th>
          <th></th>
        </tr>
      </thead>`;
  }

  function tableFor(groups: PersonGroup[], picked: boolean): HTMLElement {
    const wrap = document.createElement('div');
    wrap.className = 'pl__tablewrap';
    wrap.innerHTML = `<table class="ds-table">${headMarkup(true)}</table>`;

    const table = wrap.querySelector('table')!;
    groups.forEach((group) => group.people.length && table.appendChild(bodyFor(group, picked)));

    // Ticking the head ticks everyone shown. It spends nothing — revealing is
    // still a separate press on the bulk bar — so it is a convenience, not a
    // commitment.
    const all = wrap.querySelector('[data-all]') as HTMLInputElement;
    all.addEventListener('change', () => {
      table.querySelectorAll<HTMLInputElement>('[data-pick]').forEach((pick) => {
        if (pick.checked !== all.checked) pick.click();
      });
    });

    return wrap;
  }

  function bodyFor(group: PersonGroup, picked: boolean): HTMLElement {
    const body = document.createElement('tbody');
    body.className = 'pl__band';

    // A person who reopens "Context only" and re-runs a search means it; a
    // remembered choice is the difference between a disclosure and a nag.
    const open = overridden.get(group.path) ?? !group.collapsed;

    // The group's heading is the platform's section head — eyebrow left, hairline
    // to sit on, the count in mono on the right, because the count is the machine
    // talking. The disclosure lives on the eyebrow so the count stays a readout
    // rather than becoming part of a control.
    const head = document.createElement('tr');
    head.className = 'pl__grouprow';
    head.innerHTML = `
      <td colspan="7">
        <div class="agent-page__sect">
          <button class="pl__grouphead" type="button" data-toggle aria-expanded="${open}">
            <span class="ds-twisty${open ? ' is-open' : ''}" data-twisty>${icon('chevron')}</span>
            <span class="ds-eyebrow" data-title></span>
            <span class="pl__groupnote" data-note></span>
          </button>
          <span class="ds-mono" data-count></span>
        </div>
      </td>`;
    head.querySelector('[data-title]')!.textContent = group.title;
    head.querySelector('[data-count]')!.textContent = String(group.people.length);
    head.querySelector('[data-note]')!.textContent = group.note ?? '';
    body.appendChild(head);

    const rows: HTMLElement[] = [];
    group.people.forEach((person) => rowsFor(person, picked).forEach((row) => {
      rows.push(row);
      body.appendChild(row);
    }));

    // Collapsing hides the people, never the heading — the heading is how the
    // group is reopened, and how it says how many are behind it.
    const paintOpen = (next: boolean): void => {
      rows.forEach((row) => { row.hidden = !next; });
    };
    // A disclosure row inside a shut group must not spring open with it.
    const restoreWhyRows = (): void => {
      body.querySelectorAll<HTMLElement>('.pl__whyrow').forEach((row) => {
        const toggle = row.previousElementSibling?.querySelector('[data-why-toggle]');
        row.hidden = toggle?.getAttribute('aria-expanded') !== 'true';
      });
    };
    if (!open) paintOpen(false);

    const toggle = head.querySelector('[data-toggle]') as HTMLButtonElement;
    const twisty = head.querySelector('[data-twisty]') as HTMLElement;
    toggle.addEventListener('click', () => {
      const next = toggle.getAttribute('aria-expanded') !== 'true';
      paintOpen(next);
      if (next) restoreWhyRows();
      toggle.setAttribute('aria-expanded', String(next));
      twisty.classList.toggle('is-open', next);
      overridden.set(group.path, next);
    });

    return body;
  }

  /**
   * One person as two rows: the record, and the argument for them.
   *
   * The argument is a second `<tr>` rather than a cell in the first, because a
   * 1-2 sentence case needs the reading measure and a table cell cannot give it
   * one without making every row as tall as the longest reason. Collapsed by
   * default: the table is for scanning, the argument is for deciding, and those
   * are two different moments.
   */
  function rowsFor(person: Person, picked: boolean): HTMLElement[] {
    // The index into `people`, not into the group — selection and the enrichment
    // join both count against the whole result set.
    const index = people.indexOf(person);
    const why = person.signal_context || person.match_reason || '';
    const confidence = confidenceOf(person);

    const row = document.createElement('tr');
    row.className = 'pl__row';
    row.innerHTML = `
      <td class="ds-table__pick">
        <input class="ds-check" type="checkbox" data-pick aria-label="Select this person" />
      </td>
      <td class="pl__colwide">
        <div class="pl__who">
          <button class="pl__twisty" type="button" data-why-toggle aria-expanded="false"
                  aria-label="Why this person">
            <span class="ds-twisty" data-twisty>${icon('chevron')}</span>
          </button>
          <span class="pl__whoname">
            <span class="ds-table__primary" data-name></span>
            <span class="ds-table__sub" data-role></span>
          </span>
        </div>
      </td>
      <td><span class="ds-mark ${confidence.mark}">${confidence.label}</span></td>
      <td class="ds-table__id" data-email></td>
      <td class="ds-table__id" data-phone></td>
      <td class="ds-table__num" data-fit></td>
      <td class="pl__actcell"><span class="pl__acts" data-actions></span></td>`;

    // Every value here came from a web search — set as text, never as markup.
    //
    // The name is the way to the profile. X-ray's whole first group is called
    // "Ready to approach", meaning *approach them on LinkedIn* — and until now
    // the URL it found was read only as a dedupe key and an enrichment match
    // key, never rendered, so the one thing the group's name promised was the
    // one thing the row could not do. A non-profile URL is left as plain text
    // rather than linked: `isProfileUrl` says why.
    const label = person.full_name || person.name || '—';
    const nameCell = row.querySelector('[data-name]') as HTMLElement;
    if (isProfileUrl(person.linkedin_url)) {
      const link = document.createElement('a');
      link.className = 'pl__profile';
      link.href = String(person.linkedin_url);
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = label;
      link.title = 'Open the LinkedIn profile this search found';
      nameCell.appendChild(link);
    } else {
      nameCell.textContent = label;
    }
    // The job title only. Every person in one search works at the same company,
    // which the result section head already names — repeating it in every row
    // spent the 26ch `.ds-table__sub` is ellipsised at on the word "Northgate" and
    // truncated the title that distinguishes one person from the next. The
    // company stays in the tooltip, where a reopened shortlist can still show it.
    const roleCell = row.querySelector('[data-role]') as HTMLElement;
    roleCell.textContent = person.job_title || '';
    const full = [person.job_title, person.company].filter(Boolean).join(' · ');
    if (full) roleCell.title = full;

    // Fit is a number a person compares down the column, so it is tabular and
    // right-aligned, per the table spec. Absent rather than zero when unranked:
    // a signal sweep returns people the ranker never scored.
    const fit = row.querySelector('[data-fit]') as HTMLElement;
    const score = person.intent_score;
    fit.textContent = typeof score === 'number' ? String(score) : '—';
    if (typeof score !== 'number') fit.classList.add('pl__fit--none');

    // Built before the pick handler, which keeps the two rows' selection in step.
    const reason = document.createElement('tr');
    reason.className = 'pl__whyrow';
    reason.hidden = true;
    reason.innerHTML = '<td></td><td colspan="6"><div class="pl__whybody">'
      + '<p class="pl__why" data-why></p>'
      + '<p class="pl__found" data-found hidden></p></div></td>';
    reason.querySelector('[data-why]')!.textContent = why || 'No argument was returned for this person.';

    // How this person was found, which the response has carried all along and
    // nothing rendered. It is the difference between trusting a row and being
    // able to check it: a match_reason is the model's claim, `source_query` is
    // the evidence trail that produced the claim.
    const found = reason.querySelector('[data-found]') as HTMLElement;
    const trail = [
      person.source_query ? `found by ${person.source_query}` : '',
      person.company_domain ? String(person.company_domain) : '',
    ].filter(Boolean).join('  ·  ');
    found.textContent = trail;
    found.hidden = !trail;

    const pick = row.querySelector<HTMLInputElement>('[data-pick]')!;
    pick.checked = picked;
    row.classList.toggle('is-selected', picked);
    reason.classList.toggle('is-selected', picked);
    pick.addEventListener('change', () => {
      const key = keyOf(person, index);
      pick.checked ? selected.add(key) : selected.delete(key);
      row.classList.toggle('is-selected', pick.checked);
      reason.classList.toggle('is-selected', pick.checked);
      refreshBulk();
    });

    // Details already on the record were paid for once already.
    const emailCell = row.querySelector('[data-email]') as HTMLElement;
    emailCell.setAttribute('data-person-index', String(index));
    if (person._email) {
      showLink(emailCell, `mailto:${person._email}`, person._email);
    } else if (settings.autoEnrich && autoEnrichTargets([person]).length) {
      // An address is on its way. Only for the rows actually in the batch.
      setEmpty(emailCell, 'pending…');
    } else {
      // Nothing is coming for this row unless a human asks: it is either an
      // inferred profile the automatic pass skips, or automatic reveal is off.
      // Saying "pending" here would be a promise the page cannot keep — which is
      // what it said, forever, for every context-only person.
      setEmpty(emailCell, 'not bought');
      (emailCell as HTMLElement).title =
        'Skipped by the automatic reveal. Tick the row and press Reveal emails to buy one.';
    }

    const phoneCell = row.querySelector('[data-phone]') as HTMLElement;
    const actionCell = row.querySelector('[data-actions]')!;

    if (person._phone) {
      showLink(phoneCell, `tel:${person._phone}`, person._phone);
    } else {
      const reveal = document.createElement('button');
      reveal.type = 'button';
      reveal.className = 'ds-btn ds-btn--ghost ds-btn--sm';
      reveal.textContent = 'Reveal';
      reveal.title = 'Buy this number — a separate charge from the email';
      reveal.addEventListener('click', () => revealPhone(person, phoneCell, reveal));
      phoneCell.appendChild(reveal);
    }

    // The way onward wears secondary, not ghost: it is the next step in the
    // chain, and as a ghost link it read as metadata beside "not revealed".
    personActions.forEach((action) => {
      const link = document.createElement('a');
      link.className = 'ds-btn ds-btn--secondary ds-btn--sm';
      link.href = action.href(person);
      link.textContent = action.label;
      if (action.title) link.title = action.title;
      actionCell.appendChild(link);
    });

    // ── The argument ────────────────────────────────────────────────────────
    const toggle = row.querySelector('[data-why-toggle]') as HTMLButtonElement;
    const twisty = row.querySelector('[data-twisty]') as HTMLElement;
    toggle.addEventListener('click', () => {
      const open = reason.hidden;
      reason.hidden = !open;
      row.classList.toggle('is-open', open);
      toggle.setAttribute('aria-expanded', String(open));
      twisty.classList.toggle('is-open', open);
    });

    return [row, reason];
  }

  /**
   * Hold the page's shape while a search runs.
   *
   * Emptying it would read as "nobody found" for the twenty seconds before the
   * answer arrives, which is the one thing it must not say.
   */
  function skeleton(count = 6): void {
    clear();
    const wrap = document.createElement('div');
    wrap.className = 'pl__tablewrap';
    wrap.innerHTML = `<table class="ds-table">${headMarkup(false)}</table>`;
    const table = wrap.querySelector('table')!;
    const body = document.createElement('tbody');
    for (let i = 0; i < count; i += 1) {
      const row = document.createElement('tr');
      // No head and no checkboxes: nothing here can be ticked yet, and offering
      // a control that does nothing is worse than the wait it decorates.
      row.innerHTML = `
        <td class="ds-table__pick"></td>
        <td class="pl__colwide"><span class="ds-skeleton pl__skeleton pl__skeleton--name"></span></td>
        <td><span class="ds-skeleton pl__skeleton pl__skeleton--mark"></span></td>
        <td><span class="ds-skeleton pl__skeleton pl__skeleton--id"></span></td>
        <td class="ds-table__num"><span class="ds-skeleton pl__skeleton pl__skeleton--fit"></span></td>
        <td></td>`;
      body.appendChild(row);
    }
    table.appendChild(body);
    groupHost.appendChild(wrap);
  }

  function clear(): void {
    people = [];
    selected.clear();
    autoRow.hidden = true;
    groupHost.innerHTML = '';
    refreshBulk();
  }

  /** The muted state of an identifier cell — pending, or nothing on file. */
  function setEmpty(cell: Element, text: string): void {
    cell.textContent = '';
    const none = document.createElement('span');
    none.className = 'ds-table__id--empty';
    none.textContent = text;
    cell.appendChild(none);
  }

  function showLink(cell: Element, href: string, text: string): void {
    cell.textContent = '';
    const link = document.createElement('a');
    link.href = href;
    link.textContent = text;
    cell.appendChild(link);
  }

  function refreshBulk(): void {
    bulk.hidden = selected.size === 0;
    // A selection always states its count — and against what it was drawn from.
    countLabel.textContent = `${selected.size} of ${people.length} selected`;
    saveBtn.hidden = !settings.allowSave;
    saveBtn.textContent = list.openShortlist ? 'Update shortlist' : 'Save shortlist';
    settings.onSelectionChange?.(selected.size);
  }

  // ── Enrichment ────────────────────────────────────────────────────────────

  /**
   * Buy email addresses for these people and paint them into their rows.
   *
   * One implementation, called from two places — the bulk button and the
   * automatic pass after a search. A second copy would be a second opinion about
   * when it is acceptable to spend money, which is the thing this module exists
   * to prevent.
   *
   * The provider charges per person revealed and the route is all-or-nothing: it
   * wraps the whole batch in one `except` and returns 502, so a single bad row
   * loses every result in the call — and the credits may already have been
   * charged upstream. Hence `autoEnrichTargets` filtering the batch *before* it
   * is sent rather than hoping the provider is forgiving.
   */
  async function revealEmails(chosen: Person[]): Promise<{ found: number; asked: number }> {
    if (!chosen.length) return { found: 0, asked: 0 };

    const res = await fetch('/api/sales/xray/enrich', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      // Sent with any non-profile URL stripped: it is the person's match key and
      // a search page is not a person. See `enrichPayload`.
      body: JSON.stringify({ people: chosen.map(enrichPayload) }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `Enrichment failed (${res.status})`);

    // Joined on position, not name. The response comes back one row per person
    // sent, in the order sent, so `chosen[i]` is the person `enriched[i]`
    // describes. Matching on name looked equivalent and was not: two people
    // can share one, and discovery sometimes returns an abbreviated name that
    // no provider record will ever equal.
    const enriched: Array<{ email?: string | null }> = await res.json();

    let found = 0;
    enriched.forEach((contact, i) => {
      const person = chosen[i];
      if (!person) return;

      // Grouping means a person's record is no longer at a predictable offset,
      // so the cell is found by the index it was stamped with.
      const index = people.indexOf(person);
      const cell = groupHost.querySelector(`[data-email][data-person-index="${index}"]`);

      if (contact?.email) {
        found += 1;
        person._email = contact.email;
        if (cell) showLink(cell, `mailto:${contact.email}`, contact.email);
      } else if (cell) {
        // Asked and answered: the provider had nothing. Distinct from "pending",
        // and the row must stop implying an address is on its way.
        setEmpty(cell, 'none on file');
      }
    });

    return { found, asked: chosen.length };
  }

  /**
   * Reveal every address worth buying, as soon as the people arrive.
   *
   * Sam's call: an email should be on the row, not two clicks away. What that
   * changes is the spend — this buys for the whole approachable set rather than
   * the two or three that were ticked — so the batch is narrowed to the people
   * an address is actually usable for (`autoEnrichTargets`) and the page says
   * what it is doing while it does it.
   *
   * No meter and no denominator: it is **one** bulk request, so "7 of 12" would
   * be invented progress. It says how many it is buying, which is true.
   */
  async function autoEnrich(): Promise<void> {
    const targets = autoEnrichTargets(people);
    if (!targets.length) { autoRow.hidden = true; return; }

    autoRow.hidden = false;
    autoMark.textContent = `revealing ${targets.length} email${targets.length === 1 ? '' : 's'}`;
    try {
      const { found, asked } = await revealEmails(targets);
      autoRow.hidden = true;
      if (found < asked) toast(`${found} of ${asked} had an email on file.`);
    } catch (err: any) {
      // Never a modal. The search succeeded and the shortlist is usable without
      // an address on every row; an automatic step that nobody asked for must
      // not interrupt the work it was meant to save time on.
      autoRow.hidden = true;
      groupHost.querySelectorAll('[data-email]').forEach((cell) => {
        if (cell.querySelector('a')) return;
        setEmpty(cell, 'reveal failed');
      });
      toast(err?.message || 'Emails could not be revealed. Select rows and try again.');
    }
  }

  enrichBtn.addEventListener('click', async () => {
    const chosen = list.selected().filter((person) => !person._email);
    if (!chosen.length) {
      toast('Everyone selected already has an email.');
      return;
    }

    enrichBtn.disabled = true;
    enrichBtn.textContent = 'Revealing…';
    try {
      const { found, asked } = await revealEmails(chosen);
      toast(found === asked
        ? `${found} email${found === 1 ? '' : 's'} revealed.`
        : `${found} of ${asked} had an email on file.`);
    } catch (err: any) {
      notify({ title: 'Enrichment failed', body: err?.message || 'The provider did not respond.' });
    } finally {
      enrichBtn.disabled = false;
      enrichBtn.textContent = 'Reveal emails';
    }
  });

  async function revealPhone(person: Person, cell: Element, button: HTMLButtonElement): Promise<void> {
    button.disabled = true;
    button.textContent = '…';
    try {
      const res = await fetch('/api/sales/xray/reveal-phone', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ person }),
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'No number available');

      const { phone } = await res.json();
      // The button sits in the actions cell and the number lands in Contact, so
      // the control has to take itself away — left behind it would offer to buy
      // a second time what the row is now showing.
      button.remove();
      if (phone) {
        person._phone = phone;
        showLink(cell, `tel:${phone}`, phone);
      } else {
        cell.textContent = '';
        const none = document.createElement('span');
        none.className = 'ds-table__id--empty';
        none.textContent = 'no number on file';
        cell.appendChild(none);
      }
    } catch (err: any) {
      button.disabled = false;
      button.textContent = 'Reveal phone';
      notify({ title: 'Could not reveal a number', body: err?.message || 'The provider did not respond.' });
    }
  }

  // ── Saving ────────────────────────────────────────────────────────────────
  // The shortlist is the set that was ticked, so saving sits beside revealing
  // and acts on the same selection.

  saveBtn.addEventListener('click', async () => {
    const chosen = list.selected();
    if (!chosen.length) return;

    const name = await promptText({
      title: list.openShortlist ? 'Update this shortlist' : 'Save this shortlist',
      label: 'Name',
      value: list.openShortlist?.name || settings.source || '',
      placeholder: 'Northgate — infrastructure',
      confirm: list.openShortlist ? 'Update' : 'Save',
    });
    if (name === null) return;
    if (!name.trim()) {
      notify({
        title: 'Give the shortlist a name',
        body: 'A shortlist you cannot recognise later has not been kept, it has been lost.',
      });
      return;
    }

    saveBtn.disabled = true;
    try {
      const res = await fetch('/api/sales/xray/shortlists', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: list.openShortlist?.id ?? null,
          name: name.trim(),
          source: settings.source ?? '',
          people: chosen,
        }),
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `Could not save (${res.status})`);

      const saved = await res.json();
      list.openShortlist = { id: saved.id, name: saved.name };
      refreshBulk();
      toast(`${saved.name} — ${saved.count} ${saved.count === 1 ? 'person' : 'people'} kept.`);
      settings.onSaved?.();
    } catch (err: any) {
      notify({ title: 'Could not save the shortlist', body: err?.message || 'Nothing was stored.' });
    } finally {
      saveBtn.disabled = false;
    }
  });

  return list;
}
