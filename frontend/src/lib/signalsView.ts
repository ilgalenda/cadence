// Rendering the watchlist and what has been found on it.
//
// One place, like `briefView.ts` and `intelView.ts`, so the Signals page and
// anything that later shows a signal read the same.
//
// Every text run is set with `textContent`. A finding is model output built from web
// pages — untrusted by construction, and never markup. The one exception is the
// source link's `href`, which is validated as http(s) before it is used: a finding is
// the one thing here that carries a URL from the open web.

export interface Finding {
  kind?: string;
  headline?: string;
  when?: string;
  why_it_matters?: string;
  url?: string;
  found_at?: string;
}

export interface Watched {
  id?: string;
  company?: string;
  added_at?: string;
  last_checked_at?: string;
  due?: boolean;
  recent?: Finding[];
}

const el = <K extends keyof HTMLElementTagNameMap>(tag: K, className?: string) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
};

/**
 * Whether a finding's URL is safe to put in an href.
 *
 * The findings come from a model reading the open web, so the one field that becomes
 * a live link gets checked: http(s) only, which rules out `javascript:` and `data:`.
 */
export function safeUrl(raw: unknown): string {
  const text = String(raw ?? '').trim();
  if (!text) return '';
  try {
    const parsed = new URL(text);
    return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? parsed.href : '';
  } catch {
    return '';
  }
}

/** The host, for showing where a finding came from without the full URL. */
function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return 'source';
  }
}

/** One finding: what happened, why it matters, and where it came from. */
function paintFinding(finding: Finding): HTMLElement {
  const item = el('li', 'intel__point');

  const headline = el('p', 'ds-small intel__what');
  headline.textContent = String(finding.headline ?? '').trim();
  item.append(headline);

  const why = String(finding.why_it_matters ?? '').trim();
  if (why) {
    const reason = el('p', 'ds-small intel__why');
    reason.textContent = why;
    item.append(reason);
  }

  const foot = el('p', 'ds-caption intel__from');
  const when = String(finding.when ?? '').trim();
  if (when) foot.append(document.createTextNode(`${when} · `));

  const url = safeUrl(finding.url);
  if (url) {
    const link = el('a', 'brief__source');
    link.href = url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = hostOf(url);
    foot.append(link);
  } else {
    // Should not happen — the agent drops unsourced findings — but a surface that
    // silently showed one would be claiming something unverifiable.
    foot.append(document.createTextNode('no source'));
  }
  item.append(foot);

  return item;
}

/**
 * Draw the watchlist into `host`, replacing whatever was there.
 *
 * `onUnwatch` and `onAct` are wired per row rather than delegated, so the caller does
 * not have to parse ids back out of the DOM.
 */
export function paintWatchlist(
  host: HTMLElement,
  watched: Watched[],
  handlers: {
    onUnwatch: (id: string) => void;
    onTarget: (company: string) => void;
    onFindPeople: (company: string) => void;
  },
): void {
  host.replaceChildren();

  if (!watched.length) {
    const empty = el('div', 'ds-banner');
    const label = el('span', 'ds-banner__label');
    label.textContent = 'Nothing watched yet';
    const body = el('p');
    body.textContent = 'Add the accounts you care about and Cadence will look for funding, '
      + 'build-outs, timing work and compliance deadlines at each.';
    empty.append(label, body);
    host.append(empty);
    return;
  }

  for (const entry of watched) {
    const card = el('section', 'watch');

    const head = el('div', 'watch__head');
    const name = el('h3', 'ds-title watch__name');
    name.textContent = String(entry.company ?? '').trim() || 'Unnamed';
    head.append(name);

    const state = el('span', 'ds-mono watch__state');
    state.textContent = entry.last_checked_at
      ? `checked ${entry.last_checked_at}${entry.due ? ' · due' : ''}`
      : 'not checked yet';
    head.append(state);

    const actions = el('div', 'watch__actions');

    // A finding needs somewhere to go, or the monitor is a newsletter.
    const target = el('button', 'ds-btn ds-btn--secondary ds-btn--sm');
    target.type = 'button';
    target.textContent = 'Target';
    target.addEventListener('click', () => handlers.onTarget(String(entry.company ?? '')));

    const people = el('button', 'ds-btn ds-btn--secondary ds-btn--sm');
    people.type = 'button';
    people.textContent = 'Find people';
    people.addEventListener('click', () => handlers.onFindPeople(String(entry.company ?? '')));

    const remove = el('button', 'ds-btn ds-btn--ghost ds-btn--sm');
    remove.type = 'button';
    remove.textContent = 'Stop watching';
    remove.addEventListener('click', () => handlers.onUnwatch(String(entry.id ?? '')));

    actions.append(target, people, remove);
    head.append(actions);
    card.append(head);

    const findings = (entry.recent ?? []).filter((f) => String(f?.headline ?? '').trim());
    if (findings.length) {
      const list = el('ul', 'intel__list');
      list.append(...findings.map(paintFinding));
      card.append(list);
    } else {
      const quiet = el('p', 'ds-caption watch__quiet');
      quiet.textContent = entry.last_checked_at
        ? 'Nothing found yet. A quiet account is a real answer.'
        : 'Waiting for its first check.';
      card.append(quiet);
    }

    host.append(card);
  }
}
