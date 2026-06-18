// Shared visual vocabulary for the Lead agent surfaces (campaign builder +
// prospecting). One place for the "boxes with all the text" so the cards,
// section headers, score card, and loading/empty states look identical and
// stay in sync across pages. Everything here is a pure string builder (callers
// assign the result to .innerHTML) and stays strictly within the existing
// Tailwind token system — no new colours.

import { escHtml } from './owlChat';

// Canonical HTML escaper for the lead pages (single source of truth).
export const esc = escHtml;

// ─── Primitives ─────────────────────────────────────────────────────────────

export interface CardOpts {
  /** Optional mono uppercase header label. */
  label?: string;
  /** Optional right-aligned value rendered beside the label. */
  value?: string;
  /** Main HTML content of the box (already-escaped / trusted markup). */
  body: string;
  /** 'subtle' (default) or 'strong' border weight. */
  tone?: 'subtle' | 'strong';
  /** Extra classes appended to the box. */
  extra?: string;
}

/** The canonical box: bordered surface-1 panel with an optional header row. */
export function card({ label, value, body, tone = 'subtle', extra = '' }: CardOpts): string {
  const border = tone === 'strong' ? 'border-rule-strong' : 'border-rule-subtle';
  const header = label
    ? `<div class="flex items-baseline justify-between gap-3 mb-2">
         <p class="font-mono text-[11px] uppercase tracking-label text-ink-muted">${esc(label)}</p>
         ${value ? `<span class="font-mono text-[11px] text-ink-secondary">${esc(value)}</span>` : ''}
       </div>`
    : '';
  return `<div class="border ${border} bg-surface-1 rounded-md px-5 py-4 ${extra}">${header}${body}</div>`;
}

export interface SectionHeaderOpts {
  /** Short status text shown muted on the right. */
  status?: string;
  /** Trusted HTML for action buttons rendered on the right. */
  actions?: string;
}

/** The standard section header: mono uppercase label over a strong rule. */
export function sectionHeader(label: string, opts: SectionHeaderOpts = {}): string {
  const right = opts.actions
    ? `<div class="flex items-center gap-2">${opts.actions}</div>`
    : opts.status
      ? `<span class="font-mono text-[10px] uppercase tracking-label text-ink-muted">${esc(opts.status)}</span>`
      : '';
  return `<div class="flex items-baseline justify-between pb-3 mb-4 border-b border-rule-strong">
    <h2 class="font-mono text-[11px] uppercase tracking-label text-ink-primary">${esc(label)}</h2>
    ${right}
  </div>`;
}

/** Dashed placeholder shown before content exists. */
export function emptyState(msg: string): string {
  return `<div class="border border-dashed border-rule-subtle rounded-md bg-surface-1/40 px-6 py-10 text-center">
    <p class="font-mono text-[11px] uppercase tracking-label text-ink-muted">${esc(msg)}</p>
  </div>`;
}

/** Animated placeholder shown while an async operation is in flight. */
export function loadingState(msg: string): string {
  return `<div class="border border-rule-subtle rounded-md bg-surface-1 px-6 py-8 text-center animate-pulse">
    <p class="font-mono text-[11px] uppercase tracking-label text-ink-muted">${esc(msg)}</p>
  </div>`;
}

/** N shimmering card skeletons — used while X-Ray / generation runs. */
export function skeletonCards(n = 3): string {
  const one = `<div class="border border-rule-subtle rounded-md bg-surface-1 px-5 py-4 animate-pulse">
    <div class="h-3 w-1/3 bg-surface-2 rounded mb-3"></div>
    <div class="h-2.5 w-2/3 bg-surface-2 rounded mb-2"></div>
    <div class="h-2.5 w-1/2 bg-surface-2 rounded"></div>
  </div>`;
  return `<div class="space-y-3">${one.repeat(n)}</div>`;
}

// ─── Lead score card ─────────────────────────────────────────────────────────

/** Render the behavioural lead-score card from a signal-analysis object.
 *  Returns '' when no score is present. Single source of truth for both the
 *  campaign builder (Step 1) and the prospecting page. */
export function renderScoreCard(a: any): string {
  if (!a || a.lead_score === undefined || a.lead_score === null) return '';
  const grade = (a.lead_grade || 'C') as string;
  const gc = grade === 'A' ? 'text-accent' : grade === 'B' ? 'text-ink-primary' : 'text-ink-muted';
  const signals = Array.isArray(a.score_signals) ? a.score_signals : [];
  const breakdown = Array.isArray(a.score_breakdown) ? a.score_breakdown : [];
  const rows = breakdown.map((b: any) => {
    const neg = Number(b.points) < 0;
    return `<div class="flex items-baseline justify-between gap-3 py-1 border-t border-rule-subtle">
      <span class="text-sm text-ink-secondary">${esc(b.label)}<span class="text-ink-muted"> · ${esc(b.detail || '')}</span></span>
      <span class="font-mono text-sm ${neg ? 'text-signal-danger' : 'text-ink-primary'}">${neg ? '' : '+'}${esc(String(b.points))}</span>
    </div>`;
  }).join('');
  const sig = signals.length
    ? `<ul class="mt-2 space-y-1">${signals.map((s: string) => `<li class="text-[12px] text-signal-danger">// ${esc(s)}</li>`).join('')}</ul>`
    : '';
  const meta = [a.contact_name, a.role, a.signal_strength && `${a.signal_strength} signal`]
    .filter(Boolean).map((x: string) => esc(x)).join(' · ');
  const body = `
    <div class="flex items-center justify-between">
      <div>
        <p class="font-mono text-[11px] uppercase tracking-label text-ink-muted">Lead score · behavioural</p>
        ${meta ? `<p class="text-sm text-ink-secondary mt-1">${meta}</p>` : ''}
      </div>
      <div class="flex items-baseline gap-2">
        <span class="text-2xl font-semibold tracking-tightest ${gc}">${esc(String(a.lead_score))}</span>
        <span class="font-mono text-[11px] uppercase tracking-label ${gc}">grade ${esc(grade)}</span>
      </div>
    </div>
    ${sig}
    ${rows ? `<details class="mt-3"><summary class="font-mono text-[11px] uppercase tracking-label text-ink-muted cursor-pointer">Breakdown</summary><div class="mt-1">${rows}</div></details>` : ''}`;
  return `<div class="border border-rule-subtle bg-surface-1 rounded-md px-5 py-4 mb-5">${body}</div>`;
}

// ─── Copy-to-clipboard wiring ────────────────────────────────────────────────

/** Wire every `.copy-btn` inside `root`. Each button copies the text from its
 *  `data-copy` attribute (or the textContent of the selector in `data-copy-target`),
 *  flashing a brief confirmation. Idempotent per button. */
export function wireCopyButtons(root: ParentNode = document): void {
  root.querySelectorAll<HTMLButtonElement>('.copy-btn').forEach(btn => {
    if (btn.dataset.copyWired) return;
    btn.dataset.copyWired = '1';
    btn.addEventListener('click', async () => {
      const target = btn.dataset.copyTarget
        ? document.querySelector(btn.dataset.copyTarget)?.textContent ?? ''
        : btn.dataset.copy ?? '';
      try {
        await navigator.clipboard.writeText(target);
        const prev = btn.textContent;
        btn.textContent = 'copied';
        setTimeout(() => { btn.textContent = prev; }, 1200);
      } catch { /* clipboard blocked — non-fatal */ }
    });
  });
}
