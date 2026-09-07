"""The outbound tracker's record: trackers, their accounts, and what has happened.

Two decisions carry this module.

**A touch is an event, not a flag.** Firing touch 3 appends a fact with a date and
an actor; clearing it appends another. The row's touch state is read back from that
trail rather than stored, so "this was sent and then retracted" stays distinguishable
from "this was never sent" — which is the distinction manual suppression depends on.
The published artefact this replaces could not hold it.

**A status may move anywhere, and every move is kept.** The temptation is a strict
transition table, but the record belongs to the person working the list: a reply can
arrive before any touch is logged, a mis-click needs correcting, and an account
closed out in error must reopen. Refusing those would only teach people to work
around the tracker, which is worse than a wrong cell. So the guard is on the
*vocabulary*, not the direction — an unknown status is refused by name — and the
audit trail, not the state machine, is what makes the record trustworthy.

Errors are raised as ``ValueError`` with a message written for the person who hit
it; ``routes`` turns those into a 400, following ``agents/events``.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Iterable, Optional

from agents.outbound import db, valuation
from agents.outbound.valuation import Deal, Line
from agents.sales.store._json import new_id

#: The sequence, in the order it is worked. Order matters for display and for the
#: counters; it is deliberately not enforced as a transition table (see above).
STATUSES = (
    "not_started",
    "sequencing",
    "replied",
    "meeting",
    "qualified",
    "dead",
)

#: A reply has happened by the time an account reaches any of these.
REPLIED_STATUSES = frozenset({"replied", "meeting", "qualified"})

#: A conversation has happened by the time an account reaches either of these.
CALL_STATUSES = frozenset({"meeting", "qualified"})

#: The five touches, in order. Named because a tracker column headed `t3` tells a
#: reader nothing about what was actually sent.
TOUCHES = (
    (1, "LinkedIn connection"),
    (2, "LinkedIn message"),
    (3, "Email"),
    (4, "Value-add"),
    (5, "Break-up"),
)

TOUCH_COUNT = len(TOUCHES)

CONFIDENCES = ("high", "medium", "low")

CAMPAIGNS = ("A-jamming", "B-tdd", "C-finance")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Trackers
# ---------------------------------------------------------------------------

def create_tracker(
    name: str,
    username: str,
    *,
    goal_gbp: int = 0,
    target_touches: int = 0,
    target_replies: int = 0,
    target_calls: int = 0,
    target_qualified: int = 0,
) -> dict:
    """Start a tracker. The goals are stored so the counters mean something."""
    name = (name or "").strip()
    if not name:
        raise ValueError("The tracker needs a name.")

    record = {
        "id": new_id(),
        "name": name,
        "username": username,
        "goal_gbp": max(0, int(goal_gbp or 0)),
        "target_touches": max(0, int(target_touches or 0)),
        "target_replies": max(0, int(target_replies or 0)),
        "target_calls": max(0, int(target_calls or 0)),
        "target_qualified": max(0, int(target_qualified or 0)),
        "artifact_url": "",
        "created_at": _now(),
        "updated_at": _now(),
    }
    with db.connect() as conn:
        conn.execute(
            """INSERT INTO trackers (id, name, username, goal_gbp, target_touches,
                                     target_replies, target_calls, target_qualified,
                                     artifact_url, created_at, updated_at)
               VALUES (:id, :name, :username, :goal_gbp, :target_touches,
                       :target_replies, :target_calls, :target_qualified,
                       :artifact_url, :created_at, :updated_at)""",
            record,
        )
    return record


def list_trackers(username: Optional[str] = None) -> list[dict]:
    """Every tracker, newest first — or only one person's."""
    sql = "SELECT * FROM trackers"
    params: tuple = ()
    if username is not None:
        sql += " WHERE username = ?"
        params = (username,)
    sql += " ORDER BY created_at DESC"
    with db.connect() as conn:
        return [dict(row) for row in conn.execute(sql, params)]


def get_tracker(tracker_id: str) -> Optional[dict]:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM trackers WHERE id = ?", (tracker_id,)).fetchone()
    return dict(row) if row else None


def set_artifact_url(tracker_id: str, url: str) -> dict:
    """Record where this tracker's published share view lives."""
    tracker = _require_tracker(tracker_id)
    with db.connect() as conn:
        conn.execute(
            "UPDATE trackers SET artifact_url = ?, updated_at = ? WHERE id = ?",
            ((url or "").strip(), _now(), tracker_id),
        )
    tracker["artifact_url"] = (url or "").strip()
    return tracker


def delete_tracker(tracker_id: str) -> dict:
    """Delete a campaign, its accounts and their trail. Returns what was removed.

    **A hard delete, and the one place this module destroys rather than appends.**
    Everything else here is append-or-supersede on purpose: a touch cleared is a
    second event, a status moved keeps both ends. This is the exception because a
    campaign somebody created by mistake has no reason to be kept, and a record
    littered with abandoned lists is a record nobody trusts.

    The cost is real and the caller must state it before asking: the touch trail
    is the suppression record for a manual sequence, so deleting a campaign that
    has been worked destroys the only evidence of what was already sent. The
    return says how much of that there was, so a caller can report it afterwards
    rather than only warning beforehand.

    Rows and events go with it through `ON DELETE CASCADE`, which is enforced
    because `db.connect` sets `PRAGMA foreign_keys = ON`.
    """
    tracker = _require_tracker(tracker_id)
    rows = get_rows(tracker_id)
    removed = {
        "id": tracker_id,
        "name": tracker["name"],
        "accounts": len(rows),
        "touches": sum(1 for row in rows for touch in row["touches"] if touch["fired"]),
        "events": sum(len(row["history"]) for row in rows),
    }

    with db.connect() as conn:
        conn.execute("DELETE FROM trackers WHERE id = ?", (tracker_id,))

    return removed


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------

def add_rows(tracker_id: str, proposals: Iterable[dict], actor: str) -> dict:
    """Put accounts on a tracker, pricing each one as it lands.

    An account already on the tracker is **left alone**, not overwritten: a later
    proposal must not silently discard the state a person has built against it.
    The return says which were added and which were already there, so the caller
    can show that rather than implying everything was new.

    **All of the list, or none of it.** Each insert used to open and commit its own
    connection inside the loop, so a row the store refuses — a tier out of range, a
    campaign that has since been renamed, a trigger with no source — left the rows
    before it committed, the return value discarded and `_touch_tracker` skipped.
    The caller then had a list it believed had not landed and a tracker that was
    half built. One connection around the whole loop means a refusal rolls the
    batch back, which is what makes retrying the list safe.
    """
    _require_tracker(tracker_id)
    existing = {row["account"].strip().lower() for row in get_rows(tracker_id)}

    added: list[dict] = []
    skipped: list[str] = []
    catalogue = valuation.load_catalogue()

    with db.connect() as conn:
        for proposal in proposals:
            account = str(proposal.get("account") or "").strip()
            if not account:
                raise ValueError("Every row needs an account name.")
            if account.lower() in existing:
                skipped.append(account)
                continue

            row = _build_row(tracker_id, account, proposal, catalogue)
            conn.execute(
                """INSERT INTO tracker_rows (id, tracker_id, account, domain, segment, tier,
                        campaign, trigger_text, trigger_source, geography, target_roles,
                        confidence, deal_lines, attach_support, fleet_insight_units,
                        value_est_gbp, value_note, notes, procurement_route, status,
                        next_due, created_at)
                   VALUES (:id, :tracker_id, :account, :domain, :segment, :tier,
                        :campaign, :trigger_text, :trigger_source, :geography, :target_roles,
                        :confidence, :deal_lines, :attach_support, :fleet_insight_units,
                        :value_est_gbp, :value_note, :notes, :procurement_route, :status,
                        :next_due, :created_at)""",
                row,
            )
            existing.add(account.lower())
            added.append(row)

    _touch_tracker(tracker_id)
    return {"added": added, "skipped": skipped}


def _build_row(tracker_id: str, account: str, proposal: dict, catalogue: Optional[dict]) -> dict:
    """One row, validated and priced. Raises with the field that was wrong."""
    tier = proposal.get("tier", 1)
    if tier not in (1, 2, 3):
        raise ValueError(f"{account}: tier must be 1, 2 or 3, not {tier!r}.")

    campaign = str(proposal.get("campaign") or "").strip()
    if campaign and campaign not in CAMPAIGNS:
        raise ValueError(f"{account}: campaign must be one of {', '.join(CAMPAIGNS)}.")

    confidence = str(proposal.get("confidence") or "medium").strip()
    if confidence not in CONFIDENCES:
        raise ValueError(f"{account}: confidence must be one of {', '.join(CONFIDENCES)}.")

    deal = _deal_from(proposal)
    priced = valuation.value(deal, catalogue=catalogue)
    value_gbp, value_note = priced.value_gbp, priced.note

    carried = proposal.get("value_est_gbp")
    if not deal.lines and not deal.fleet_insight_units and isinstance(carried, int):
        # A figure whose composition is not recorded — an imported row whose value
        # was agreed before this module existed. Kept verbatim rather than
        # recomputed, and marked, because a figure nobody can decompose is still a
        # figure somebody committed to. `reprice` leaves these alone.
        value_gbp = carried
        value_note = str(proposal.get("value_note") or "Carried over; composition not recorded.")

    trigger_text = str(proposal.get("trigger_text") or "").strip()
    trigger_source = str(proposal.get("trigger_source") or "").strip()
    if trigger_text and not trigger_source:
        raise ValueError(
            f"{account}: a trigger must say where it came from, so it can be checked."
        )

    return {
        "id": new_id(),
        "tracker_id": tracker_id,
        "account": account,
        "domain": str(proposal.get("domain") or "").strip(),
        "segment": str(proposal.get("segment") or "").strip(),
        "tier": int(tier),
        "campaign": campaign,
        "trigger_text": trigger_text,
        "trigger_source": trigger_source,
        "geography": str(proposal.get("geography") or "").strip(),
        "target_roles": str(proposal.get("target_roles") or "").strip(),
        "confidence": confidence,
        "deal_lines": json.dumps(
            [{"shape": line.shape, "quantity": line.quantity} for line in deal.lines]
        ),
        "attach_support": 1 if deal.attach_support else 0,
        "fleet_insight_units": deal.fleet_insight_units,
        "value_est_gbp": value_gbp,
        "value_note": value_note,
        "notes": str(proposal.get("notes") or "").strip(),
        "procurement_route": str(proposal.get("procurement_route") or "").strip(),
        "status": "not_started",
        "next_due": str(proposal.get("next_due") or "").strip(),
        "created_at": _now(),
    }


def _deal_from(proposal: dict) -> Deal:
    """The deal composition a proposal describes, as the valuation's own types."""
    raw_lines = proposal.get("deal_lines") or []
    lines = []
    for entry in raw_lines:
        if isinstance(entry, Line):
            lines.append(entry)
        elif isinstance(entry, dict):
            lines.append(Line(str(entry.get("shape") or ""), entry.get("quantity", 1)))
        else:
            raise ValueError(f"A deal line must name a shape and a quantity, not {entry!r}.")
    return Deal(
        lines=tuple(lines),
        attach_support=bool(proposal.get("attach_support")),
        fleet_insight_units=int(proposal.get("fleet_insight_units") or 0),
    )


def get_rows(tracker_id: str) -> list[dict]:
    """Every account on a tracker, each with its touch state read from the trail."""
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM tracker_rows WHERE tracker_id = ? ORDER BY tier, account",
            (tracker_id,),
        )]
        events = [dict(e) for e in conn.execute(
            """SELECT e.* FROM tracker_events e
               JOIN tracker_rows r ON r.id = e.row_id
               WHERE r.tracker_id = ? ORDER BY e.at""",
            (tracker_id,),
        )]

    by_row: dict[str, list[dict]] = {}
    for event in events:
        by_row.setdefault(event["row_id"], []).append(event)

    for row in rows:
        row["deal_lines"] = json.loads(row["deal_lines"] or "[]")
        row["attach_support"] = bool(row["attach_support"])
        row["touches"] = _touches_from(by_row.get(row["id"], []))
        row["history"] = by_row.get(row["id"], [])
    return rows


def get_row(row_id: str) -> Optional[dict]:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM tracker_rows WHERE id = ?", (row_id,)).fetchone()
        if not row:
            return None
        events = [dict(e) for e in conn.execute(
            "SELECT * FROM tracker_events WHERE row_id = ? ORDER BY at", (row_id,)
        )]
    record = dict(row)
    record["deal_lines"] = json.loads(record["deal_lines"] or "[]")
    record["attach_support"] = bool(record["attach_support"])
    record["touches"] = _touches_from(events)
    record["history"] = events
    return record


def _touches_from(events: list[dict]) -> list[dict]:
    """The five touches, each either fired (with its date) or not.

    The last event for a touch wins, which is what makes clearing one possible
    without deleting the fact that it was fired.
    """
    latest: dict[int, dict] = {}
    for event in events:
        if event["kind"] != "touch" or event["touch_index"] is None:
            continue
        latest[int(event["touch_index"])] = event

    state = []
    for index, label in TOUCHES:
        event = latest.get(index)
        fired = bool(event and event["to_value"] == "fired")
        state.append({
            "index": index,
            "label": label,
            "fired": fired,
            "at": event["at"] if (event and fired) else "",
            "actor": event["actor"] if (event and fired) else "",
        })
    return state


# ---------------------------------------------------------------------------
# What has happened
# ---------------------------------------------------------------------------

def fire_touch(row_id: str, index: int, actor: str, *, fired: bool = True, source: str = "") -> dict:
    """Record that a touch was sent, or retract one that was not.

    Firing the first touch on an untouched account moves it into ``sequencing``:
    the one automatic transition, because an account being worked and an account
    nobody has started are different rows on the list and nobody should have to
    say so twice.
    """
    row = _require_row(row_id)
    if index not in {i for i, _ in TOUCHES}:
        raise ValueError(f"There are {TOUCH_COUNT} touches; {index} is not one of them.")

    current = next(t for t in row["touches"] if t["index"] == index)
    if current["fired"] == fired:
        raise ValueError(
            f"Touch {index} on {row['account']} is already "
            + ("recorded as sent." if fired else "not recorded as sent.")
        )

    _append_event(
        row_id,
        kind="touch",
        touch_index=index,
        from_value="fired" if current["fired"] else "not_fired",
        to_value="fired" if fired else "not_fired",
        actor=actor,
        source=source,
    )

    if fired and row["status"] == "not_started":
        set_status(row_id, "sequencing", actor, source="first touch fired")

    _touch_tracker(row["tracker_id"])
    return get_row(row_id)


def set_status(row_id: str, status: str, actor: str, *, source: str = "") -> dict:
    """Move an account's status, keeping the move.

    Any known status may be set from any other. See the module docstring: the
    guard is the vocabulary and the trail, not a transition table.
    """
    row = _require_row(row_id)
    status = (status or "").strip()
    if status not in STATUSES:
        raise ValueError(f"'{status}' is not a status. Use one of: {', '.join(STATUSES)}.")
    if status == row["status"]:
        raise ValueError(f"{row['account']} is already {status}.")

    _append_event(
        row_id,
        kind="status",
        touch_index=None,
        from_value=row["status"],
        to_value=status,
        actor=actor,
        source=source,
    )
    with db.connect() as conn:
        conn.execute("UPDATE tracker_rows SET status = ? WHERE id = ?", (status, row_id))

    _touch_tracker(row["tracker_id"])
    return get_row(row_id)


#: What a person may edit on a row after it lands. Everything else came from the
#: agent and is changed by re-proposing, not by typing over it.
EDITABLE = ("next_due", "procurement_route", "notes", "trigger_text", "trigger_source")


def update_row(row_id: str, changes: dict, actor: str) -> dict:
    """Edit the fields a person owns, recording each change."""
    row = _require_row(row_id)
    unknown = set(changes) - set(EDITABLE)
    if unknown:
        raise ValueError(
            f"{', '.join(sorted(unknown))} cannot be edited here. Editable: {', '.join(EDITABLE)}."
        )

    for field, new in changes.items():
        new = str(new or "").strip()
        if new == row[field]:
            continue
        _append_event(
            row_id, kind="edit", touch_index=None,
            from_value=f"{field}={row[field]}", to_value=f"{field}={new}", actor=actor,
        )
        with db.connect() as conn:
            # `field` is interpolated because a column name cannot be bound, and it
            # is safe to do so only because it was checked against EDITABLE above.
            conn.execute(f"UPDATE tracker_rows SET {field} = ? WHERE id = ?", (new, row_id))

    _touch_tracker(row["tracker_id"])
    return get_row(row_id)


def reprice(tracker_id: str) -> dict:
    """Re-run the valuation over a tracker, e.g. after the catalogue changes.

    Every change is recorded, because a figure moving without a trace is how a
    forecast quietly becomes unaccountable.
    """
    catalogue = valuation.load_catalogue()
    changed = 0
    for row in get_rows(tracker_id):
        if not row["deal_lines"] and not row["fleet_insight_units"]:
            # A carried-over figure has no composition to recompute from. Repricing
            # it would replace an agreed number with `None`, which is worse than
            # leaving it visibly un-decomposed.
            continue
        deal = _deal_from({
            "deal_lines": row["deal_lines"],
            "attach_support": row["attach_support"],
            "fleet_insight_units": row["fleet_insight_units"],
        })
        priced = valuation.value(deal, catalogue=catalogue)
        if priced.value_gbp == row["value_est_gbp"]:
            continue
        _append_event(
            row["id"], kind="value", touch_index=None,
            from_value=str(row["value_est_gbp"]), to_value=str(priced.value_gbp),
            actor="system", source="reprice",
        )
        with db.connect() as conn:
            conn.execute(
                "UPDATE tracker_rows SET value_est_gbp = ?, value_note = ? WHERE id = ?",
                (priced.value_gbp, priced.note, row["id"]),
            )
        changed += 1
    _touch_tracker(tracker_id)
    return {"repriced": changed}


def _append_event(
    row_id: str, *, kind: str, touch_index: Optional[int],
    from_value: str, to_value: str, actor: str, source: str = "",
) -> None:
    with db.connect() as conn:
        conn.execute(
            """INSERT INTO tracker_events (id, row_id, kind, touch_index, from_value,
                                           to_value, actor, source, at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (new_id(), row_id, kind, touch_index, from_value, to_value, actor, source, _now()),
        )


# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------

def counters(tracker_id: str) -> dict:
    """What the tracker's header reports, against the goals it was created with.

    ``unpriced`` is reported alongside ``total_value_gbp`` rather than folded into
    it, because a total that silently omits rows reads as complete when it is not.

    ``uncomposed`` is the quieter version of the same problem and the one this
    list actually has: a row whose figure was agreed before there was a catalogue
    to derive it from. It counts in the total and cannot be repriced, so it is
    reported rather than left to look like every other row.
    """
    tracker = _require_tracker(tracker_id)
    rows = get_rows(tracker_id)

    touches = sum(1 for row in rows for touch in row["touches"] if touch["fired"])
    in_sequence = sum(1 for row in rows if any(t["fired"] for t in row["touches"]))
    replies = sum(1 for row in rows if row["status"] in REPLIED_STATUSES)
    calls = sum(1 for row in rows if row["status"] in CALL_STATUSES)
    qualified = [row for row in rows if row["status"] == "qualified"]

    priced = [row["value_est_gbp"] for row in rows if row["value_est_gbp"] is not None]

    # A figure carried over from the hand-built list, with no composition behind
    # it. Distinct from `unpriced`: these rows *have* a number, so they land in
    # the total — but they cannot be repriced when the catalogue moves, and that
    # is a different problem from having no figure at all.
    uncomposed = [
        row for row in rows
        if row["value_est_gbp"] is not None
        and not row["deal_lines"] and not row["fleet_insight_units"]
    ]

    return {
        "targets": len(rows),
        "touches": touches,
        "target_touches": tracker["target_touches"],
        "in_sequence": in_sequence,
        "replies": replies,
        "target_replies": tracker["target_replies"],
        "calls": calls,
        "target_calls": tracker["target_calls"],
        "qualified": len(qualified),
        "target_qualified": tracker["target_qualified"],
        "qualified_value_gbp": sum(r["value_est_gbp"] or 0 for r in qualified),
        "total_value_gbp": sum(priced),
        "unpriced": len(rows) - len(priced),
        "uncomposed": len(uncomposed),
        "goal_gbp": tracker["goal_gbp"],
    }


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

def _require_tracker(tracker_id: str) -> dict:
    tracker = get_tracker(tracker_id)
    if not tracker:
        raise ValueError("No such tracker")
    return tracker


def _require_row(row_id: str) -> dict:
    row = get_row(row_id)
    if not row:
        raise ValueError("No such account on any tracker")
    return row


def _touch_tracker(tracker_id: str) -> None:
    with db.connect() as conn:
        conn.execute("UPDATE trackers SET updated_at = ? WHERE id = ?", (_now(), tracker_id))
