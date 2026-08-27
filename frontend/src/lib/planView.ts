// Rendering a campaign plan.
//
// Two surfaces show one: the Campaign selection page and the path runner — the
// same reason `briefView.ts` and `intelView.ts` exist.
//
// Unlike those two, a plan is **not** model output: it is computed by
// `services/campaign_selection.py` from a fixed rule set. It is still set with
// `textContent`, because the rule about untrusted text is easier to keep as a rule
// than as a judgement made per builder.

export interface Plan {
  archetype?: string;
  channels?: string[];
  touch_count?: number;
  cadence?: string;
  touch_structure?: string[];
  requires_identification?: boolean;
  rationale?: string;
  inputs?: Record<string, any>;
  /** Inputs that were defaulted rather than read from the lead. */
  assumed?: string[];
  error?: string | null;
}

/** What the rules call the two archetypes, in words a person would use. */
const ARCHETYPE_NAMES: Record<string, string> = {
  warm_inbound_reengagement: 'Warm inbound re-engagement',
  abm_account_push: 'ABM account push',
};

export const archetypeName = (archetype: string | undefined): string =>
  ARCHETYPE_NAMES[archetype ?? ''] ?? 'Campaign';

const el = <K extends keyof HTMLElementTagNameMap>(tag: K, className?: string) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
};

/** Whether there is a plan here at all. */
export function hasContent(plan: Plan | null | undefined): boolean {
  return Boolean(plan && (plan.touch_structure ?? []).length);
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

/** A step name as a person reads it: `week1_connect` → `week1 connect`. */
const readable = (step: string) => String(step).replace(/_/g, ' ');

/**
 * Draw the plan into `host`, replacing whatever was there.
 *
 * The sequence is numbered because its order is the plan — the rules pick a
 * *prefix* of the inbound sequence by warmth, so which steps are missing is as
 * meaningful as which are present.
 */
export function paintPlan(host: HTMLElement, plan: Plan): void {
  host.replaceChildren();

  if (!hasContent(plan)) {
    const failed = el('div', 'ds-banner ds-banner--fault');
    const label = el('span', 'ds-banner__label');
    label.textContent = 'No plan';
    const body = el('p');
    body.textContent = plan?.error
      ? `The plan could not be computed (${plan.error}).`
      : 'No plan came back.';
    failed.append(label, body);
    host.append(failed);
    return;
  }

  // Stated first, because it changes what the person should do next rather than
  // just describing the plan: the campaign cannot start until someone is found.
  if (plan.requires_identification) {
    const identify = el('div', 'ds-banner ds-banner--drift');
    const label = el('span', 'ds-banner__label');
    label.textContent = 'Nobody named yet';
    const body = el('p');
    body.textContent = 'This campaign opens by finding the right people — run X-ray before writing anything.';
    identify.append(label, body);
    host.append(identify);
  }

  // What the plan assumed, above it: a plan computed from defaults looks exactly
  // like one computed from a real verdict, and the difference matters.
  if ((plan.assumed ?? []).length) {
    const assumed = el('div', 'ds-banner');
    const label = el('span', 'ds-banner__label');
    label.textContent = 'Assumed';
    const body = el('p');
    body.textContent = `${plan.assumed!.map(readable).join(', ')} — not read from a scored lead. `
      + 'Score the lead first and the plan is computed from what it found.';
    assumed.append(label, body);
    host.append(assumed);
  }

  host.append(section(archetypeName(plan.archetype)));
  host.append(labelled('touches', String(plan.touch_count ?? (plan.touch_structure ?? []).length)));
  if (plan.cadence) host.append(labelled('cadence', plan.cadence));
  if (plan.rationale) host.append(prose(plan.rationale));

  host.append(section('The sequence'));
  const list = el('ol', 'brief__list');
  for (const step of plan.touch_structure ?? []) {
    const li = el('li', 'ds-small');
    li.textContent = readable(step);
    list.append(li);
  }
  host.append(list);
}

/**
 * Draw the channel mix as chips the person can toggle, and report changes.
 *
 * The mix is the one part of the plan a person edits: the archetype and the touch
 * structure come from the playbook, but which channels *this* person will actually
 * work is theirs to say. `onChange` receives the mix after every toggle.
 */
export function paintChannels(
  host: HTMLElement,
  all: string[],
  chosen: string[],
  onChange: (chosen: string[]) => void,
): void {
  host.replaceChildren();
  const selected = new Set(chosen);

  /**
   * Selected chips take `.ds-tag--accent`; unselected keep the plain tag.
   *
   * Not opacity: dimming `--ink-secondary` to 45% lands around 2.5:1, under the
   * system's 4.5:1 floor. The accent variant is what the design system provides
   * for exactly this, and it is what Composer's channel chips already use.
   */
  const paint = (chip: HTMLElement, on: boolean): void => {
    chip.className = on ? 'ds-tag ds-tag--accent' : 'ds-tag';
    chip.setAttribute('aria-pressed', String(on));
  };

  for (const channel of all) {
    const chip = el('button', 'ds-tag');
    chip.type = 'button';
    chip.textContent = channel;
    paint(chip, selected.has(channel));

    chip.addEventListener('click', () => {
      if (selected.has(channel)) {
        // Never leave nothing selected — composing no channels is not a choice.
        if (selected.size === 1) return;
        selected.delete(channel);
      } else {
        selected.add(channel);
      }
      paint(chip, selected.has(channel));
      onChange(all.filter((c) => selected.has(c)));
    });

    host.append(chip);
  }
}
