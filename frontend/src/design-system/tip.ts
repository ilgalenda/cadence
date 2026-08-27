/**
 * Tooltip placement.
 *
 * `.ds-tip__body` is `position: fixed`, so it answers to the viewport rather
 * than to whichever rail or header happens to contain it. That is the whole
 * point of the primitive: an absolutely-positioned bubble is clipped by any
 * scrolling ancestor, and the platform's triggers routinely sit within the
 * pill's own height of one. The cost is that the coordinates have to be
 * computed, which is what this module does.
 */

/** Breathing room between the pill and both its trigger and the window edge. */
const GAP = 8;

export interface Box { width: number; height: number }
export interface Point { top: number; left: number }

/**
 * Place the pill above its trigger, or below it when there is no headroom,
 * horizontally centred and always kept inside the window.
 *
 * Pure geometry, so the flip and the clamp can be tested without a browser.
 */
export function tipPlacement(trigger: DOMRect | Box & Point, pill: Box, viewport: Box): Point {
  const t = trigger as DOMRect;
  const above = t.top - pill.height - GAP;
  const top = above >= GAP ? above : t.bottom + GAP;

  const centred = t.left + t.width / 2 - pill.width / 2;
  const rightmost = viewport.width - pill.width - GAP;
  // A pill wider than the window clamps to the left edge rather than a negative
  // right-hand bound, so the start of the label is always the part you keep.
  const left = Math.max(GAP, Math.min(centred, Math.max(GAP, rightmost)));

  return { top, left };
}

/**
 * Wire every `.ds-tip` on the page, including ones built later.
 *
 * Delegated from the document rather than bound per node, because the
 * transcript mints tooltips as it streams and nothing would re-run an
 * initialiser for them.
 */
export function enableTips(): void {
  let shown: HTMLElement | null = null;

  const hide = (): void => {
    shown?.classList.remove('is-on');
    shown = null;
  };

  const show = (wrap: HTMLElement): void => {
    const pill = wrap.querySelector<HTMLElement>('.ds-tip__body');
    if (!pill || pill === shown) return;
    hide();

    // Measured before it is shown — the pill has layout at `opacity: 0`, so
    // this avoids placing it at the origin for a frame first.
    const { top, left } = tipPlacement(
      wrap.getBoundingClientRect(),
      { width: pill.offsetWidth, height: pill.offsetHeight },
      { width: window.innerWidth, height: window.innerHeight },
    );
    pill.style.top = `${top}px`;
    pill.style.left = `${left}px`;
    pill.classList.add('is-on');
    shown = pill;
  };

  const enter = (event: Event): void => {
    const target = event.target as Element | null;
    const wrap = target?.closest?.('.ds-tip') as HTMLElement | null;
    if (wrap) show(wrap);
    else if (shown) hide();
  };

  document.addEventListener('mouseover', enter);
  document.addEventListener('focusin', enter);
  document.addEventListener('mouseout', (event) => {
    const to = (event as MouseEvent).relatedTarget as Element | null;
    if (!to?.closest?.('.ds-tip')) hide();
  });
  document.addEventListener('focusout', hide);

  // A label pinned to a control that has moved is worse than no label. Capture,
  // so inner scrollers count and not just the window.
  document.addEventListener('scroll', hide, true);
  window.addEventListener('resize', hide);
}
