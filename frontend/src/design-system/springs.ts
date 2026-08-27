/**
 * Springs — the design system's motion vocabulary, translated once.
 *
 * `tokens.css` states the springs as damping and response, because those are the
 * two numbers a designer reasons about. The animation library wants bounce and
 * visual duration. This module is the only place that conversion happens, so a
 * change to the doctrine stays a change to `tokens.css` and nothing else.
 *
 *   damping 1   → bounce 0    settles onto the target, no overshoot
 *   damping 0.8 → bounce 0.2  overshoots once and returns
 *
 * Why a spring rather than a transition: a transition runs to its target on a
 * fixed clock and cannot be grabbed mid-flight. A spring animates from the
 * current on-screen value, so it can be redirected at any instant. Nothing on
 * the home surface is grabbable yet — `carry` exists so the drawer and sheet
 * work has a defined vocabulary rather than inventing one when it arrives.
 */
import { animate } from 'motion';

export type SpringName = 'settle' | 'carry';

/** Fallbacks, should this run before the stylesheet resolves. Mirrors tokens.css. */
const FALLBACK: Record<SpringName, { damping: number; response: number }> = {
  settle: { damping: 1, response: 0.4 },
  carry: { damping: 0.8, response: 0.3 },
};

/** Stagger unit, should `--dur-step` be unreadable. Mirrors tokens.css. */
const FALLBACK_STEP_SECONDS = 0.036;

function tokens(): CSSStyleDeclaration {
  return getComputedStyle(document.documentElement);
}

function readNumber(property: string, fallback: number): number {
  const value = Number.parseFloat(tokens().getPropertyValue(property));
  return Number.isFinite(value) ? value : fallback;
}

/**
 * Read once: the token values cannot change after load, and reading computed
 * style is a layout-adjacent cost we should not pay per animation.
 */
const VOCABULARY: Record<SpringName, { damping: number; response: number }> = {
  settle: {
    damping: readNumber('--spring-settle-damping', FALLBACK.settle.damping),
    response: readNumber('--spring-settle-response', FALLBACK.settle.response),
  },
  carry: {
    damping: readNumber('--spring-carry-damping', FALLBACK.carry.damping),
    response: readNumber('--spring-carry-response', FALLBACK.carry.response),
  },
};

/** `--dur-step` is authored in ms; the library counts in seconds. */
const STEP_SECONDS = readNumber('--dur-step', FALLBACK_STEP_SECONDS * 1000) / 1000;

/**
 * Read live rather than cached — the preference can change while the page is
 * open, and a stale answer is the one case where honouring it matters most.
 */
export function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * Reduced motion is a gentler equivalent, not an absence: a short cross-fade,
 * long enough to read as a change and short enough not to be motion. Non-zero
 * so the animation still completes and callers waiting on it are not stranded.
 */
const CROSS_FADE = { duration: 0.12, ease: 'linear' } as const;

/** The named spring, as options for the animation library. */
export function spring(name: SpringName = 'settle') {
  if (prefersReducedMotion()) return { ...CROSS_FADE };
  const { damping, response } = VOCABULARY[name];
  return { type: 'spring' as const, bounce: 1 - damping, visualDuration: response };
}

/**
 * The system's entry: a short rise into place, staggered by `--dur-step` so a
 * stack reads as one arrival rather than several. Under reduced motion the rise
 * is dropped and only the fade remains — vestibular motion is the part that has
 * to go, not the feedback that something appeared.
 *
 * Elements are expected to start hidden (`opacity: 0`) in the markup, so there
 * is no flash of the final position before the first frame.
 */
export function reveal(elements: Element[], name: SpringName = 'settle') {
  const still = prefersReducedMotion();
  return elements.map((element, index) =>
    animate(
      element,
      still ? { opacity: [0, 1] } : { opacity: [0, 1], transform: ['translateY(0.5rem)', 'none'] },
      { ...spring(name), delay: index * STEP_SECONDS },
    ),
  );
}
