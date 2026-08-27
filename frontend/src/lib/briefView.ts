// Rendering a research brief.
//
// Two surfaces show one: the Research agent's own page and the path runner. This
// exists so there is one definition of what a brief looks like — the same reason
// `peopleTable.ts` was extracted rather than forked for the runner's X-ray step.
//
// Every text run is set with `textContent`. A brief is model output built from web
// pages, so it is untrusted by construction and never becomes markup.

export interface Brief {
  subject?: { company?: string; person?: string };
  company?: Record<string, string>;
  timing?: { why_now?: string; signals?: string[] };
  angle?: { fit?: string; why?: string; products?: string[] };
  person?: Record<string, string>;
  risks?: string[];
  sources?: { claim?: string; url?: string }[];
  error?: string | null;
}

const el = <K extends keyof HTMLElementTagNameMap>(tag: K, className?: string) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
};

/** Whether there is anything in here worth showing. */
export function hasContent(brief: Brief | null | undefined): boolean {
  if (!brief) return false;
  return Boolean(
    Object.keys(brief.company ?? {}).length
    || Object.keys(brief.timing ?? {}).length
    || Object.keys(brief.angle ?? {}).length
    || Object.keys(brief.person ?? {}).length,
  );
}

function section(title: string): HTMLElement {
  const head = el('h3', 'ds-eyebrow brief__title');
  head.textContent = title;
  return head;
}

function prose(text: string): HTMLElement {
  const para = el('p', 'ds-small brief__prose');
  para.textContent = text;
  return para;
}

function labelled(label: string, value: string): HTMLElement {
  const row = el('div', 'brief__row');
  const key = el('span', 'ds-mono brief__key');
  key.textContent = label;
  const val = el('span', 'ds-small brief__value');
  val.textContent = value;
  row.append(key, val);
  return row;
}

function bullets(items: string[]): HTMLElement {
  const list = el('ul', 'brief__list');
  for (const item of items) {
    if (!item) continue;
    const li = el('li', 'ds-small');
    li.textContent = item;
    list.append(li);
  }
  return list;
}

/** Turn a snake_case key into a readable label without inventing a dictionary. */
const humanise = (key: string) => key.replace(/_/g, ' ');

/**
 * Draw the brief into `host`, replacing whatever was there.
 *
 * Empty sections are omitted rather than shown blank: the agent leaves a field
 * empty when it found nothing, and a heading over nothing reads as a failure.
 */
export function paintBrief(host: HTMLElement, brief: Brief): void {
  host.replaceChildren();

  if (brief.error && !hasContent(brief)) {
    const failed = el('div', 'ds-banner ds-banner--fault');
    const label = el('span', 'ds-banner__label');
    label.textContent = 'Nothing found';
    const body = el('p');
    body.textContent = `The research turn did not return a usable brief (${brief.error}).`;
    failed.append(label, body);
    host.append(failed);
    return;
  }

  // A truncated turn still produced most of a brief; say so above it rather than
  // discarding what the searches already paid for.
  if (brief.error) {
    const partial = el('div', 'ds-banner ds-banner--drift');
    const label = el('span', 'ds-banner__label');
    label.textContent = 'Incomplete';
    const body = el('p');
    body.textContent = `The research ended early (${brief.error}), so this brief may be missing something.`;
    partial.append(label, body);
    host.append(partial);
  }

  const company = brief.company ?? {};
  if (Object.keys(company).length) {
    host.append(section('The company'));
    for (const [key, value] of Object.entries(company)) {
      if (value) host.append(labelled(humanise(key), value));
    }
  }

  const timing = brief.timing ?? {};
  if (timing.why_now || (timing.signals ?? []).length) {
    host.append(section('Why now'));
    if (timing.why_now) host.append(prose(timing.why_now));
    if ((timing.signals ?? []).length) host.append(bullets(timing.signals!));
  }

  const angle = brief.angle ?? {};
  if (angle.fit || angle.why) {
    host.append(section('Our angle'));
    if (angle.fit) host.append(labelled('fit', angle.fit));
    if (angle.why) host.append(prose(angle.why));
    if ((angle.products ?? []).length) {
      const tags = el('div', 'brief__tags');
      for (const product of angle.products!) {
        const tag = el('span', 'ds-tag');
        tag.textContent = product;
        tags.append(tag);
      }
      host.append(tags);
    }
  }

  const person = brief.person ?? {};
  if (Object.keys(person).length) {
    host.append(section(person.name || 'The person'));
    for (const [key, value] of Object.entries(person)) {
      if (value && key !== 'name') host.append(labelled(humanise(key), value));
    }
  }

  if ((brief.risks ?? []).length) {
    host.append(section('Worth knowing'));
    host.append(bullets(brief.risks!));
  }

  // Sources last and always shown when present: a claim that cannot be checked
  // should not be repeated on a call.
  const sources = (brief.sources ?? []).filter((s) => s?.url);
  if (sources.length) {
    host.append(section(`Sources · ${sources.length}`));
    const list = el('ul', 'brief__list');
    for (const source of sources) {
      const li = el('li', 'ds-small');
      const link = el('a', 'brief__source');
      link.href = source.url!;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = source.claim || source.url!;
      li.append(link);
      list.append(li);
    }
    host.append(list);
  }
}

