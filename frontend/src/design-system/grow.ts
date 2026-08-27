/**
 * Growing fields: native where supported, one delegated listener where not.
 *
 * `field-sizing: content` does this in CSS with no JavaScript in Chromium. This
 * is the fallback for engines that lack it — a single document-level listener,
 * so no field ever needs per-instance wiring.
 *
 * The max-height ceiling stays in CSS (`.ds-textarea`, `.ds-composer__input`),
 * so a growing field can never push the send button off screen.
 */
export function enableGrowingFields(root: Document | HTMLElement = document): void {
  if (CSS.supports("field-sizing", "content")) return;

  root.addEventListener("input", (event) => {
    const el = event.target;
    if (!(el instanceof HTMLTextAreaElement)) return;
    if (!el.matches(".ds-textarea, .ds-grow, .ds-composer__input")) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  });
}
