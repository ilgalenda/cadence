// Rendering composed outreach touches.
//
// Shown by the Composer agent's page and by the path runner, so it is defined once.
// Every touch is copyable, because nothing here sends: Gmail drafting is a Phase 4
// integration, and until it lands the honest interaction is "copy this into your
// mail client", said plainly rather than implied by a button that looks like Send.
//
// Text is set with `textContent` throughout — these are model-written words.

export interface Touches {
  email?: { subject?: string; body?: string };
  linkedin?: { connection_note?: string; follow_up?: string };
  call?: { opener?: string; talking_points?: string[] };
}

const el = <K extends keyof HTMLElementTagNameMap>(tag: K, className?: string) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
};

/** The plain text of one touch, for the clipboard. */
export function touchText(channel: string, touch: any): string {
  if (channel === 'email') return `Subject: ${touch.subject}\n\n${touch.body}`;
  if (channel === 'linkedin') return `${touch.connection_note}\n\n---\n\n${touch.follow_up}`;
  if (channel === 'call') {
    return [touch.opener, '', ...(touch.talking_points ?? []).map((p: string) => `- ${p}`)].join('\n');
  }
  return '';
}

const CHANNEL_NAMES: Record<string, string> = {
  email: 'Email',
  linkedin: 'LinkedIn',
  call: 'Call',
};

async function copy(text: string, button: HTMLButtonElement, label: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
    button.textContent = 'Copied ✓';
  } catch {
    button.textContent = 'Could not copy';
  }
  window.setTimeout(() => { button.textContent = label; }, 1500);
}

function field(label: string, value: string, mono = false): HTMLElement {
  const wrap = el('div', 'touch__field');
  const key = el('p', 'ds-mono touch__key');
  key.textContent = label;
  const val = el('p', mono ? 'ds-mono touch__value' : 'ds-small touch__value');
  val.textContent = value;
  wrap.append(key, val);
  return wrap;
}

function touchCard(channel: string, touch: any): HTMLElement {
  const card = el('article', 'ds-panel touch');

  const head = el('div', 'touch__head');
  const name = el('h3', 'ds-eyebrow touch__name');
  name.textContent = CHANNEL_NAMES[channel] ?? channel;
  const copyBtn = el('button', 'ds-btn ds-btn--secondary ds-btn--sm');
  copyBtn.type = 'button';
  copyBtn.textContent = 'Copy';
  copyBtn.addEventListener('click', () => copy(touchText(channel, touch), copyBtn, 'Copy'));
  head.append(name, copyBtn);
  card.append(head);

  if (channel === 'email') {
    card.append(field('subject', touch.subject ?? ''));
    card.append(field('body', touch.body ?? ''));
  } else if (channel === 'linkedin') {
    card.append(field('connection note', touch.connection_note ?? ''));
    card.append(field('follow-up', touch.follow_up ?? ''));
  } else if (channel === 'call') {
    card.append(field('opener', touch.opener ?? ''));
    const points = el('div', 'touch__field');
    const key = el('p', 'ds-mono touch__key');
    key.textContent = 'talking points';
    const list = el('ul', 'touch__points');
    for (const point of touch.talking_points ?? []) {
      const li = el('li', 'ds-small');
      li.textContent = point;
      list.append(li);
    }
    points.append(key, list);
    card.append(points);
  }

  return card;
}

/**
 * Draw the touches into `host`.
 *
 * `missing` names the channels that came back unusable. They are stated rather
 * than silently absent: asking for three touches and getting two without being
 * told is indistinguishable from the agent deciding for you.
 */
export function paintTouches(host: HTMLElement, touches: Touches, missing: string[] = []): void {
  host.replaceChildren();

  const written = Object.keys(touches ?? {});
  for (const channel of written) {
    host.append(touchCard(channel, (touches as any)[channel]));
  }

  if (missing.length) {
    const banner = el('div', 'ds-banner ds-banner--drift');
    const label = el('span', 'ds-banner__label');
    label.textContent = 'Not written';
    const body = el('p');
    const names = missing.map((c) => CHANNEL_NAMES[c] ?? c).join(', ');
    body.textContent = `${names} came back incomplete and was not kept. Run it again to retry.`;
    banner.append(label, body);
    host.append(banner);
  }

  if (written.length) {
    const note = el('p', 'ds-caption touch__note');
    note.textContent = 'Nothing has been sent. Copy a touch into your mail client or LinkedIn — '
      + 'drafting straight into Gmail arrives with the Gmail integration.';
    host.append(note);
  }
}

