"""Every lead score, kept so the grades can one day be calibrated rather than argued.

The thresholds in `services/lead_scoring.py` were set against nine real Leadinfo
blocks — every one held at the time — and not one of them had ever reached the
pricing or contact page. Numbers chosen from a sample that small are a starting
position, not a calibration, and there was no way to improve on them because
nothing kept a score once the page had rendered it.

This is that record. One row per scored lead, append-only, so a month from now the
question "where should A begin" has a distribution behind it.

**What is deliberately not stored.** The pasted Leadinfo block, the contact's name
and their email never enter this file. Calibration needs the features and the
outcome — which page types, how long, what it scored — and nothing else. A store
that keeps more than its purpose requires is a liability waiting for the day
somebody copies the directory somewhere less careful.
"""
from __future__ import annotations

from pathlib import Path

from paths import sales_data

from agents.sales.store._json import new_id, now_label, read_json, write_json

SCORES_FILE = sales_data() / "scores.json"

#: Rows kept, newest first, oldest dropped. Well above what calibration needs —
#: a few hundred sessions is a usable distribution — and low enough that the file
#: stays something you can open.
MAX_SCORES = 2000


def _scores_file(sandbox: bool) -> Path:
    if sandbox:
        sandboxed = sales_data() / "_sandbox"
        sandboxed.mkdir(parents=True, exist_ok=True)
        return sandboxed / "scores.json"
    return SCORES_FILE


def _load_all(sandbox: bool) -> list[dict]:
    records = read_json(_scores_file(sandbox), [])
    return records if isinstance(records, list) else []


def record(username: str, score: dict, *, company: str = "", sandbox: bool = False) -> dict:
    """Keep one scored lead. Returns the stored row.

    Takes the whole result from `lead_scoring.score_lead` and keeps the parts that
    would let the thresholds be re-fitted: the total, the grade, each component's
    points against its cap, and the page types with their dwell. The URLs come too
    — a page nobody classified is the other thing this file can tell you.
    """
    row = {
        "id": new_id(),
        "username": username,
        "scored_at": now_label(),
        "company": (company or "").strip(),
        "score": score.get("score"),
        "grade": score.get("grade"),
        "components": {
            str(part.get("label")): part.get("points")
            for part in (score.get("breakdown") or []) if isinstance(part, dict)
        },
        "page_views": [
            {"url": view.get("url"), "seconds": view.get("seconds"), "type": view.get("type")}
            for view in (score.get("page_views") or []) if isinstance(view, dict)
        ],
    }
    records = _load_all(sandbox)
    records.insert(0, row)
    write_json(_scores_file(sandbox), records[:MAX_SCORES])
    return row


def all_scores(sandbox: bool = False) -> list[dict]:
    """Every stored score, newest first — the distribution to calibrate against."""
    return _load_all(sandbox)


def distribution(sandbox: bool = False) -> dict:
    """How the stored scores fall: the count per grade and the scores themselves.

    Deliberately raw. Deciding where a grade should begin is a judgement about the
    business, so this hands over the numbers rather than a recommendation.
    """
    scores = [r.get("score") for r in _load_all(sandbox) if isinstance(r.get("score"), int)]
    grades: dict[str, int] = {}
    for row in _load_all(sandbox):
        grade = row.get("grade")
        if isinstance(grade, str):
            grades[grade] = grades.get(grade, 0) + 1
    return {"count": len(scores), "by_grade": grades, "scores": sorted(scores)}
