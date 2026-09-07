from __future__ import annotations
"""Review/Approval gate — the platform's human-in-the-loop primitive.

Every consequential thing an agent produces — an outreach draft, a target list,
a prospect shortlist, a knowledge correction — is *submitted* to a review queue
as ``pending`` and does nothing until a human ``approve``s or ``reject``s it.
This is the single place the platform rule **"agents draft & populate; the human
always sends / decides"** is enforced, so no agent re-implements it.

The rule is enforced structurally: this primitive has no "send" or "execute"
action. An agent can only *submit* a draft; moving it out of ``pending`` is a
human-only decision, and the real-world action (e.g. sending a Gmail draft) is
taken by the human, outside the system.

Storage-agnostic: a :class:`ReviewQueue` is backed by a JSON file whose path the
caller chooses (a per-user drafts file, a per-campaign queue, ...). Deterministic
— no LLM. The knowledge-correction gate in ``agents.shared.vault`` is the
original, domain-specific instance of this same pattern; it converges onto this
primitive when ``lead``/``calls`` are retired (Phase 3).
"""
import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"

#: A history marker, **not** a status an item can hold. It labels the trail entry
#: written when an approved item is acted on — see `record_outcome`. Kept out of
#: `_ALLOWED_TRANSITIONS` so it can never become a decision state.
OUTCOME = "outcome"

# A pending item may only move to a terminal state; terminal decisions are never
# silently rewritten (Immutability). To revisit one, submit a fresh item.
_ALLOWED_TRANSITIONS = {PENDING: {APPROVED, REJECTED}}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class QueueUnreadable(RuntimeError):
    """The queue file exists and could not be read.

    Its own type because the caller's choice matters: an empty queue is a normal
    answer and this is not one.
    """


#: One lock per queue **file**, not per :class:`ReviewQueue`.
#:
#: Every call site builds a fresh queue per call — see the identical
#: `_queue()` helpers in Composer, Recap and GTM — so that a test pointing the
#: data root elsewhere is honoured. A lock held on the instance therefore guarded
#: nothing: two concurrent requests took two different locks over one file, both
#: did a full read-modify-write, and one of them lost. Keyed on the resolved path
#: so the late binding those helpers rely on still works.
_LOCKS: dict[Path, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    key = Path(os.path.abspath(path))
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


@dataclass
class ReviewItem:
    """One reviewable thing and its decision trail."""

    id: str
    kind: str
    status: str
    payload: dict
    submitted_by: str
    created_at: str
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    review_notes: Optional[str] = None
    # Append-only audit of every state transition (Immutability).
    history: list = field(default_factory=list)
    #: What happened when the approved item was acted on — e.g. the Gmail draft that
    #: was created from it. Separate from the decision: a fact discovered *after* it.
    outcome: dict = field(default_factory=dict)

    @property
    def is_pending(self) -> bool:
        return self.status == PENDING

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ReviewItem":
        return cls(**data)


class ReviewQueue:
    """A JSON-backed review queue with an explicit, human-gated state machine."""

    def __init__(self, path: Path | str):
        self._path = Path(path)

    @property
    def _lock(self) -> threading.Lock:
        """Shared by every queue on this file — see `_lock_for`."""
        return _lock_for(self._path)

    # -- persistence --------------------------------------------------------
    def _load(self) -> dict[str, dict]:
        """Every item, or `{}` when there is no queue yet.

        **A file that exists and will not parse raises.** It used to be folded
        into `{}` alongside the missing-file case, which read as "no items" — and
        the next `_save` then wrote that empty dict back over the top. A torn read
        during somebody else's write was enough to erase the queue silently, with
        no exception anywhere to say so. Losing every pending draft is not a state
        this may report as normal.
        """
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            raise QueueUnreadable(f"The review queue at {self._path} could not be read: {e}")

    def _save(self, records: dict[str, dict]) -> None:
        """Replace the file atomically.

        A bare `write_text` truncates first, so every reader between the truncate
        and the write sees a partial file. Writing a sibling and renaming means a
        reader sees either the old queue or the new one, never half of one.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(f"{self._path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(records, indent=2), encoding="utf-8")
            os.replace(temporary, self._path)
        finally:
            temporary.unlink(missing_ok=True)

    # -- commands -----------------------------------------------------------
    def submit(self, *, kind: str, payload: dict, submitted_by: str) -> ReviewItem:
        """Queue a freshly drafted item as ``pending``."""
        if not kind or not kind.strip():
            raise ValueError("submit: kind is required")
        if not submitted_by or not submitted_by.strip():
            raise ValueError("submit: submitted_by is required")

        now = _now()
        item = ReviewItem(
            id=uuid.uuid4().hex,
            kind=kind,
            status=PENDING,
            payload=payload,
            submitted_by=submitted_by,
            created_at=now,
            history=[{"status": PENDING, "by": submitted_by, "at": now, "notes": ""}],
        )
        with self._lock:
            records = self._load()
            records[item.id] = item.to_dict()
            self._save(records)
        return item

    def approve(self, item_id: str, *, reviewed_by: str, notes: str = "") -> ReviewItem:
        """Record the human decision to approve a pending item."""
        return self._decide(item_id, APPROVED, reviewed_by=reviewed_by, notes=notes)

    def reject(self, item_id: str, *, reviewed_by: str, notes: str = "") -> ReviewItem:
        """Record the human decision to reject a pending item."""
        return self._decide(item_id, REJECTED, reviewed_by=reviewed_by, notes=notes)

    def record_outcome(self, item_id: str, *, outcome: dict) -> ReviewItem:
        """Attach what happened when an approved item was acted on.

        **Not a decision, and not a rewrite of one.** The status, the reviewer and the
        timestamps are untouched; this is the *append* the Immutability rule allows —
        a fact learned after the decision, logged with its own history line so the
        trail shows both the approval and what followed from it.

        Only approved items can have an outcome: nothing has been acted on until a
        human said so, and recording delivery against a pending or rejected item would
        describe something that did not happen.
        """
        with self._lock:
            records = self._load()
            raw = records.get(item_id)
            if raw is None:
                raise KeyError(f"No review item with id {item_id}")
            item = ReviewItem.from_dict(raw)
            if item.status != APPROVED:
                raise ValueError(
                    f"Cannot record an outcome for item {item_id}: it is {item.status!r}, "
                    "and only an approved item has been acted on"
                )
            now = _now()
            item.outcome = {**item.outcome, **outcome}
            # `OUTCOME` rather than the item's status: the trail reads
            # pending → approved → outcome, which is what happened. Repeating
            # "approved" would read as a second approval, and it is deliberately not
            # in `_ALLOWED_TRANSITIONS`, so it can never become a decision state.
            item.history.append({
                "status": OUTCOME, "by": item.reviewed_by or "", "at": now,
                "notes": "outcome recorded", "outcome": outcome,
            })
            records[item_id] = item.to_dict()
            self._save(records)
        return item

    def _decide(self, item_id: str, new_status: str, *, reviewed_by: str, notes: str) -> ReviewItem:
        if not reviewed_by or not reviewed_by.strip():
            raise ValueError(f"{new_status}: reviewed_by is required — a human owns this decision")
        with self._lock:
            records = self._load()
            raw = records.get(item_id)
            if raw is None:
                raise KeyError(f"No review item with id {item_id}")
            item = ReviewItem.from_dict(raw)
            if new_status not in _ALLOWED_TRANSITIONS.get(item.status, set()):
                raise ValueError(
                    f"Cannot move item {item_id} from {item.status!r} to {new_status!r}; "
                    f"only {sorted(_ALLOWED_TRANSITIONS.get(item.status, set()))} allowed"
                )
            now = _now()
            item.status = new_status
            item.reviewed_by = reviewed_by
            item.reviewed_at = now
            item.review_notes = notes or None
            item.history.append({"status": new_status, "by": reviewed_by, "at": now, "notes": notes})
            records[item_id] = item.to_dict()
            self._save(records)
        return item

    # -- queries ------------------------------------------------------------
    def get(self, item_id: str) -> Optional[ReviewItem]:
        raw = self._load().get(item_id)
        return ReviewItem.from_dict(raw) if raw else None

    def list(
        self,
        *,
        status: Optional[str] = None,
        kind: Optional[str] = None,
        submitted_by: Optional[str] = None,
    ) -> list[ReviewItem]:
        """Return matching items, newest first."""
        items = [ReviewItem.from_dict(r) for r in self._load().values()]
        if status is not None:
            items = [i for i in items if i.status == status]
        if kind is not None:
            items = [i for i in items if i.kind == kind]
        if submitted_by is not None:
            items = [i for i in items if i.submitted_by == submitted_by]
        return sorted(items, key=lambda i: i.created_at, reverse=True)

    def pending(self, **filters) -> list[ReviewItem]:
        """The reviewer's inbox: everything awaiting a human decision."""
        return self.list(status=PENDING, **filters)
