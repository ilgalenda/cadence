// Rendering a Campaign Intelligence outline.
//
// Two surfaces show one: the agent's own page and the path runner — the same
// reason `briefView.ts` exists rather than each surface drawing its own.
//
// Every text run is set with `textContent`. An outline is model output built from
// call transcripts, so it is untrusted by construction and never becomes markup.

export interface Objection {
  objection?: string;
  how_it_lands?: string;
  from?: string;
}

export interface PainPoint {
  pain?: string;
  why_it_bites?: string;
  from?: string;
}

export interface Intel {
  vertical?: string;
  objections?: Objection[];
  pain_points?: PainPoint[];
  angle?: { open_with?: string; avoid?: string; why?: string };
  proof_points?: string[];
  recall?: { id?: string; title?: string }[];
  recall_quality?: string;
  considered?: number;
  indexed?: number;
  error?: string | null;
}

const el = <K extends keyof HTMLElementTagNameMap>(tag: K, className?: string) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
};

/** Whether there is anything in here worth showing. */
export function hasContent(intel: Intel | null | undefined): boolean {
  if (!intel) return false;
  return Boolean(
    (intel.objections ?? []).length
    || (intel.pain_points ?? []).length
    || Object.keys(intel.angle ?? {}).length
    || (intel.proof_points ?? []).length,
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

/**
 * One recalled point: what it is, why it bites, and the call it came from.
 *
 * The attribution is shown rather than kept in the payload. A salesperson about to
 * repeat this on a call needs to know it came from a real conversation — the same
 * argument that puts sources at the bottom of a research brief.
 */
function point(head: string, because: string, from: string): HTMLElement {
  const item = el('li', 'intel__point');

  const what = el('p', 'ds-small intel__what');
  what.textContent = head;
  item.append(what);

  if (because) {
    const why = el('p', 'ds-small intel__why');
    why.textContent = because;
    item.append(why);
  }
  if (from) {
    const source = el('p', 'ds-caption intel__from');
    source.textContent = `from: ${from}`;
    item.append(source);
  }
  return item;
}

function points(items: HTMLElement[]): HTMLElement {
  const list = el('ul', 'intel__list');
  list.append(...items);
  return list;
}

/**
 * Draw the outline into `host`, replacing whatever was there.
 *
 * Empty sections are omitted rather than shown blank, and a market with no history
 * says so plainly — "no recall" is a real answer about the market, not a fault in
 * the run, and dressing it up as one would send someone looking for a bug.
 */
export function paintIntel(host: HTMLElement, intel: Intel): void {
  host.replaceChildren();

  const market = intel.vertical || 'this market';

  if (intel.error === 'no_recall') {
    const empty = el('div', 'ds-banner');
    const label = el('span', 'ds-banner__label');
    label.textContent = 'Nothing recalled';
    const body = el('p');
    body.textContent = `None of the ${intel.considered ?? 0} analysed calls speak to ${market}. `
      + 'Analyse a call in it and this fills in.';
    empty.append(label, body);
    host.append(empty);
    return;
  }

  if (intel.error) {
    const failed = el('div', 'ds-banner ds-banner--fault');
    const label = el('span', 'ds-banner__label');
    label.textContent = 'Could not recall';
    const body = el('p');
    body.textContent = `The outline did not complete (${intel.error}).`;
    failed.append(label, body);
    host.append(failed);
    if (!hasContent(intel)) return;
  }

  // Thin recall is flagged above the outline, so it is not read as the market's
  // settled position when it rests on two calls.
  if (intel.recall_quality === 'thin') {
    const thin = el('div', 'ds-banner ds-banner--drift');
    const label = el('span', 'ds-banner__label');
    label.textContent = 'Thin recall';
    const body = el('p');
    body.textContent = 'There was little in the calls about this market. Treat this as a '
      + 'starting point rather than what the market thinks.';
    thin.append(label, body);
    host.append(thin);
  }

  const pains = (intel.pain_points ?? [])
    .filter((p) => (p?.pain ?? '').trim())
    .map((p) => point(p.pain!.trim(), (p.why_it_bites ?? '').trim(), (p.from ?? '').trim()));
  if (pains.length) {
    host.append(section('What hurts them'));
    host.append(points(pains));
  }

  const objections = (intel.objections ?? [])
    .filter((o) => (o?.objection ?? '').trim())
    .map((o) => point(o.objection!.trim(), (o.how_it_lands ?? '').trim(), (o.from ?? '').trim()));
  if (objections.length) {
    host.append(section('Objections you will meet'));
    host.append(points(objections));
  }

  const angle = intel.angle ?? {};
  if (angle.open_with || angle.avoid || angle.why) {
    host.append(section('The angle'));
    if (angle.open_with) host.append(labelled('open with', angle.open_with));
    if (angle.avoid) host.append(labelled('avoid', angle.avoid));
    if (angle.why) host.append(prose(angle.why));
  }

  const proof = (intel.proof_points ?? []).filter(Boolean);
  if (proof.length) {
    host.append(section('Has landed before'));
    const tags = el('div', 'brief__tags');
    for (const item of proof) {
      const tag = el('span', 'ds-tag');
      tag.textContent = String(item);
      tags.append(tag);
    }
    host.append(tags);
  }

  // The trail last, and always when present: every claim above should be
  // traceable to a conversation somebody actually had.
  const recall = (intel.recall ?? []).filter((r) => (r?.title ?? '').trim());
  if (recall.length) {
    host.append(section(`Recalled from · ${recall.length}`));
    const list = el('ul', 'brief__list');
    for (const row of recall) {
      const li = el('li', 'ds-small');
      li.textContent = row.title!.trim();
      list.append(li);
    }
    host.append(list);

    if ((intel.indexed ?? 0) > (intel.considered ?? 0)) {
      host.append(prose(
        `Read the most recent ${intel.considered} of ${intel.indexed} analysed calls.`,
      ));
    }
  }
}
