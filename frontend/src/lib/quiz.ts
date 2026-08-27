// Taking a quiz — the rules, apart from the screen.
//
// This came out of `agents/calls/quiz.astro`, where 720 lines mixed the state
// machine with the DOM and nothing was tested. Scoring, the pass mark and the
// difference between a marked answer and a self-rated one are exactly the things
// worth being sure of, so they live here: pure, no DOM, no fetch, no storage.
//
// Two kinds of question, and the distinction matters. An MCQ is *marked* — the
// answer is right or wrong on its own terms. A flashcard is *self-rated* — the
// reader says whether they knew it. Both count toward the score, because both are
// the reader testing themselves, but only one of them can be graded.

export interface McqQuestion {
  type: 'mcq';
  question: string;
  options: string[];
  correct: number;
  explanation: string;
}

export interface FlashcardQuestion {
  type: 'flashcard';
  question: string;
  answer: string;
}

export type Question = McqQuestion | FlashcardQuestion;

export interface McqAnswer { kind: 'mcq'; chosen: number; correct: boolean }
export interface FlashcardAnswer { kind: 'flashcard'; gotIt: boolean; typed: string }
export type Answer = McqAnswer | FlashcardAnswer;

/** Where the questions came from, so "retake" can repeat the same thing. */
export type Source = { kind: 'generated' } | { kind: 'call'; callId: string };

export interface QuizState {
  questions: Question[];
  current: number;
  answers: (Answer | null)[];
  source: Source;
}

/** The mark a reader has to reach. One place, so the screen cannot disagree. */
export const PASS_MARK = 70;

export function startQuiz(questions: Question[], source: Source): QuizState {
  return {
    questions,
    current: 0,
    answers: new Array(questions.length).fill(null),
    source,
  };
}

export const currentQuestion = (state: QuizState): Question | undefined =>
  state.questions[state.current];

export const isCorrect = (answer: Answer): boolean =>
  answer.kind === 'mcq' ? answer.correct : answer.gotIt;

/** Whether this question has been answered — used to keep the reader honest. */
export const isAnswered = (state: QuizState, index = state.current): boolean =>
  state.answers[index] != null;

/**
 * Record an MCQ choice. Ignored if this question is already answered: a second
 * click must not overwrite a wrong answer with a right one.
 */
export function answerMcq(state: QuizState, choice: number): QuizState {
  const question = currentQuestion(state);
  if (!question || question.type !== 'mcq' || isAnswered(state)) return state;

  const answers = [...state.answers];
  answers[state.current] = {
    kind: 'mcq',
    chosen: choice,
    correct: choice === question.correct,
  };
  return { ...state, answers };
}

/** Record a self-rating on a flashcard. Also refuses to overwrite. */
export function answerFlashcard(state: QuizState, gotIt: boolean, typed = ''): QuizState {
  const question = currentQuestion(state);
  if (!question || question.type !== 'flashcard' || isAnswered(state)) return state;

  const answers = [...state.answers];
  answers[state.current] = { kind: 'flashcard', gotIt, typed: typed.trim() };
  return { ...state, answers };
}

export const isLastQuestion = (state: QuizState): boolean =>
  state.current >= state.questions.length - 1;

/**
 * Move on. Returns `finished` on the last question instead of walking past the
 * end, so the caller shows the score rather than an empty card.
 */
export function advance(state: QuizState): { state: QuizState; finished: boolean } {
  if (isLastQuestion(state)) return { state, finished: true };
  return { state: { ...state, current: state.current + 1 }, finished: false };
}

/** Progress so far — counts only what has actually been answered. */
export function tally(state: QuizState): { answered: number; correct: number } {
  const answered = state.answers.filter((a): a is Answer => a != null);
  return { answered: answered.length, correct: answered.filter(isCorrect).length };
}

export interface Score {
  correct: number;
  total: number;
  pct: number;
  passed: boolean;
}

/**
 * The final score, out of every question — not out of the ones answered.
 *
 * Abandoning a quiz half way cannot round up to a pass; an unanswered question is
 * a question the reader did not know.
 */
export function score(state: QuizState): Score {
  const total = state.questions.length;
  const { correct } = tally(state);
  const pct = total ? Math.round((correct / total) * 100) : 0;
  return { correct, total, pct, passed: pct >= PASS_MARK };
}

export interface Progress {
  label: string;
  /** 0–1, for the meter. Reflects questions completed, not the one in hand. */
  fraction: number;
}

export function progress(state: QuizState): Progress {
  const total = state.questions.length;
  return {
    label: `Question ${Math.min(state.current + 1, total)} of ${total}`,
    fraction: total ? state.current / total : 0,
  };
}

export interface ReviewRow {
  question: Question;
  answer: Answer | null;
  correct: boolean;
  /** What the reader put — the option they chose, or what they typed. */
  given: string;
  /** What was right. Empty for a flashcard the reader never rated. */
  expected: string;
}

/** Every question with what happened, for the screen after the last one. */
export function review(state: QuizState): ReviewRow[] {
  return state.questions.map((question, i) => {
    const answer = state.answers[i];
    const correct = answer != null && isCorrect(answer);

    if (question.type === 'mcq') {
      const chosen = answer?.kind === 'mcq' ? question.options[answer.chosen] : '';
      return {
        question,
        answer,
        correct,
        given: chosen ?? '',
        expected: question.options[question.correct] ?? '',
      };
    }
    return {
      question,
      answer,
      correct,
      given: answer?.kind === 'flashcard' ? answer.typed : '',
      expected: question.answer,
    };
  });
}

/**
 * Whether a payload from `/api/learn/quiz/*` is usable.
 *
 * Questions are model-generated, so a malformed one is a live possibility rather
 * than a hypothetical. A quiz with a `correct` index pointing outside its options
 * would be unanswerable, so it is rejected here instead of rendering a question
 * nobody can pass.
 */
/**
 * An option index as the model wrote it.
 *
 * `"correct": "2"` is a routine thing for a model to emit and means exactly what
 * `2` means, so it is read rather than refused. A fraction is not an option
 * number and is refused, because rounding one would invent a right answer.
 */
function optionIndex(value: unknown): number | null {
  const n = typeof value === 'string' && value.trim() !== '' ? Number(value) : value;
  return typeof n === 'number' && Number.isInteger(n) ? n : null;
}

export function usableQuestions(raw: unknown): Question[] {
  if (!Array.isArray(raw)) return [];

  // Normalises as well as filters: a generated batch is model output, and the
  // bar is "can someone answer this", not "did it label itself". A question with
  // options and a valid index IS an MCQ whether or not it said so — refusing it
  // over a missing `type` threw away whole usable batches.
  return raw.flatMap((q): Question[] => {
    if (!q || typeof q !== 'object') return [];
    const candidate = q as Partial<McqQuestion> & Partial<FlashcardQuestion>;
    const question = typeof candidate.question === 'string' ? candidate.question.trim() : '';
    if (!question) return [];

    const options = Array.isArray(candidate.options)
      && candidate.options.length > 1
      && candidate.options.every((o) => typeof o === 'string')
      ? candidate.options as string[]
      : null;
    const correct = optionIndex(candidate.correct);
    const answer = typeof candidate.answer === 'string' ? candidate.answer.trim() : '';

    // An explicit type is honoured where the shape supports it; where it is
    // missing or wrong, the shape decides. MCQ is tried first: a question
    // carrying options and an index is one, whatever else it also carries.
    if (candidate.type !== 'flashcard' && options && correct !== null
        && correct >= 0 && correct < options.length) {
      return [{
        type: 'mcq',
        question,
        options,
        correct,
        explanation: typeof candidate.explanation === 'string' ? candidate.explanation : '',
      }];
    }

    if (answer) return [{ type: 'flashcard', question, answer }];

    return [];
  });
}

/** A call as the practice pool describes it — only what filtering needs. */
export interface FilterableCall {
  title: string;
  concepts: string[];
}

/**
 * Does this call match what someone typed?
 *
 * Title and concepts both count, because "the Northgate call" and "holdover" are
 * equally how a call is remembered. An empty needle matches everything, so the
 * caller never has to special-case the unfiltered list.
 */
export function matchesCall(call: FilterableCall, needle: string): boolean {
  const wanted = needle.trim().toLowerCase();
  if (!wanted) return true;
  const hay = [call.title, ...(call.concepts ?? [])].join(' ').toLowerCase();
  return hay.includes(wanted);
}
