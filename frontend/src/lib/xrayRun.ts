// How the search is framed, and how it reports itself.
//
// **It used to be a readout, and that was the problem.** Every version of this
// restated what was already on screen: the elapsed time (also inline under the
// ask), the company (also in the field above it), the mode (also on the
// selector), and a provenance chip whose value was always the same single
// string. A panel that duplicates the page cannot be styled into being useful,
// because it has nothing of its own to say.
//
// So it holds the one thing nothing else could reach: **the grounding** — the
// vertical and timing pain the backend derived from a bare company name. It can
// be wrong, and a wrong vertical sends the whole search after the wrong
// technical function. Corrected here, it is used as given and the model is not
// asked again.
//
// **It also used to be a `.ds-drawer`, and that was the bigger problem.** The
// platform has no other drawer; this one was closed by default behind an
// unlabelled icon, and hidden outright below 72rem — a width a laptop hits with
// the rail open — so the header toggle silently did nothing. The argument against
// that arrangement is already written in `lib/personaPicker.ts`, about the
// personas that used to live in this same drawer: *"a control the person cannot
// find has not been delivered, whatever the tests say."* Grounding is the
// highest-value control on the page, so it now sits on the ask as a statement of
// its own state and opens in place, exactly as the personas beside it do.
//
// The run's readout — `web discovery · 11 found · 20.4s` — is handed back through
// `onReadout` rather than painted here. It belongs in the result section head's
// mono slot, which is where this platform's grammar puts the machine talking.
//
// Screen design: `design-system/preview/screen-xray.html`.
//
// Pure rendering and local state: it never fetches a search. The page owns that
// and passes `onRerun`.

import { startElapsed, type StopElapsed } from './elapsed';
import type { Person } from './paths';

/** What the control can change, handed back when Re-run is pressed. */
export interface RunSettings {
  industry: string;
  productFit: string;
}

export interface RunControlOptions {
  /** Run the search again with what the control now holds. */
  onRerun: (settings: RunSettings) => void;
  /** Where the run states itself: the result section head's mono readout. */
  onReadout: (text: string) => void;
}

export interface RunResult {
  people: Person[];
  seconds: number;
  /**
   * What the backend derived, so a correction starts from what it decided.
   *
   * Provider warnings are deliberately not here. They are rendered on the page's
   * `.ds-banner--drift`, and restating them in the readout is exactly the
   * duplication this module was rebuilt to stop carrying.
   */
  grounding?: { industry?: string; product_fit?: string };
}

export interface RunControls {
  /** A search has begun. */
  start(subject: string): void;
  /** The search returned. */
  settle(result: RunResult): void;
  /** The search failed. */
  fail(message: string): void;
  /** What the control currently holds, for a search started from the ask. */
  settings(): RunSettings;
  /** Grounding can only be tuned for a company search; a lead brings its own. */
  setTunable(tunable: boolean): void;
  /** Open or close the panel. */
  toggle(): void;
}

/** Providers stamp a `source` on every row; this is how each one reads. */
const SOURCE_NAMES: Record<string, string> = {
  web_search: 'web discovery',
  zoominfo: 'ZoomInfo',
};

/**
 * Say how the search is grounded, in the words the search will actually use.
 *
 * Pure, so the wording is testable without a browser — this repo has no jsdom on
 * purpose (see `dom.test.ts`). Four cases, all previously rendered as one absent
 * chip, and the distinction between the last two is the one that matters:
 *
 *   * a lead carries its own grounding from the verdict; there is nothing here
 *     to correct, so the control says where it came from instead;
 *   * a derived or hand-typed grounding reads back as the sentence it is;
 *   * **before any search**, nothing has been derived *yet* — which is not a
 *     finding, so it describes what will happen;
 *   * **after a search**, empty means the model did not recognise the company
 *     and the whole discovery ran ungrounded. That is a quality warning, and
 *     wording it the same as "not yet" would bury it.
 */
export function groundingSummary(
  industry: string,
  productFit: string,
  tunable: boolean,
  hasRun: boolean,
): string {
  if (!tunable) return 'from the scored lead';
  const parts = [industry, productFit].map((p) => p.trim()).filter(Boolean);
  if (parts.length) return parts.join(' · ');
  return hasRun ? 'nothing derived' : 'derived from the name';
}

/**
 * Build the control.
 *
 * Two mounts, for the reason `personaPicker` gives: the trigger belongs on the
 * ask's minor row, which is an inline row, and the panel is a block that has to
 * sit under it.
 */
export function createRunControls(
  trigger: HTMLElement,
  mount: HTMLElement,
  options: RunControlOptions,
): RunControls {
  let open = false;
  let tunable = true;
  let hasRun = false;
  let stopElapsed: StopElapsed | null = null;

  trigger.innerHTML = `
    <button class="xr__link" type="button" data-toggle aria-expanded="false">
      Read as · <span data-summary></span>
    </button>`;

  mount.innerHTML = `
    <div class="xr__panel" data-panel hidden>
      <div class="xr__tune">
        <label class="ds-label" for="tune-industry">Vertical</label>
        <input class="ds-field" id="tune-industry" type="text" data-industry autocomplete="off" />
        <label class="ds-label" for="tune-fit">Timing pain</label>
        <input class="ds-field" id="tune-fit" type="text" data-fit autocomplete="off" />
      </div>
      <p class="ds-help">Derived from the name. Correct it and the model is not asked again.</p>
      <button class="ds-btn ds-btn--secondary" type="button" data-rerun>Re-run with these</button>
    </div>`;

  const find = <T extends HTMLElement>(attr: string) =>
    (trigger.querySelector(`[${attr}]`) ?? mount.querySelector(`[${attr}]`)) as T;
  const toggleBtn = find<HTMLButtonElement>('data-toggle');
  const panel = find('data-panel');
  const summary = find('data-summary');
  const industryField = find<HTMLInputElement>('data-industry');
  const fitField = find<HTMLInputElement>('data-fit');

  toggleBtn.addEventListener('click', () => controls.toggle());
  mount.querySelector('[data-rerun]')!.addEventListener('click', () => options.onRerun(controls.settings()));

  // Typing in either field changes what the trigger claims, so the summary is
  // never a stale description of the search that is about to run.
  [industryField, fitField].forEach((field) => {
    field.addEventListener('input', paintSummary);
    // Enter inside the page's search form would submit it and run an untuned
    // search; here it means "re-run with what I have just typed".
    field.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter') return;
      event.preventDefault();
      event.stopPropagation();
      options.onRerun(controls.settings());
    });
  });

  function paintSummary(): void {
    summary.textContent = groundingSummary(industryField.value, fitField.value, tunable, hasRun);
  }

  const controls: RunControls = {
    start(subject) {
      stopElapsed?.();
      // The first tick names the subject; the rest count. See `lib/elapsed`.
      let first = true;
      stopElapsed = startElapsed((seconds) => {
        options.onReadout(first ? `searching · ${subject}` : `searching · ${seconds}s`);
        first = false;
      });
    },

    settle(result) {
      stopElapsed?.();

      // Start a correction from what the backend actually decided, but never
      // overwrite an edit already made — a re-run must not undo the fix that
      // prompted it.
      hasRun = true;
      if (result.grounding) {
        if (!industryField.value) industryField.value = result.grounding.industry ?? '';
        if (!fitField.value) fitField.value = result.grounding.product_fit ?? '';
      }
      paintSummary();

      const sources = [...new Set(result.people.map((p) => String(p.source || '')).filter(Boolean))]
        .map((s) => SOURCE_NAMES[s] ?? s);
      const parts = [
        ...(sources.length ? [sources.join(' · ')] : []),
        `${result.people.length} found`,
        `${result.seconds.toFixed(1)}s`,
      ];
      options.onReadout(parts.join(' · '));
    },

    fail(message) {
      stopElapsed?.();
      options.onReadout(message);
    },

    settings: () => ({
      industry: industryField.value.trim(),
      productFit: fitField.value.trim(),
    }),

    setTunable(next) {
      // A scored lead carries its own vertical and product fit from the verdict.
      // Offering to edit a grounding the search will not use would be a control
      // that does nothing — so the trigger says where the grounding came from
      // and stops being a way in.
      tunable = next;
      toggleBtn.disabled = !next;
      if (!next && open) controls.toggle();
      paintSummary();
    },

    toggle() {
      open = !open;
      panel.hidden = !open;
      toggleBtn.setAttribute('aria-expanded', String(open));
    },
  };

  paintSummary();
  return controls;
}
