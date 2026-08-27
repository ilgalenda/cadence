// Overlays — dialogs, menus and toasts, owned once.
//
// These were proved in the Owl workspace and lived inside its page script, so no
// other surface could reach them and the rest of the platform fell back on
// `confirm()` and `alert()` — browser chrome in the middle of a designed system,
// unstyled, unbranded and unable to say anything specific about what is at stake.
//
// Everything here is built from the design system's own components
// (`.ds-scrim`, `.ds-dialog`, `.ds-menu`, `.ds-toast`) and shares its behaviour:
// Escape always closes, focus moves into the dialog, a menu can never be left
// orphaned, and a destructive action is always named rather than generic.

const LAYER_ID = 'ds-overlay-layer';

/** The overlay layer, created on first use so no page has to remember to add it. */
function layer(): HTMLElement {
  let el = document.getElementById(LAYER_ID);
  if (!el) {
    el = document.createElement('div');
    el.id = LAYER_ID;
    document.body.appendChild(el);
  }
  return el;
}

function escapeHtml(text: string): string {
  const holder = document.createElement('div');
  holder.textContent = text;
  return holder.innerHTML;
}

// ── Toast ───────────────────────────────────────────────────────────────────

const TOAST_MS = 3200;

/** A brief confirmation. Never used for errors that need a decision. */
export function toast(message: string): void {
  const el = document.createElement('div');
  el.className = 'ds-toast';
  el.setAttribute('role', 'status');
  el.style.cssText =
    'position:fixed;bottom:var(--space-6);left:50%;transform:translateX(-50%);z-index:var(--z-toast);';
  el.textContent = message;
  layer().appendChild(el);
  setTimeout(() => el.remove(), TOAST_MS);
}

// ── Dialog ──────────────────────────────────────────────────────────────────

export interface DialogOptions {
  title: string;
  /** Body markup. Any `[name]` field is collected into the result. */
  body?: string;
  confirm?: string;
  cancel?: string;
  /** Styles the confirm button as destructive. Use whenever data is lost. */
  danger?: boolean;
}

/**
 * Open a modal built from the design system's dialog.
 *
 * Resolves with the submitted field values, or `null` when dismissed — so a
 * caller can always distinguish "confirmed with nothing to collect" (`{}`) from
 * "cancelled" (`null`).
 */
export function dialog(options: DialogOptions): Promise<Record<string, string> | null> {
  const { title, body = '', confirm = 'Confirm', cancel = 'Cancel', danger = false } = options;

  return new Promise((resolve) => {
    const previouslyFocused = document.activeElement as HTMLElement | null;

    const scrim = document.createElement('div');
    scrim.className = 'ds-scrim';

    const form = document.createElement('form');
    const box = document.createElement('div');
    box.className = 'ds-dialog';
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-modal', 'true');
    box.innerHTML = `
      <div class="ds-dialog__head"><p class="ds-title">${escapeHtml(title)}</p></div>
      ${body ? `<div class="ds-dialog__body">${body}</div>` : ''}
      <div class="ds-dialog__foot">
        <button type="button" class="ds-btn ds-btn--ghost" data-act="cancel">${escapeHtml(cancel)}</button>
        <button type="submit" class="ds-btn ${danger ? 'ds-btn--danger' : 'ds-btn--primary'}">${escapeHtml(confirm)}</button>
      </div>`;
    form.appendChild(box);

    const close = (result: Record<string, string> | null) => {
      scrim.remove();
      form.remove();
      document.removeEventListener('keydown', onKey, true);
      previouslyFocused?.focus?.();
      resolve(result);
    };

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.stopPropagation(); close(null); }
    };

    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const values: Record<string, string> = {};
      box.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>('[name]')
        .forEach((field) => { values[field.name] = field.value.trim(); });
      close(values);
    });

    box.querySelector('[data-act="cancel"]')!.addEventListener('click', () => close(null));
    scrim.addEventListener('click', () => close(null));
    document.addEventListener('keydown', onKey, true);

    layer().append(scrim, form);
    box.querySelector<HTMLElement>('input, textarea, select, [data-act="cancel"]')?.focus();
  });
}

/**
 * Confirm a consequential action. Replaces `confirm()`.
 *
 * `title` should name the thing — "Delete “Northgate”?" not "Are you sure?" — and
 * `body` should say what actually happens, especially whether it can be undone.
 */
export function confirmAction(options: {
  title: string;
  body?: string;
  confirm?: string;
  danger?: boolean;
}): Promise<boolean> {
  return dialog({
    title: options.title,
    body: options.body ? `<p class="ds-small">${escapeHtml(options.body)}</p>` : '',
    confirm: options.confirm ?? 'Confirm',
    danger: options.danger ?? true,
  }).then((result) => result !== null);
}

/** Ask for one value. Replaces `prompt()`. Resolves null when dismissed. */
export function promptText(options: {
  title: string;
  label: string;
  value?: string;
  placeholder?: string;
  confirm?: string;
  multiline?: boolean;
}): Promise<string | null> {
  const { title, label, value = '', placeholder = '', confirm = 'Save', multiline = false } = options;
  const field = multiline
    ? `<textarea class="ds-field ds-textarea" id="ds-prompt" name="value" placeholder="${escapeHtml(placeholder)}">${escapeHtml(value)}</textarea>`
    : `<input class="ds-field" id="ds-prompt" name="value" value="${escapeHtml(value)}" placeholder="${escapeHtml(placeholder)}" />`;

  return dialog({
    title,
    body: `<label class="ds-label" for="ds-prompt">${escapeHtml(label)}</label>${field}`,
    confirm,
  }).then((result) => (result === null ? null : result.value ?? ''));
}

/** State something the user must acknowledge. Replaces `alert()`. */
export function notify(options: { title: string; body?: string }): Promise<void> {
  return dialog({
    title: options.title,
    body: options.body ? `<p class="ds-small">${escapeHtml(options.body)}</p>` : '',
    confirm: 'Close',
    cancel: '',
  }).then(() => undefined);
}

// ── Menu ────────────────────────────────────────────────────────────────────

export type MenuItem = { label: string; danger?: boolean; run: () => void } | 'separator';

/**
 * A context menu anchored to a trigger.
 *
 * Closes on any outside click, on Escape, and after a choice — so it can never
 * be left orphaned. Only one menu exists at a time.
 */
export function menu(anchor: HTMLElement, items: MenuItem[]): void {
  layer().querySelector('[data-ds-menu]')?.remove();

  const wrap = document.createElement('div');
  wrap.dataset.dsMenu = '';
  const box = document.createElement('div');
  box.className = 'ds-menu';
  box.setAttribute('role', 'menu');

  const dismiss = () => {
    wrap.remove();
    document.removeEventListener('pointerdown', onOutside, true);
    document.removeEventListener('keydown', onKey, true);
  };
  const onOutside = (e: Event) => { if (!wrap.contains(e.target as Node)) dismiss(); };
  const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') dismiss(); };

  for (const item of items) {
    if (item === 'separator') {
      const sep = document.createElement('div');
      sep.className = 'ds-menu__sep';
      box.appendChild(sep);
      continue;
    }
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `ds-menu__item${item.danger ? ' ds-menu__item--danger' : ''}`;
    button.setAttribute('role', 'menuitem');
    button.textContent = item.label;
    button.addEventListener('click', () => { dismiss(); item.run(); });
    box.appendChild(button);
  }

  /**
   * Placed where there is room, and measured rather than assumed.
   *
   * It used to open downward always, from a hard-coded 210px width guess. Any
   * anchor near the foot of the window therefore opened off the bottom of it —
   * and the rail's account control sits at the bottom of the rail by definition,
   * so its menu was unreachable in every rail state. Measure the box, prefer
   * below, flip above when below does not fit, and stay inside the viewport on
   * both axes.
   */
  const GAP = 4;
  const EDGE = 8;

  // Inserted invisible so it can be measured before it is placed; the entry
  // animation has not painted a frame yet, so nothing flickers.
  wrap.style.cssText = 'position:fixed;z-index:var(--z-dialog);top:0;left:0;visibility:hidden;';
  wrap.appendChild(box);
  layer().appendChild(wrap);

  const rect = anchor.getBoundingClientRect();
  const size = box.getBoundingClientRect();
  const roomBelow = window.innerHeight - rect.bottom - GAP - EDGE;
  const flip = size.height > roomBelow && rect.top - GAP - EDGE > roomBelow;

  // Flipped, it still grows from the control that opened it, so the origin and
  // the direction of travel invert together.
  if (flip) box.classList.add('ds-menu--up');

  const top = flip
    ? Math.max(EDGE, rect.top - GAP - size.height)
    : Math.min(rect.bottom + GAP, window.innerHeight - size.height - EDGE);
  const left = Math.min(
    Math.max(EDGE, rect.left),
    Math.max(EDGE, window.innerWidth - size.width - EDGE),
  );

  wrap.style.top = `${top}px`;
  wrap.style.left = `${left}px`;
  wrap.style.visibility = '';

  // Deferred, so the click that opened the menu does not immediately close it.
  setTimeout(() => {
    document.addEventListener('pointerdown', onOutside, true);
    document.addEventListener('keydown', onKey, true);
  });

  box.querySelector<HTMLElement>('.ds-menu__item')?.focus();
}
