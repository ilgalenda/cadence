// The personas a search is narrowed to — on the ask bar, where they can be seen.
//
// **This is the third attempt and the first one you can find.** It began as a
// free-text comma box asking someone to retype job titles they had already
// written down in `Persona.md`; it then became a proper list, but inside a
// drawer that was closed by default behind an unlabelled icon — which meant the
// control did not move so much as vanish. A control the person cannot find has
// not been delivered, whatever the tests say.
//
// So it sits on the bar as a statement of its own state — `24 · all considered`,
// or `3 chosen` — and opens in place.
//
// **Choosing none is not "no personas".** `Persona.md` is injected into the
// prompt as authoritative regardless; the selection only *narrows*. Rendering an
// empty selection as `0` would say the search is running with no persona
// guidance at all, which is false, so the count says "all considered" instead.
//
// The list comes from `GET /api/sales/xray/personas`, which parses the team's own
// file through `blocks.persona_focus_options()` — a function written for exactly
// this selector whose docstring says so, and which had never once been called.

/** How the picker reports itself, so callers do not reach into the DOM. */
export interface PersonaPicker {
  /** The narrowing to send. Empty means narrow nothing. */
  chosen(): string[];
  /** Open or close the list. */
  toggle(): void;
}

/**
 * Say what the count means, rather than printing a bare number.
 *
 * Pure, so the wording is testable without a browser — this repo has no jsdom on
 * purpose (see `dom.test.ts`), and the distinction this sentence draws is the
 * whole reason the control is not misleading.
 */
export function personaSummary(total: number, chosen: number, failed: boolean): string {
  if (failed) return 'could not load';
  if (!total) return 'none configured';
  return chosen ? `${total} · ${chosen} chosen` : `${total} · all considered`;
}

/**
 * Why the list is empty, when it is — or nothing, when it is not empty.
 *
 * A failed fetch and an unconfigured file both render as no checkboxes, and they
 * need entirely different actions from the person looking at them. The earlier
 * version caught the error and said nothing at all, which is the same silent
 * degradation this project spent the day removing from the backend.
 */
export function personaStatus(total: number, failed: boolean): string {
  if (failed) {
    return 'The persona list could not be loaded, so nothing is being narrowed. '
      + 'Add one by hand below, or reload once the app is back.';
  }
  if (!total) {
    return 'No personas are configured. Add job titles to Persona.md in the vault, '
      + 'or add one by hand below.';
  }
  return '';
}

/**
 * Build the control.
 *
 * Two mounts, because they cannot be one. The trigger belongs on the ask bar,
 * which is an inline row; the list is a block that has to sit under it. And the
 * whole thing lives inside the search `<form>` — so the "add" input is an input
 * with an Enter handler and **not** a nested `<form>`, which the HTML fragment
 * parser drops on the floor without a word. It did exactly that: the dropped
 * form made a `querySelector` return null, the constructor threw half-built, and
 * the control rendered as a permanent "loading…" that did nothing when clicked.
 */
export function createPersonaPicker(trigger: HTMLElement, mount: HTMLElement): PersonaPicker {
  let configured: string[] = [];
  let failed = false;
  let open = false;
  const added: string[] = [];
  const chosen = new Set<string>();

  trigger.innerHTML = `
    <button class="xr__link" type="button" data-toggle aria-expanded="false">
      Personas · <span data-summary>loading…</span>
    </button>`;

  mount.innerHTML = `
    <div class="xr__personas" data-panel hidden>
      <p class="ds-help" data-status hidden></p>
      <div class="xr__personalist" data-list></div>
      <input class="ds-field xr__personaadd" data-add placeholder="Add a persona, then press Enter"
             aria-label="Add a persona" autocomplete="off" />
    </div>`;

  const find = <T extends HTMLElement>(attr: string) =>
    (trigger.querySelector(`[${attr}]`) ?? mount.querySelector(`[${attr}]`)) as T;
  const toggleBtn = find<HTMLButtonElement>('data-toggle');
  const panel = find('data-panel');
  const summary = find('data-summary');
  const status = find('data-status');
  const list = find('data-list');
  const addField = find<HTMLInputElement>('data-add');

  toggleBtn.addEventListener('click', () => picker.toggle());

  // A persona typed here joins the list already ticked — adding one you did not
  // then want to search for would be a strange thing to have asked for.
  //
  // Enter on the input rather than a form submit: this sits inside the page's
  // search form, and Enter must add a persona, not run a search.
  addField.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    event.stopPropagation();
    const value = addField.value.trim();
    if (!value) return;
    if (!configured.includes(value) && !added.includes(value)) added.push(value);
    chosen.add(value);
    addField.value = '';
    paint();
  });

  (async function load(): Promise<void> {
    try {
      const res = await fetch('/api/sales/xray/personas');
      if (!res.ok) throw new Error(String(res.status));
      const body = await res.json();
      configured = Array.isArray(body) ? body.filter((p) => typeof p === 'string') : [];
    } catch {
      // Named, not swallowed. A 404 here — which is what a stale server returns —
      // used to render as an empty list, indistinguishable from a vault with no
      // personas in it, and cost a session's worth of confusion.
      failed = true;
    } finally {
      paint();
    }
  })();

  function paint(): void {
    const all = [...configured, ...added];
    summary.textContent = personaSummary(all.length, chosen.size, failed);

    const note = personaStatus(all.length, failed);
    status.textContent = note;
    status.hidden = !note;

    list.innerHTML = '';
    all.forEach((persona) => {
      const label = document.createElement('label');
      label.className = 'ds-choice';
      const box = document.createElement('input');
      box.type = 'checkbox';
      box.className = 'ds-check';
      box.checked = chosen.has(persona);
      box.addEventListener('change', () => {
        box.checked ? chosen.add(persona) : chosen.delete(persona);
        paint();
      });
      const text = document.createElement('span');
      text.className = 'ds-choice__text';
      // From a file on disk — set as text, never as markup.
      text.textContent = persona;
      label.append(box, text);
      list.appendChild(label);
    });
  }

  const picker: PersonaPicker = {
    chosen: () => [...chosen],
    toggle() {
      open = !open;
      panel.hidden = !open;
      toggleBtn.setAttribute('aria-expanded', String(open));
    },
  };

  return picker;
}
