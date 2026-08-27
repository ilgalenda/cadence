// The Owl transcript, rendered once.
//
// Both surfaces — the full workspace and the in-context drawer — are the same
// product in two placements, so the transcript is built here rather than twice.
//
// **Not a chat. A logbook.** Each exchange is one entry with two columns: the
// reading column carries language only — the question, then the answer as prose —
// and the left spine carries everything the machine has to say about itself: when
// it was asked, which model, how long, every tool it ran, and the actions on the
// answer. There are no "You"/"Owl" bylines; with two voices, typography is enough.
//
// Visuals come entirely from the design system (`.ds-log`, `.ds-x`, `.ds-tick`,
// `.ds-caret`, `.ds-answer`). This module owns only the behaviour: what an entry
// is made of, how streamed text settles into typeset prose, and when the view
// follows the latest line.

import { renderMarkdown } from './owlChat';

export type ModelTier = 'fast' | 'deep';

/** Owl's two tiers, named for what they are rather than which model serves them. */
export function tierOf(model: string | null | undefined): ModelTier {
  return (model || '').includes('haiku') ? 'fast' : 'deep';
}

export function clockLabel(date = new Date()): string {
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

const COPY_ICON =
  '<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><rect x="2.5" y="2.5" width="6.5" height="6.5" rx="1" stroke="currentColor" stroke-width="1.1"/><path d="M5 11.5h5.5a1 1 0 001-1V5" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"/></svg>';

/** Elapsed, in the spine's register: sub-second work is not worth three digits. */
function elapsedLabel(ms: number): string {
  return ms < 950 ? `${Math.max(1, Math.round(ms / 100)) / 10}s` : `${(ms / 1000).toFixed(1)}s`;
}

const el = <K extends keyof HTMLElementTagNameMap>(tag: K, className?: string) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
};

/** A live Owl answer. The caller streams into it and then settles it. */
export interface AnswerHandle {
  /** The exchange this answer belongs to. */
  readonly turn: HTMLElement;
  /** Text streamed so far — used to preserve a partial answer on error. */
  readonly streamed: string;
  setTier(model: string): void;
  setText(full: string): void;
  /** What the machine is doing, shown live in the spine. Replaced as work moves on. */
  setActivity(label: string): void;
  /** A finished tool call, recorded in the spine. */
  addTick(label: string, kind?: 'done' | 'fault' | 'canon'): void;
  /** Replace the stream with typeset prose. Removes the entry if empty. */
  /** Renders the answer. Returns false when it rendered to nothing. */
  finalise(full: string): boolean;
  /** State the failure without destroying what was already read. */
  fail(message: string): void;
  remove(): void;
}

export interface ThreadOptions {
  /** The `.ds-log` element entries are appended to. */
  container: HTMLElement;
  /** The scrolling ancestor. Often the container's parent. */
  scroller: HTMLElement;
  /** Copy feedback. Omit to stay silent. */
  onNotice?: (message: string) => void;
  /** Called when the reader moves away from, or back to, the latest line. */
  onFollowChange?: (following: boolean) => void;
}

export interface Thread {
  clear(): void;
  isEmpty(): boolean;
  appendQuestion(text: string, meta?: string): void;
  createAnswer(tier?: ModelTier | null): AnswerHandle;
  /** Drop arbitrary markup into the transcript — an empty state, a correction card. */
  append(node: HTMLElement): void;
  setEmptyState(html: string): void;
  clearEmptyState(): void;
  scrollToLatest(force?: boolean): void;
  /** True while the view is pinned to the latest line. */
  readonly following: boolean;
  follow(): void;
}

export function createThread(options: ThreadOptions): Thread {
  const { container, scroller, onNotice, onFollowChange } = options;

  // Following means "pinned to the live edge". A reader who has scrolled up is
  // never yanked back down mid-answer; the caller offers a jump control instead.
  let following = true;
  const FOLLOW_SLACK_PX = 80;

  // The entry a question has opened and an answer will fill. An exchange is one
  // `<article>`, so the two calls have to meet on the same element.
  let open: HTMLElement | null = null;

  scroller.addEventListener('scroll', () => {
    const distance = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
    const next = distance < FOLLOW_SLACK_PX;
    if (next !== following) {
      following = next;
      onFollowChange?.(following);
    }
  });

  const scrollToLatest = (force = false): void => {
    if (!following && !force) return;
    scroller.scrollTop = scroller.scrollHeight;
  };

  const clearEmptyState = (): void => {
    container.querySelector('[data-empty]')?.remove();
  };

  /** A spine tick. The square is the state; the words are the detail. */
  function tick(label: string, kind?: string): HTMLElement {
    const node = el('span', kind ? `ds-tick ds-tick--${kind}` : 'ds-tick');
    node.textContent = label;
    return node;
  }

  function copyAction(text: string): HTMLElement {
    const tip = el('span', 'ds-tip');

    const button = el('button', 'ds-icon-btn');
    button.type = 'button';
    button.setAttribute('aria-label', 'Copy answer');
    button.innerHTML = COPY_ICON;
    button.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(text);
        onNotice?.('Copied.');
      } catch {
        onNotice?.('Could not copy — your browser blocked clipboard access.');
      }
    });

    const label = el('span', 'ds-tip__body');
    label.textContent = 'copy';

    tip.append(button, label);
    return tip;
  }

  return {
    get following() {
      return following;
    },

    follow() {
      following = true;
      onFollowChange?.(true);
      scrollToLatest(true);
    },

    clear() {
      container.innerHTML = '';
      open = null;
    },

    isEmpty() {
      return container.querySelector('.ds-x') === null;
    },

    append(node) {
      clearEmptyState();
      container.appendChild(node);
      scrollToLatest();
    },

    setEmptyState(html) {
      container.innerHTML = `<div data-empty>${html}</div>`;
      open = null;
    },

    clearEmptyState,

    /**
     * Open an entry with the question.
     *
     * The stamp is the time asked, in the spine. `meta` may be empty — a restored
     * conversation has no per-message time, and an empty stamp is better than an
     * invented one.
     */
    appendQuestion(text, meta = clockLabel()) {
      clearEmptyState();

      const entry = el('article', 'ds-x');

      const stamp = el('p', 'ds-x__stamp ds-arrive');
      stamp.textContent = meta;

      const question = el('p', 'ds-x__q ds-arrive');
      question.textContent = text;

      entry.append(stamp, question);
      container.appendChild(entry);
      open = entry;
      scrollToLatest();
    },

    createAnswer(tier = null) {
      clearEmptyState();

      // Fill the entry the question opened. Without one — a bare assistant
      // message on restore — start an entry so the answer still has a column.
      const entry = open ?? (() => {
        const fresh = el('article', 'ds-x');
        container.appendChild(fresh);
        return fresh;
      })();
      open = null;

      const spine = el('div', 'ds-x__spine ds-arrive');
      spine.style.setProperty('--arrive', '80ms');

      const modelTick = tick(tier === 'fast' ? 'haiku' : 'sonnet', 'model');
      if (tier === null) modelTick.hidden = true;
      spine.appendChild(modelTick);

      // What the machine is doing, live. The spine reports it; the prose column
      // shows a caret and nothing else.
      const activity = tick('working', 'live');
      spine.appendChild(activity);

      const body = el('div', 'ds-x__body ds-arrive');
      body.style.setProperty('--arrive', '160ms');
      body.innerHTML = '<div class="ds-answer"><p><span class="ds-caret"></span></p></div>';

      entry.append(spine, body);
      scrollToLatest();

      const startedAt = Date.now();
      let stream: HTMLElement | null = null;

      /**
       * Drop the live tick and record how long it took.
       *
       * Elapsed is only shown when the answer actually streamed. A restored
       * conversation goes straight from `createAnswer` to `finalise` in the same
       * tick, and reporting "0.1s" against a message from last week would be an
       * invented measurement — the one thing a readout must never be.
       */
      const settleSpine = (): void => {
        activity.remove();
        if (stream === null) return;
        if (!spine.querySelector('[data-elapsed]')) {
          const elapsed = tick(elapsedLabel(Date.now() - startedAt));
          elapsed.setAttribute('data-elapsed', '');
          spine.appendChild(elapsed);
        }
      };

      const handle: AnswerHandle = {
        turn: entry,

        get streamed() {
          return stream?.textContent || '';
        },

        setTier(model) {
          const resolved = tierOf(model);
          modelTick.hidden = false;
          modelTick.textContent = resolved === 'fast' ? 'haiku' : 'sonnet';
        },

        setActivity(label) {
          activity.textContent = label;
        },

        addTick(label, kind = 'done') {
          // Before the live tick, so the running line stays at the bottom of the
          // spine where the eye expects the current state.
          spine.insertBefore(tick(label, kind), activity);
          scrollToLatest();
        },

        setText(full) {
          if (!stream) {
            body.innerHTML = '';
            stream = el('div', 'ds-streaming');
            body.appendChild(stream);
          }
          stream.textContent = full;
        },

        finalise(full) {
          const html = renderMarkdown(full);
          if (!html.trim()) {
            // Nothing came back. The question stays — it was asked, and the
            // server has already stored it — and the spine says what happened.
            settleSpine();
            body.innerHTML = '';
            return false;
          }
          settleSpine();
          body.innerHTML = `<div class="ds-answer">${html}</div>`;

          // Actions live in the spine's margin, revealed on hover or focus.
          const acts = el('div', 'ds-x__acts');
          acts.appendChild(copyAction(full));
          entry.appendChild(acts);

          scrollToLatest();
          return true;
        },

        // An error must never eat an answer the user was already reading: settle
        // whatever streamed, then state the failure in both registers — a fault
        // tick in the spine, and the reason in the prose column where it is read.
        fail(message) {
          const partial = stream?.textContent || '';
          // `finalise` reports false when the partial rendered to nothing; either
          // way the entry survives, so the tick and the reason below always land
          // on a node that is still in the document.
          if (!partial || handle.finalise(partial) === false) {
            settleSpine();
            body.innerHTML = '';
          }

          spine.appendChild(tick('failed', 'fault'));

          const line = el('p', 'ds-mono ds-error');
          line.textContent = message;
          body.appendChild(line);
          scrollToLatest();
        },

        remove() {
          entry.remove();
        },
      };

      return handle;
    },

    scrollToLatest,
  };
}
