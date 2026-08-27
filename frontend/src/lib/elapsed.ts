// The elapsed count — the only honest progress a model call has.
//
// No agent call on this platform has a denominator. There is no "step 3 of 7"
// to report, because the model decides how much work the answer needs while it
// is answering. So the readout says **how long**, not how far: a `.ds-meter`
// here would draw a fraction nobody can compute, and a spinner would say only
// that time is passing, which the user already knows.
//
// The design system is explicit that there is no spinner (`primitives.css:529`);
// the ticking second is what replaces it, and it belongs in the mono slot of a
// section head, which is where this platform's grammar puts the machine talking.
//
// Extracted from `xrayRun.ts`, which had the only copy, when GTM needed the same
// thing for a forty-second run. One timer, one place, both callers.

/** A running count, stopped by calling the returned function. */
export type StopElapsed = () => void;

/**
 * Call `onTick` with whole elapsed seconds, once a second, until stopped.
 *
 * Ticks once immediately so the readout never sits blank for the first second —
 * a blank slot at the moment of pressing the button reads as nothing happening.
 * Stopping is idempotent, so a caller that stops on both the success and the
 * failure path cannot double-clear a timer that has already gone.
 */
export function startElapsed(onTick: (seconds: number) => void): StopElapsed {
  const startedAt = Date.now();
  const seconds = () => Math.round((Date.now() - startedAt) / 1000);

  onTick(0);
  let ticking: number | null = window.setInterval(() => onTick(seconds()), 1000);

  return () => {
    if (ticking === null) return;
    window.clearInterval(ticking);
    ticking = null;
  };
}
