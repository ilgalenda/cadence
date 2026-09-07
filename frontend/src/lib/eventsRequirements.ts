// What a person asks for on the form: material, and travel.
//
// **The options are served, not written here.** `GET /api/events` returns the
// material list and the travel modes from `agents/events/requirements.py`, which
// is the one place either vocabulary exists. A copy in this file would disagree
// with the backend the first time somebody added to one of them, and the
// disagreement would show up as a request nobody can fulfil.
//
// **Two disclosures, one pattern.** A tick opens a block; unticking closes it and
// the answer inside stops being sent — matching what the store does with it, so
// the page and the record never differ about what somebody asked for.
//
// **A leg is a row, not a sentence.** Operations books a flight differently from
// a car, so the shape asks for the mode, the route and the nights separately
// rather than leaving somebody to parse a note. Every text run is set with
// `textContent`, as everywhere else on this page.

export interface MaterialOption {
  key: string;
  label: string;
  hint?: string;
}

export interface TravelMode {
  key: string;
  label: string;
  /** Whether the leg runs between two places. A car hire does not. */
  routed?: boolean;
}

export interface Leg {
  mode: string;
  from: string;
  to: string;
  nights: number;
}

/** The key whose choice opens the free-text box. Mirrors `requirements.OTHER`. */
export const OTHER = 'other';

/**
 * Whether a mode runs between two places.
 *
 * A car hire has no route, and a mode the backend added after this page loaded
 * is assumed to have one — a spare pair of fields is a smaller failure than a
 * journey somebody cannot say the destination of.
 */
export function isRouted(key: string, modes: TravelMode[]): boolean {
  return modes.find((mode) => mode.key === key)?.routed !== false;
}

/**
 * One leg, normalised.
 *
 * Whitespace off, nights as a number that is never negative and never `NaN` —
 * an empty box and a box somebody typed a word into both mean "no nights", and
 * neither should reach the request as something the backend has to refuse.
 */
export function toLeg(raw: {
  mode: string; from: string; to: string; nights: string;
}): Leg {
  const nights = Number(raw.nights.trim());
  return {
    mode: raw.mode,
    from: raw.from.trim(),
    to: raw.to.trim(),
    nights: Number.isFinite(nights) ? Math.max(0, Math.trunc(nights)) : 0,
  };
}

const el = <K extends keyof HTMLElementTagNameMap>(tag: K, className?: string) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
};

/**
 * Draw the material choices.
 *
 * Rendered once, from what the API returned. `onOther` fires whenever the
 * *Something else* box changes, so the page can reveal the free-text field
 * without this module knowing where that field lives.
 */
export function paintMaterial(
  host: HTMLElement,
  options: MaterialOption[],
  onOther: (on: boolean) => void,
): void {
  host.replaceChildren();

  for (const option of options) {
    const label = el('label', 'ds-choice');
    const box = el('input', 'ds-check') as HTMLInputElement;
    box.type = 'checkbox';
    box.value = option.key;
    box.dataset.material = option.key;

    const text = el('span', 'ds-choice__text');
    text.append(option.label);
    if (option.hint) {
      const hint = el('span', 'ds-choice__hint');
      hint.textContent = option.hint;
      text.append(hint);
    }

    if (option.key === OTHER) {
      box.addEventListener('change', () => onOther(box.checked));
    }

    label.append(box, text);
    host.append(label);
  }
}

/** Every material key currently ticked, in the order they were drawn. */
export function readMaterial(host: HTMLElement): string[] {
  return [...host.querySelectorAll<HTMLInputElement>('input[data-material]')]
    .filter((box) => box.checked)
    .map((box) => box.value);
}

/** Whether *Something else* is one of them. */
export function wantsOther(host: HTMLElement): boolean {
  return readMaterial(host).includes(OTHER);
}

/**
 * One travel arrangement.
 *
 * `onRemove` is passed rather than assumed: the first leg is removable like any
 * other, because somebody who ticked travel by mistake should be able to empty
 * the block and untick it rather than being left with a row they cannot clear.
 */
export function legRow(modes: TravelMode[], onRemove: () => void): HTMLElement {
  const row = el('div', 'ev__leg');
  row.dataset.leg = '';

  const modeCell = el('div', 'form__cell');
  const modeLabel = el('label', 'ds-label');
  modeLabel.textContent = 'How';
  const select = el('select', 'ds-select') as HTMLSelectElement;
  select.dataset.legMode = '';
  for (const mode of modes) {
    const option = el('option') as HTMLOptionElement;
    option.value = mode.key;
    option.textContent = mode.label;
    select.append(option);
  }
  modeCell.append(modeLabel, select);

  const fromCell = el('div', 'form__cell');
  const fromLabel = el('label', 'ds-label');
  fromLabel.textContent = 'From';
  const from = el('input', 'ds-field') as HTMLInputElement;
  from.dataset.legFrom = '';
  from.placeholder = 'London';
  fromCell.append(fromLabel, from);

  const toCell = el('div', 'form__cell');
  const toLabel = el('label', 'ds-label');
  toLabel.textContent = 'To';
  const to = el('input', 'ds-field') as HTMLInputElement;
  to.dataset.legTo = '';
  to.placeholder = 'Amsterdam';
  toCell.append(toLabel, to);

  const nightsCell = el('div', 'form__cell form__cell--tight');
  const nightsLabel = el('label', 'ds-label');
  nightsLabel.textContent = 'Nights';
  const nights = el('input', 'ds-field') as HTMLInputElement;
  nights.dataset.legNights = '';
  nights.type = 'number';
  nights.min = '0';
  nights.step = '1';
  nights.placeholder = '0';
  const nightsHint = el('p', 'ds-help');
  nightsHint.textContent = '0 for a day trip.';
  nightsCell.append(nightsLabel, nights, nightsHint);

  const remove = el('button', 'ds-btn ds-btn--ghost ds-btn--sm ev__leg-drop') as HTMLButtonElement;
  remove.type = 'button';
  remove.textContent = 'Remove';
  remove.addEventListener('click', onRemove);

  // A route means nothing for a car hire, so the two fields follow the mode
  // rather than sitting there inviting an answer nobody wants.
  const syncRoute = () => {
    const routed = isRouted(select.value, modes);
    fromCell.hidden = !routed;
    toCell.hidden = !routed;
    if (!routed) {
      from.value = '';
      to.value = '';
    }
  };
  select.addEventListener('change', syncRoute);
  syncRoute();

  row.append(modeCell, fromCell, toCell, nightsCell, remove);
  return row;
}

/** Every leg on the page, in the order they were added. */
export function readLegs(host: HTMLElement): Leg[] {
  return [...host.querySelectorAll<HTMLElement>('[data-leg]')].map((row) => {
    const field = (name: string) =>
      row.querySelector<HTMLInputElement>(`[data-leg-${name}]`)?.value ?? '';
    return toLeg({
      mode: row.querySelector<HTMLSelectElement>('[data-leg-mode]')?.value ?? '',
      from: field('from'),
      to: field('to'),
      nights: field('nights'),
    });
  });
}
