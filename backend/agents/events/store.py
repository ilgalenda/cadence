"""The events record: what is stored, and the rules that guard it.

Business rules live here rather than in the routes, so the same rule holds
whether a request arrived from the page, a test, or a later caller nobody has
written yet. The store raises ``ValueError``; the router turns that into a 400.
That is the pattern `agents/sales/signals` already ships.

Two rules are worth naming because they shape everything else:

  * **A show is a series, an edition is a year.** Registering interest in
    "IBC 2027" when IBC 2027 already exists joins that record instead of forking
    it. The unique index on (series, year) makes forking impossible rather than
    merely discouraged.
  * **Approval raises the checklist.** Nothing is owed by a proposal, because
    proposals get declined. The moment an edition is approved — or a person's
    place on it is — the lines that show or that person needs appear with real
    deadlines, from `checklist.CHECKLIST`, which is the playbook's own timeline.
"""
from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

from . import checklist, requirements
from .db import connect

#: Where an edition stands. `attended` is a terminal state kept deliberately —
#: an event we went to is the evidence for going again, and next year's clone
#: reads from it.
EVENT_STATUSES = ("proposed", "approved", "declined", "attended")

#: Where a person's place stands. Same gate, one level down.
REGISTRATION_STATUSES = ("proposed", "approved", "declined")

#: What somebody is going to do there. It decides which checklist lines a show
#: gets: a presenter needs a banner behind them, an attendee does not.
INTENTS = ("attending", "presenting", "exhibiting")


def new_id() -> str:
    return uuid.uuid4().hex


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _parse_date(value: Any, field: str) -> date:
    """An ISO ``YYYY-MM-DD`` date, or a ``ValueError`` naming the field.

    The message is shown to the person who typed it — `signals.astro` renders
    `detail` verbatim — so it says which field and what shape, not "invalid".
    """
    if not value:
        raise ValueError(f"{field} is required, as YYYY-MM-DD")
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        raise ValueError(f"{field} must be a date in the form YYYY-MM-DD")


#: The longest any single free-text answer may be. Generous for a sentence and
#: nowhere near a pasted document — which is the case worth stopping, because a
#: spreadsheet cell holds 50,000 characters and a row that exceeds one takes the
#: whole push down for every show, not just its own.
MAX_TEXT = 2000


def _clean(value: Any) -> str:
    """Trimmed, and bounded. Every free-text answer on this form goes through here."""
    return str(value or "").strip()[:MAX_TEXT]


def _series_key(name: str) -> str:
    """A show's name reduced to what makes it the same show.

    "Northgate Expo 2026", "ibc", "IBC  —  Amsterdam" all key to `ibc`, so the year a
    person types into the event name does not create a second series. Digits go
    with it: a year in the title is an edition, never an identity.
    """
    stripped = re.sub(r"\b(19|20)\d{2}\b", " ", name.lower())
    return re.sub(r"[^a-z]+", " ", stripped).strip()


def _row(row: Optional[sqlite3.Row]) -> Optional[dict]:
    return dict(row) if row is not None else None


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

#: What a non-admin may see: a show they are on, that has not been declined.
#:
#: Written as a clause the query carries rather than a filter applied to the
#: results, because those are different guarantees — `store/signals.py` puts it
#: exactly: *"the username is part of the lookup rather than a check afterwards,
#: so no path can return another person's record."*
#:
#: "On it" is a registration that is not declined, which covers both halves of
#: what Sam asked for: shows they are confirmed for, and their own proposals
#: still waiting on a decision.
_MINE = """EXISTS (
  SELECT 1 FROM registrations r
  WHERE r.event_id = events.id AND r.username = ? AND r.status != 'declined'
) AND events.status != 'declined'"""


#: Statuses a show can be ready *in*. A show that was said no to has nothing to
#: be ready for, and calling it ready is how a dead row ends up looking live.
LIVE_STATUSES = ("proposed", "approved", "attended")


def _progress(conn: sqlite3.Connection, event_id: str, total: int,
              status: str = "approved") -> dict:
    """How far along a show is, as the spreadsheet last reported it.

    Cadence raises the lines and knows when each is owed; **whether one is done
    lives in the sheet**, where the people doing the work are. So this reads the
    cached answer rather than computing one — Sam's split: *"no need for Cadence
    to track all the steps. Only thing Cadence should show is when everything is
    approved and everything is ready."*

    A show nobody has synced yet reports its whole checklist outstanding, which
    is true: nothing has been reported done.
    """
    cached = conn.execute(
        "SELECT outstanding, next_due, checked_at FROM sheet_state WHERE event_id = ?",
        (event_id,),
    ).fetchone()
    outstanding = cached["outstanding"] if cached else total

    # The date is Cadence's own even before the sheet has reported: it raised the
    # lines and computed every deadline. Only *which* remain is the sheet's to
    # say, so an unsynced show still shows the earliest thing it owes.
    next_due = cached["next_due"] if cached and cached["next_due"] else conn.execute(
        "SELECT MIN(due_on) FROM checklist_items WHERE event_id = ?", (event_id,)
    ).fetchone()[0]

    return {
        "checklist_total": total,
        "outstanding": outstanding,
        "ready": status in LIVE_STATUSES and total > 0 and outstanding == 0,
        "next_due": next_due,
        "checked_at": cached["checked_at"] if cached else None,
    }


def list_events(
    *,
    year: Optional[int] = None,
    status: Optional[str] = None,
    today: Optional[date] = None,
    username: Optional[str] = None,
) -> list[dict]:
    """Every live edition in date order, each carrying how far along it is.

    ``username`` narrows the calendar to that person's own shows; ``None`` — the
    admin — sees all of them. See :data:`_MINE`.

    Readiness is computed here rather than stored: a row written as "breached"
    is wrong the next morning, and there is no scheduler to correct it.
    """
    today = today or _today()
    clauses = ["deleted_at IS NULL"]
    params: list[Any] = []
    if username is not None:
        clauses.append(_MINE)
        params.append(username)
    if year is not None:
        clauses.append("year = ?")
        params.append(year)
    if status is not None:
        if status not in EVENT_STATUSES:
            raise ValueError(f"Unknown status '{status}'")
        clauses.append("status = ?")
        params.append(status)

    sql = f"SELECT * FROM events WHERE {' AND '.join(clauses)} ORDER BY starts_on"
    with connect() as conn:
        events = [dict(r) for r in conn.execute(sql, params)]
        for event in events:
            start = date.fromisoformat(event["starts_on"])
            total = conn.execute(
                "SELECT COUNT(*) FROM checklist_items WHERE event_id = ?",
                (event["id"],),
            ).fetchone()[0]
            event.update(_progress(conn, event["id"], total, event["status"]))
            event["days_until"] = (start - today).days
            event["days_to_decide"] = (
                (date.fromisoformat(event["decide_by"]) - today).days
                if event["decide_by"] else None
            )
            event["attendee_count"] = conn.execute(
                "SELECT COUNT(*) FROM registrations WHERE event_id = ? AND status != 'declined'",
                (event["id"],),
            ).fetchone()[0]
    return events


def get_event(
    event_id: str, *, today: Optional[date] = None, username: Optional[str] = None
) -> dict:
    """One edition with its people and its checklist.

    ``username`` applies the same scope the list does. A show that person is not
    on raises **"No such event"** rather than a distinct refusal, so the route
    cannot be used to discover which shows exist — the id is the only thing an
    outsider would have, and an id that answers differently is an answer.
    """
    today = today or _today()
    sql = "SELECT * FROM events WHERE id = ? AND deleted_at IS NULL"
    params: list[Any] = [event_id]
    if username is not None:
        sql += f" AND {_MINE}"
        params.append(username)

    with connect() as conn:
        event = _row(conn.execute(sql, params).fetchone())
        if event is None:
            raise ValueError("No such event")

        start = date.fromisoformat(event["starts_on"])
        registrations = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM registrations WHERE event_id = ? ORDER BY created_at",
                (event_id,),
            )
        ]
        items = [dict(r) for r in conn.execute(
            "SELECT * FROM checklist_items WHERE event_id = ?"
            " ORDER BY due_on, phase, item", (event_id,)
        )]

    event["days_until"] = (start - today).days
    event["days_to_decide"] = (
        (date.fromisoformat(event["decide_by"]) - today).days if event["decide_by"] else None
    )
    event["registrations"] = registrations
    event["checklist"] = items
    with connect() as conn:
        event.update(_progress(conn, event_id, len(items), event["status"]))
    return event


def _iso_date(value: str) -> str:
    """`value` if it is a plain ISO date, else empty.

    A spreadsheet hands back whatever the cell is formatted as, and these dates
    are compared and ordered as text everywhere they are used.
    """
    try:
        return date.fromisoformat((value or "").strip()).isoformat()
    except ValueError:
        return ""


def _named_show(live: list, name: str, starts_on: str = ""):
    """The one live show a hand-typed row means, or `None`.

    The spreadsheet writes the show's **name** and its **start date** in
    separate columns and does not repeat the year, so two editions of one show
    read identically by name alone. The date is what tells them apart.

    Ambiguity is refused rather than resolved. A line put on the wrong year is
    work on the wrong calendar and nothing would ever say so; a line left
    unadopted sits in the sheet where somebody can see it and fix it.
    """
    name = (name or "").strip()
    if not name:
        return None

    matches = [row for row in live if row["name"] == name]
    if starts_on.strip():
        dated = [row for row in matches if row["starts_on"] == starts_on.strip()]
        if dated:
            matches = dated

    return matches[0] if len(matches) == 1 else None


def adopt_lines(added: list) -> tuple:
    """Take on lines somebody typed into the spreadsheet.

    Returns ``(adopted, duplicates)`` — rows that were given an id, and rows the
    caller should **remove from the sheet** because the line was already there.

    The sheet became a place where work is *defined* as well as progressed, and
    this is the join: a row with an item but no id is given one, stored like any
    other line, and counted from then on. The caller writes the ids it gets back
    into column A, which is what stops the same row being adopted twice.

    **Matched on the show's name**, which carries its year — "Northgate Expo 2026" — so it
    is unique among live shows. A row naming a show that is not there is left
    alone rather than guessed at: an orphan line is somebody's typo, and
    attaching it to the wrong show would put work on the wrong calendar.
    """
    if not added:
        return {}, []

    stamp = _now()
    adopted: dict = {}
    duplicates: list = []

    with connect() as conn:
        live = conn.execute(
            "SELECT id, name, starts_on FROM events"
            " WHERE deleted_at IS NULL AND status != 'declined'"
        ).fetchall()

        for line in added:
            show = _named_show(live, line["show"], line.get("starts_on", ""))
            if show is None:
                continue

            item = line["item"].strip()[:200]
            if not item:
                continue

            # Idempotent on (show, item), the same key the seeding uses. The id
            # written back into the sheet is what marks a row as adopted, and
            # that write is a network call which can fail. Without this, the
            # next pass would adopt the row again and the show would owe the
            # same job twice — with nothing to say which of the two was real.
            already = conn.execute(
                "SELECT id FROM checklist_items"
                " WHERE event_id = ? AND item = ? AND registration_id IS NULL",
                (show["id"], item),
            ).fetchone()
            if already:
                # The line is already on the list, on its own row with its own
                # id. Stamping that id into this row too would leave two rows
                # claiming to be one line — `_upsert_all` keeps only the last it
                # sees, so the other would go stale and could never be updated
                # again. The row is a duplicate; the caller removes it.
                duplicates.append(line["row"])
                continue

            line_id = new_id()
            # `registration_id` NULL: a line added by hand belongs to the show.
            # Nothing in the tab says whose it is, and guessing would put
            # somebody's name on work they never asked for.
            conn.execute(
                "INSERT INTO checklist_items"
                " (id, event_id, registration_id, phase, item, owner, due_on, created_at)"
                " VALUES (?, ?, NULL, ?, ?, ?, ?, ?)",
                (line_id, show["id"],
                 _clean(line["phase"]) or checklist.PHASES[0],
                 item,
                 _clean(line["owner"]) or checklist.SAM,
                 # No usable date means it is owed when the show opens, which is
                 # the latest it could possibly be useful. Anything that is not
                 # a plain ISO date is treated as no date: these are compared
                 # and sorted as strings against ISO ones, so "28/08/2026" would
                 # not merely look wrong, it would order wrongly and be reported
                 # as the next deadline.
                 _iso_date(line["due_on"]) or show["starts_on"],
                 stamp),
            )
            adopted[line["row"]] = line_id

    return adopted, duplicates


def record_progress(done_ids: set) -> int:
    """Store what the sheet reported, per show. Returns how many shows changed.

    Cadence keeps the lines and their dates; the sheet keeps whether each is
    done. This is the join between them, and it is cached because the calendar
    renders on every page load and the sheet is a network call.
    """
    stamp = _now()
    with connect() as conn:
        # Live shows only. Both clauses matter and for the same reason: a
        # retired show's lines are taken out of the sheet, so the sheet can
        # never report them done, and counting them here would leave a number
        # outstanding that nobody is able to bring down.
        rows = conn.execute(
            "SELECT c.event_id, c.id, c.due_on FROM checklist_items c"
            " JOIN events e ON e.id = c.event_id"
            f" WHERE e.deleted_at IS NULL AND e.status != 'declined'"
        ).fetchall()

        by_event: dict[str, dict] = {}
        for row in rows:
            bucket = by_event.setdefault(row["event_id"], {"outstanding": 0, "next_due": None})
            if row["id"] in done_ids:
                continue
            bucket["outstanding"] += 1
            if bucket["next_due"] is None or row["due_on"] < bucket["next_due"]:
                bucket["next_due"] = row["due_on"]

        for event_id, state in by_event.items():
            conn.execute(
                "INSERT INTO sheet_state (event_id, outstanding, next_due, checked_at)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(event_id) DO UPDATE SET"
                " outstanding = excluded.outstanding, next_due = excluded.next_due,"
                " checked_at = excluded.checked_at",
                (event_id, state["outstanding"], state["next_due"], stamp),
            )

        # A retired show's cached count would otherwise sit here for ever: the
        # foreign key cascades on a real delete, and this table's shows are only
        # ever soft-deleted.
        conn.execute(
            "DELETE FROM sheet_state WHERE event_id NOT IN"
            " (SELECT id FROM events WHERE deleted_at IS NULL AND status != 'declined')"
        )
    return len(by_event)


def years() -> list[int]:
    """Every year that has an edition, newest first — the table's selector."""
    with connect() as conn:
        return [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT year FROM events WHERE deleted_at IS NULL ORDER BY year DESC"
            )
        ]


# ---------------------------------------------------------------------------
# Registering interest
# ---------------------------------------------------------------------------

#: The shortest answer to "why we should go" that is actually an answer. A one-word
#: field is a field somebody has learned to skip, and the approver gains nothing.
MIN_RATIONALE = 20


def _personal(payload: dict) -> dict:
    """The part of the form that is about the person, validated.

    Asked of everybody, whether they are proposing a show or joining one already
    on the calendar.
    """
    intent = _clean(payload.get("intent")) or "attending"
    if intent not in INTENTS:
        raise ValueError(f"Going as must be one of: {', '.join(INTENTS)}")

    raw_ticket = payload.get("ticket_cost")
    if raw_ticket in (None, ""):
        # Required rather than optional: "unknown" and "free" look identical in a
        # blank field, and they are different facts to somebody approving a cost.
        raise ValueError("Ticket cost is required. Put 0 if the event is free.")
    try:
        ticket_cost = float(raw_ticket)
    except (TypeError, ValueError):
        raise ValueError("Ticket cost must be a number")
    if ticket_cost < 0:
        raise ValueError("Ticket cost cannot be negative")

    # What they asked for. Both blocks are kept only when the tick above them is
    # on: somebody who ticks material, chooses cards, then unticks it has changed
    # their mind, and storing the choice anyway would order the cards.
    needs_material = 1 if payload.get("needs_material") else 0
    material_items = requirements.clean_material(payload.get("material_items")) \
        if needs_material else []
    if needs_material and not material_items:
        raise ValueError("Tell us what material you need, or untick the box.")

    material_note = _clean(payload.get("material_note")) if needs_material else ""
    if requirements.OTHER in material_items and not material_note:
        raise ValueError("You chose 'something else' — say what you need.")

    needs_travel = 1 if payload.get("needs_travel") else 0
    travel_legs = requirements.clean_legs(payload.get("travel_legs")) \
        if needs_travel else []
    if needs_travel and not travel_legs:
        raise ValueError("Add at least one travel arrangement, or untick the box.")

    return {
        "intent": intent,
        "ticket_cost": ticket_cost,
        "ticket_currency": _clean(payload.get("ticket_currency")) or "GBP",
        "needs_travel": needs_travel,
        "travel_note": _clean(payload.get("travel_note")) if needs_travel else "",
        "travel_legs": requirements.dump(travel_legs),
        "needs_material": needs_material,
        "material_items": requirements.dump(material_items),
        "material_note": material_note,
        "note": _clean(payload.get("note")),
    }


def _show(payload: dict) -> dict:
    """The part of the form that describes the show itself, validated.

    Asked only when a new edition is being proposed. Everything here is required,
    **conditionally** — a stand cost is required if we are exhibiting and
    meaningless if we are not, and demanding one from somebody attending a
    conference would block a valid registration. That is the opposite of making
    the approval easier, which is what this block exists for.
    """
    name = _clean(payload.get("name"))
    if not name:
        raise ValueError("The event needs a name.")

    location = _clean(payload.get("location"))
    if not location:
        raise ValueError("Say where it is held.")
    country = _clean(payload.get("country"))
    if not country:
        raise ValueError("Say which country.")

    starts_on = _parse_date(payload.get("starts_on"), "Start date")
    ends_on = _parse_date(payload.get("ends_on") or payload.get("starts_on"), "End date")
    if ends_on < starts_on:
        raise ValueError("The end date cannot be before the start date.")

    show = {
        "name": name,
        "location": location,
        "country": country,
        "starts_on": starts_on,
        "ends_on": ends_on,
        "website": _clean(payload.get("website")),
        "invited": 1 if payload.get("invited") else 0,
        "exhibiting": 1 if payload.get("exhibiting") else 0,
        "demo_required": 1 if payload.get("demo_required") else 0,
        "demo_type": "",
        "submission_deadline": None,
        "submission_note": _clean(payload.get("submission_note")),
        "exhibit_cost": None,
        "exhibit_currency": _clean(payload.get("exhibit_currency")) or "GBP",
        "quote_contact_name": "",
        "quote_contact_email": "",
    }

    if show["exhibiting"]:
        raw_cost = payload.get("exhibit_cost")
        if raw_cost in (None, ""):
            raise ValueError("Stand cost is required when we are exhibiting. Put 0 if it is free.")
        show["exhibit_cost"] = _coerce("Stand cost", "money", raw_cost)
        show["quote_contact_name"] = _clean(payload.get("quote_contact_name"))
        show["quote_contact_email"] = _clean(payload.get("quote_contact_email"))
        if not show["quote_contact_email"]:
            raise ValueError("A quote contact email is required when we are exhibiting.")
        if "@" not in show["quote_contact_email"]:
            raise ValueError("That does not look like an email address.")

    if show["demo_required"]:
        show["demo_type"] = _clean(payload.get("demo_type"))
        if not show["demo_type"]:
            raise ValueError("Say what kind of demo is needed.")

    if payload.get("has_submission_deadline"):
        deadline = _parse_date(payload.get("submission_deadline"), "Submission deadline")
        if deadline > starts_on:
            raise ValueError("The submission deadline cannot be after the event starts.")
        show["submission_deadline"] = deadline.isoformat()

    rationale = _clean(payload.get("rationale"))
    if len(rationale) < MIN_RATIONALE:
        raise ValueError(
            "Say why we should go — who we would meet and what we would say. "
            f"At least {MIN_RATIONALE} characters."
        )
    show["rationale"] = rationale

    decide_by = _parse_date(payload.get("decide_by"), "Decide-by date")
    if decide_by > starts_on:
        # A decision taken after the show has started is not a decision.
        raise ValueError("The decide-by date cannot be after the event starts.")
    show["decide_by"] = decide_by.isoformat()

    return show


def register_interest(username: str, payload: dict) -> dict:
    """Record that somebody wants to go.

    Two ways in, and they ask for different things:

      * **Joining** an edition already on the calendar (``event_id`` given) asks
        only about the person. The show has already been described and asking a
        second person to describe it again invites two different answers.
      * **Proposing** a new edition asks the whole form — the show's
        requirements and the case for going — because the point of the form is
        that whoever approves it does not then have to go and find them.

    Proposing something that turns out to already exist joins it instead of
    failing, and says so: the unique index on (series, year) means a fork is not
    possible, and an error there would be a worse answer than the truth.
    """
    personal = _personal(payload)
    joining = bool(_clean(payload.get("event_id")))
    show = None if joining else _show(payload)

    stamp = _now()
    with connect() as conn:
        if joining:
            event_id = _clean(payload["event_id"])
            if conn.execute(
                "SELECT 1 FROM events WHERE id = ? AND deleted_at IS NULL", (event_id,)
            ).fetchone() is None:
                raise ValueError("That show is no longer on the calendar.")
            joined_existing = True
        else:
            event_id, joined_existing = _find_or_create_event(
                conn, show, username=username, stamp=stamp
            )

        if conn.execute(
            "SELECT 1 FROM registrations WHERE event_id = ? AND username = ?",
            (event_id, username),
        ).fetchone() is not None:
            raise ValueError("You have already registered interest in this show.")

        conn.execute(
            """
            INSERT INTO registrations (
              id, event_id, username, intent, needs_travel, travel_note,
              travel_legs, needs_material, material_items, material_note,
              ticket_cost, ticket_currency, note, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'proposed', ?, ?)
            """,
            (
                new_id(),
                event_id,
                username,
                personal["intent"],
                personal["needs_travel"],
                personal["travel_note"],
                personal["travel_legs"],
                personal["needs_material"],
                personal["material_items"],
                personal["material_note"],
                personal["ticket_cost"],
                personal["ticket_currency"],
                personal["note"],
                stamp,
                stamp,
            ),
        )

    event = get_event(event_id)
    event["joined_existing"] = joined_existing
    return event


def _find_or_create_event(
    conn: sqlite3.Connection, show: dict, *, username: str, stamp: str
) -> tuple[str, bool]:
    """The edition this proposal belongs to, creating it if it is genuinely new.

    Returns the id and whether an existing edition was joined rather than made,
    so the surface can say *"Northgate Expo 2026 was already on the calendar"* instead of
    silently discarding everything the person typed about the show.
    """
    key = _series_key(show["name"])
    if not key:
        raise ValueError("The event name needs some letters in it.")

    series = _row(
        conn.execute("SELECT * FROM event_series WHERE name = ?", (key,)).fetchone()
    )
    if series is None:
        series_id = new_id()
        conn.execute(
            "INSERT INTO event_series (id, name, organiser, note, created_at)"
            " VALUES (?, ?, '', ?, ?)",
            (series_id, key, show["name"], stamp),
        )
    else:
        series_id = series["id"]

    year = show["starts_on"].year
    existing = conn.execute(
        "SELECT id FROM events WHERE series_id = ? AND year = ? AND deleted_at IS NULL",
        (series_id, year),
    ).fetchone()
    if existing is not None:
        return existing["id"], True

    event_id = new_id()
    conn.execute(
        """
        INSERT INTO events (
          id, series_id, name, year, location, country, starts_on, ends_on,
          website, status, invited, exhibiting, demo_required, demo_type,
          submission_deadline, submission_note, exhibit_cost, exhibit_currency,
          quote_contact_name, quote_contact_email, rationale, decide_by,
          created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'proposed', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            series_id,
            show["name"],
            year,
            show["location"],
            show["country"],
            show["starts_on"].isoformat(),
            show["ends_on"].isoformat(),
            show["website"],
            show["invited"],
            show["exhibiting"],
            show["demo_required"],
            show["demo_type"],
            show["submission_deadline"],
            show["submission_note"],
            show["exhibit_cost"],
            show["exhibit_currency"],
            show["quote_contact_name"],
            show["quote_contact_email"],
            show["rationale"],
            show["decide_by"],
            username,
            stamp,
            stamp,
        ),
    )
    return event_id, False


# ---------------------------------------------------------------------------
# The approval gate
# ---------------------------------------------------------------------------

def _checklist_subject(conn: sqlite3.Connection, event_id: str) -> Optional[dict]:
    """The show and its people, read on the caller's own connection.

    `get_event` would open a second one, which cannot see the UPDATE the caller
    has not committed yet — so a registration just approved still reads as
    proposed and its lines are never raised. The seeding has to look at the
    transaction it is part of.
    """
    event = _row(conn.execute(
        "SELECT * FROM events WHERE id = ? AND deleted_at IS NULL", (event_id,)
    ).fetchone())
    if event is None:
        return None
    event["registrations"] = [dict(r) for r in conn.execute(
        "SELECT * FROM registrations WHERE event_id = ?", (event_id,)
    )]
    return event


def _seed_checklist(conn: sqlite3.Connection, event: dict) -> None:
    """Raise everything this show needs doing, from the playbook's own list.

    Idempotent by (event, item, person): approving twice, or approving a second
    person, adds what is missing and leaves what is there. Nothing is ever
    removed — a line raised against a show that later stops exhibiting is a line
    somebody may already have acted on.

    **A line that is already there has its date corrected.** Every deadline is
    the show's start minus a lead time, so moving the show moves all of them.
    Left alone, a show pushed back a fortnight kept telling Jo to order business
    cards against the date it used to open — a deadline that no longer exists,
    on the one document three teams work from.
    """
    starts_on = date.fromisoformat(event["starts_on"])
    stamp = _now()

    for item, registration in checklist.for_event(event):
        registration_id = registration["id"] if registration else None
        due_on = checklist.due_on(starts_on, item).isoformat()
        already = conn.execute(
            "SELECT id, due_on FROM checklist_items WHERE event_id = ? AND item = ?"
            " AND registration_id IS ?",
            (event["id"], item.item, registration_id),
        ).fetchone()
        if already:
            if already["due_on"] != due_on:
                conn.execute(
                    "UPDATE checklist_items SET due_on = ? WHERE id = ?",
                    (due_on, already["id"]),
                )
            continue
        conn.execute(
            "INSERT INTO checklist_items"
            " (id, event_id, registration_id, phase, item, owner, due_on, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id(), event["id"], registration_id, item.phase, item.item,
             item.owner, due_on, stamp),
        )


def decide_event(event_id: str, *, status: str, admin: str, note: str = "") -> dict:
    """Approve or decline an edition, and raise its checklist on approval.

    Declining is recorded rather than deleted. Why Acme said no to a show is
    worth as much next year as why it said yes.
    """
    if status not in ("approved", "declined", "attended"):
        raise ValueError("An event can be approved, declined or marked attended")

    stamp = _now()
    with connect() as conn:
        event = _row(
            conn.execute(
                "SELECT * FROM events WHERE id = ? AND deleted_at IS NULL", (event_id,)
            ).fetchone()
        )
        if event is None:
            raise ValueError("No such event")

        conn.execute(
            "UPDATE events SET status = ?, decision_note = ?, decided_by = ?,"
            " decided_at = ?, updated_at = ? WHERE id = ?",
            (status, _clean(note), admin, stamp, stamp, event_id),
        )
        if status == "approved":
            event["status"] = status
            subject = _checklist_subject(conn, event_id)
            if subject:
                _seed_checklist(conn, subject)

    return get_event(event_id)


def decide_registration(
    registration_id: str, *, status: str, admin: str
) -> dict:
    """Approve or decline one person's place, raising their own lines on approval."""
    if status not in ("approved", "declined"):
        raise ValueError("A registration can be approved or declined")

    stamp = _now()
    with connect() as conn:
        reg = _row(
            conn.execute(
                "SELECT * FROM registrations WHERE id = ?", (registration_id,)
            ).fetchone()
        )
        if reg is None:
            raise ValueError("No such registration")

        conn.execute(
            "UPDATE registrations SET status = ?, decided_by = ?, decided_at = ?,"
            " updated_at = ? WHERE id = ?",
            (status, admin, stamp, stamp, registration_id),
        )
        if status == "approved":
            subject = _checklist_subject(conn, reg["event_id"])
            if subject:
                _seed_checklist(conn, subject)

    return get_event(reg["event_id"])


# ---------------------------------------------------------------------------
# The show requirements block
# ---------------------------------------------------------------------------

#: Fields the requirements form owns, and how each is coerced. Declared rather
#: than branched so an added field is one line, not a new `elif`.
_EVENT_FIELDS: dict[str, str] = {
    "name": "text",
    "location": "text",
    "country": "text",
    "website": "text",
    "starts_on": "date",
    "ends_on": "date",
    "invited": "bool",
    "exhibiting": "bool",
    "demo_required": "bool",
    "demo_type": "text",
    "submission_deadline": "optional_date",
    "submission_note": "text",
    "exhibit_cost": "money",
    "exhibit_currency": "text",
    "quote_contact_name": "text",
    "quote_contact_email": "text",
}


def _coerce(field: str, kind: str, value: Any) -> Any:
    if kind == "text":
        return _clean(value)
    if kind == "bool":
        return 1 if value else 0
    if kind == "date":
        return _parse_date(value, field).isoformat()
    if kind == "optional_date":
        return _parse_date(value, field).isoformat() if value else None
    if kind == "money":
        if value in (None, ""):
            return None
        try:
            amount = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{field} must be a number")
        if amount < 0:
            raise ValueError(f"{field} cannot be negative")
        return amount
    raise ValueError(f"Unhandled field type {kind}")


def update_event(event_id: str, payload: dict) -> dict:
    """Fill in what the show requires. Only the keys sent are touched.

    Changing the requirements re-raises the checklist for an approved edition,
    so ticking "we are exhibiting" produces the stand's lines immediately rather
    than at the next approval. Nothing is ever removed: a line raised against a
    show that later stops exhibiting may already have been acted on.
    """
    updates: dict[str, Any] = {}
    for field, kind in _EVENT_FIELDS.items():
        if field in payload:
            updates[field] = _coerce(field, kind, payload[field])
    if not updates:
        raise ValueError("Nothing to update")

    with connect() as conn:
        event = _row(
            conn.execute(
                "SELECT * FROM events WHERE id = ? AND deleted_at IS NULL", (event_id,)
            ).fetchone()
        )
        if event is None:
            raise ValueError("No such event")

        merged = {**event, **updates}
        if date.fromisoformat(merged["ends_on"]) < date.fromisoformat(merged["starts_on"]):
            raise ValueError("The end date cannot be before the start date")
        if "starts_on" in updates:
            updates["year"] = date.fromisoformat(merged["starts_on"]).year

        updates["updated_at"] = _now()
        assignments = ", ".join(f"{field} = ?" for field in updates)
        conn.execute(
            f"UPDATE events SET {assignments} WHERE id = ?",
            [*updates.values(), event_id],
        )
        if merged["status"] == "approved":
            subject = _checklist_subject(conn, event_id)
            if subject:
                _seed_checklist(conn, subject)

    return get_event(event_id)


# ---------------------------------------------------------------------------
# Next year
# ---------------------------------------------------------------------------

def clone_event(event_id: str, payload: dict, *, username: str) -> dict:
    """Create next year's edition from this one.

    Carries forward everything that is a property of the *show* — where it is,
    what it costs, who to ask for a quote, what the submission deadline was —
    and none of what is a property of the year: no attendees, no checklist, no
    decision. It lands as `proposed`, so next year's edition still has to be
    argued for.
    """
    starts_on = _parse_date(payload.get("starts_on"), "Start date")
    ends_on = _parse_date(payload.get("ends_on") or payload.get("starts_on"), "End date")
    if ends_on < starts_on:
        raise ValueError("The end date cannot be before the start date")

    stamp = _now()
    with connect() as conn:
        source = _row(
            conn.execute(
                "SELECT * FROM events WHERE id = ? AND deleted_at IS NULL", (event_id,)
            ).fetchone()
        )
        if source is None:
            raise ValueError("No such event")
        if conn.execute(
            "SELECT 1 FROM events WHERE series_id = ? AND year = ? AND deleted_at IS NULL",
            (source["series_id"], starts_on.year),
        ).fetchone() is not None:
            raise ValueError(f"{source['name']} already has a {starts_on.year} edition")

        new_event_id = new_id()
        conn.execute(
            """
            INSERT INTO events (
              id, series_id, name, year, location, country, starts_on, ends_on,
              website, status, invited, exhibiting, demo_required, demo_type,
              submission_note, exhibit_cost, exhibit_currency,
              quote_contact_name, quote_contact_email,
              created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'proposed', 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_event_id,
                source["series_id"],
                source["name"],
                starts_on.year,
                source["location"],
                source["country"],
                starts_on.isoformat(),
                ends_on.isoformat(),
                source["website"],
                source["exhibiting"],
                source["demo_required"],
                source["demo_type"],
                source["submission_note"],
                source["exhibit_cost"],
                source["exhibit_currency"],
                source["quote_contact_name"],
                source["quote_contact_email"],
                username,
                stamp,
                stamp,
            ),
        )

    return get_event(new_event_id)


def delete_event(event_id: str) -> dict:
    """Soft-delete an edition, and hand back the show it retired.

    The row stays; the table stops showing it. **The return value is what lets
    the shared spreadsheet be told.** A deleted show is unreadable through
    `get_event` by design, so a caller that deleted first would have nothing left
    to write out — and the sheet would keep showing the show as live, which is
    exactly the fault this replaced.

    Read before the `UPDATE`, on `get_event`'s own connection: a read on a second
    connection cannot see an uncommitted write, and that is a trap this file has
    already fallen into once.
    """
    event = get_event(event_id)  # raises "No such event", which is the guard
    stamp = _now()
    with connect() as conn:
        conn.execute(
            "UPDATE events SET deleted_at = ?, updated_at = ? WHERE id = ?",
            (stamp, stamp, event_id),
        )
    return {**event, "deleted_at": stamp, "updated_at": stamp}
