// The quiz rules, tested where they are easiest to get wrong.
//
// The screen this came from had 720 lines and no tests, and the parts most worth
// being sure of were buried in DOM handlers:
//
//   * the pass mark, at the boundary — 70% passes, 69% does not;
//   * the score is out of every question, so abandoning half way cannot round up
//     to a pass;
//   * a second click cannot overwrite a wrong answer with a right one;
//   * a self-rated flashcard counts, but only an MCQ can be marked;
//   * a model-generated question whose `correct` index is out of range is thrown
//     away rather than rendered as a question nobody can pass.

import { describe, expect, it } from 'vitest';
import {
  advance, answerFlashcard, answerMcq, isAnswered, isLastQuestion, matchesCall,
  PASS_MARK, progress, review, score, startQuiz, tally, usableQuestions,
  type Question, type QuizState,
} from './quiz';

const mcq = (correct = 0): Question => ({
  type: 'mcq',
  question: 'Which oscillator holds over longest?',
  options: ['Rubidium', 'Quartz OCXO', 'TCXO'],
  correct,
  explanation: 'Rubidium drifts least.',
});

const card = (): Question => ({
  type: 'flashcard',
  question: 'What does PTP stand for?',
  answer: 'Precision Time Protocol',
});

const generated = { kind: 'generated' } as const;

/** Answer every question of a quiz correctly, to reach a known score. */
function answerAll(state: QuizState, rights: boolean[]): QuizState {
  let current = state;
  rights.forEach((right, i) => {
    current = { ...current, current: i };
    const question = current.questions[i];
    current = question.type === 'mcq'
      ? answerMcq(current, right ? question.correct : (question.correct + 1) % question.options.length)
      : answerFlashcard(current, right, 'my answer');
  });
  return { ...current, current: 0 };
}

describe('starting', () => {
  it('begins unanswered, on the first question', () => {
    const state = startQuiz([mcq(), card()], generated);
    expect(state.current).toBe(0);
    expect(state.answers).toEqual([null, null]);
    expect(isAnswered(state)).toBe(false);
  });

  it('remembers where the questions came from, so retake repeats it', () => {
    const state = startQuiz([mcq()], { kind: 'call', callId: 'abc' });
    expect(state.source).toEqual({ kind: 'call', callId: 'abc' });
  });
});

describe('answering an MCQ', () => {
  it('marks the right choice right', () => {
    const state = answerMcq(startQuiz([mcq(1)], generated), 1);
    expect(state.answers[0]).toEqual({ kind: 'mcq', chosen: 1, correct: true });
  });

  it('marks a wrong choice wrong, and keeps what was chosen', () => {
    const state = answerMcq(startQuiz([mcq(1)], generated), 2);
    expect(state.answers[0]).toEqual({ kind: 'mcq', chosen: 2, correct: false });
  });

  it('refuses to overwrite an answer already given', () => {
    // Otherwise a second click after seeing the feedback turns a miss into a hit.
    const first = answerMcq(startQuiz([mcq(1)], generated), 2);
    const second = answerMcq(first, 1);
    expect(second.answers[0]).toEqual({ kind: 'mcq', chosen: 2, correct: false });
  });

  it('ignores an MCQ answer on a flashcard', () => {
    const state = answerMcq(startQuiz([card()], generated), 0);
    expect(state.answers[0]).toBeNull();
  });
});

describe('answering a flashcard', () => {
  it('takes the reader at their word', () => {
    const state = answerFlashcard(startQuiz([card()], generated), true, '  PTP  ');
    expect(state.answers[0]).toEqual({ kind: 'flashcard', gotIt: true, typed: 'PTP' });
  });

  it('counts a self-rated miss as wrong', () => {
    const state = answerFlashcard(startQuiz([card()], generated), false);
    expect(score(state).correct).toBe(0);
  });

  it('refuses to overwrite a rating already given', () => {
    const first = answerFlashcard(startQuiz([card()], generated), false, 'no idea');
    expect(answerFlashcard(first, true).answers[0]).toEqual(
      { kind: 'flashcard', gotIt: false, typed: 'no idea' },
    );
  });

  it('ignores a flashcard rating on an MCQ', () => {
    const state = answerFlashcard(startQuiz([mcq()], generated), true);
    expect(state.answers[0]).toBeNull();
  });
});

describe('moving through', () => {
  it('advances one question at a time', () => {
    const { state, finished } = advance(startQuiz([mcq(), mcq()], generated));
    expect(state.current).toBe(1);
    expect(finished).toBe(false);
  });

  it('finishes on the last question rather than walking off the end', () => {
    const last = { ...startQuiz([mcq(), mcq()], generated), current: 1 };
    const { state, finished } = advance(last);
    expect(finished).toBe(true);
    expect(state.current).toBe(1);
    expect(isLastQuestion(state)).toBe(true);
  });

  it('reports progress by questions completed', () => {
    const state = startQuiz([mcq(), mcq(), mcq(), mcq()], generated);
    expect(progress(state)).toEqual({ label: 'Question 1 of 4', fraction: 0 });
    expect(progress({ ...state, current: 2 })).toEqual({ label: 'Question 3 of 4', fraction: 0.5 });
  });
});

describe('the running tally', () => {
  it('counts only what has been answered', () => {
    let state = startQuiz([mcq(0), mcq(0), mcq(0)], generated);
    state = answerMcq(state, 0);
    expect(tally(state)).toEqual({ answered: 1, correct: 1 });
  });

  it('counts across both kinds of question', () => {
    const state = answerAll(startQuiz([mcq(0), card()], generated), [true, true]);
    expect(tally(state)).toEqual({ answered: 2, correct: 2 });
  });
});

describe('scoring', () => {
  it('passes exactly at the mark', () => {
    const state = answerAll(
      startQuiz([mcq(0), mcq(0), mcq(0), mcq(0), mcq(0), mcq(0), mcq(0), mcq(0), mcq(0), mcq(0)], generated),
      [true, true, true, true, true, true, true, false, false, false],
    );
    expect(score(state).pct).toBe(PASS_MARK);
    expect(score(state).passed).toBe(true);
  });

  it('fails just below the mark', () => {
    const state = answerAll(
      startQuiz(Array.from({ length: 100 }, () => mcq(0)), generated),
      Array.from({ length: 100 }, (_, i) => i < 69),
    );
    expect(score(state).pct).toBe(69);
    expect(score(state).passed).toBe(false);
  });

  it('scores out of every question, not out of the ones answered', () => {
    // Answering two of four correctly and stopping is 50%, not 100%.
    let state = startQuiz([mcq(0), mcq(0), mcq(0), mcq(0)], generated);
    state = answerMcq(state, 0);
    state = answerMcq({ ...state, current: 1 }, 0);
    expect(score(state)).toEqual({ correct: 2, total: 4, pct: 50, passed: false });
  });

  it('does not divide by zero on an empty quiz', () => {
    expect(score(startQuiz([], generated))).toEqual({ correct: 0, total: 0, pct: 0, passed: false });
    expect(progress(startQuiz([], generated)).fraction).toBe(0);
  });
});

describe('the review', () => {
  it('shows what was chosen against what was right', () => {
    const state = answerMcq(startQuiz([mcq(1)], generated), 2);
    const [row] = review(state);
    expect(row.correct).toBe(false);
    expect(row.given).toBe('TCXO');
    expect(row.expected).toBe('Quartz OCXO');
  });

  it('shows a flashcard against the real answer', () => {
    const state = answerFlashcard(startQuiz([card()], generated), false, 'no idea');
    const [row] = review(state);
    expect(row.given).toBe('no idea');
    expect(row.expected).toBe('Precision Time Protocol');
  });

  it('includes questions never answered', () => {
    const rows = review(startQuiz([mcq(), card()], generated));
    expect(rows).toHaveLength(2);
    expect(rows.every((r) => r.answer === null && !r.correct)).toBe(true);
    expect(rows[1].expected).toBe('Precision Time Protocol');
  });
});

describe('what the model returns', () => {
  it('keeps well-formed questions of both kinds', () => {
    expect(usableQuestions([mcq(), card()])).toHaveLength(2);
  });

  it('throws away an MCQ whose correct index is out of range', () => {
    // A model-generated quiz can do this, and it would be unanswerable.
    expect(usableQuestions([{ ...mcq(), correct: 9 }])).toEqual([]);
    expect(usableQuestions([{ ...mcq(), correct: -1 }])).toEqual([]);
  });

  it('throws away an MCQ with too few options', () => {
    expect(usableQuestions([{ ...mcq(), options: ['only one'], correct: 0 }])).toEqual([]);
  });

  it('throws away an empty or malformed entry', () => {
    expect(usableQuestions([null, 'nonsense', {}, { type: 'mcq', question: '  ' }])).toEqual([]);
    expect(usableQuestions([{ type: 'flashcard', question: 'Q?', answer: '' }])).toEqual([]);
  });

  it('is not fooled by a non-array payload', () => {
    expect(usableQuestions(undefined)).toEqual([]);
    expect(usableQuestions({ questions: [mcq()] })).toEqual([]);
  });
});

describe('matchesCall', () => {
  const call = { title: 'Northgate — timing refresh', concepts: ['Holdover', 'PTP', 'MiFID II'] };

  it('matches everything when nothing is typed', () => {
    expect(matchesCall(call, '')).toBe(true);
    expect(matchesCall(call, '   ')).toBe(true);
  });

  it('matches on the title, ignoring case', () => {
    expect(matchesCall(call, 'northgate')).toBe(true);
    expect(matchesCall(call, 'NORTHGATE')).toBe(true);
  });

  it('matches on a concept, which is the other way a call is remembered', () => {
    expect(matchesCall(call, 'holdover')).toBe(true);
    expect(matchesCall(call, 'mifid')).toBe(true);
  });

  it('does not match what is in neither', () => {
    expect(matchesCall(call, 'broadcast')).toBe(false);
  });

  it('ignores surrounding whitespace in the needle', () => {
    expect(matchesCall(call, '  ptp  ')).toBe(true);
  });

  it('survives a call with no concepts', () => {
    expect(matchesCall({ title: 'Untitled', concepts: [] }, 'untitled')).toBe(true);
    expect(matchesCall({ title: 'Untitled', concepts: undefined as never }, 'untitled')).toBe(true);
  });
});

// A generated batch is model output, so it is untidy in predictable ways. The
// validator's job is to throw away questions NOBODY CAN PASS — not questions
// that merely failed to label themselves.
describe('usableQuestions, against real model output', () => {
  it('accepts an MCQ that omitted its type, inferring it from shape', () => {
    const q = {
      question: 'Which oscillator holds over longest?',
      options: ['Rubidium', 'Quartz OCXO', 'TCXO'],
      correct: 0,
      explanation: 'Rubidium ages far more slowly.',
    };
    expect(usableQuestions([q])).toHaveLength(1);
    expect(usableQuestions([q])[0].type).toBe('mcq');
  });

  it('accepts a flashcard that omitted its type', () => {
    const q = { question: 'What is holdover?', answer: 'Keeping time without a reference.' };
    expect(usableQuestions([q])).toHaveLength(1);
    expect(usableQuestions([q])[0].type).toBe('flashcard');
  });

  it('accepts a correct index the model wrote as a string', () => {
    const q = {
      type: 'mcq',
      question: 'Which is the most stable?',
      options: ['TCXO', 'Rubidium'],
      correct: '1',
    };
    const [out] = usableQuestions([q]);
    expect(out).toBeDefined();
    expect((out as { correct: number }).correct).toBe(1);
  });

  it('still refuses a question nobody can pass', () => {
    // Index out of range — there is no right answer to pick.
    expect(usableQuestions([{
      type: 'mcq', question: 'q', options: ['a', 'b'], correct: 7,
    }])).toHaveLength(0);
    // A lone option is not a choice.
    expect(usableQuestions([{ type: 'mcq', question: 'q', options: ['a'], correct: 0 }])).toHaveLength(0);
    // Neither shape.
    expect(usableQuestions([{ question: 'q' }])).toHaveLength(0);
    // A fractional index is not an option number.
    expect(usableQuestions([{
      type: 'mcq', question: 'q', options: ['a', 'b'], correct: 1.5,
    }])).toHaveLength(0);
  });
});
