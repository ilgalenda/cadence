"""Everything a show needs doing, and when.

This is [[Event Playbook]]'s six-week timeline as data — the same phases, the
same deadlines, made tickable. It is deliberately not a second opinion about how
Acme runs a show: if the playbook changes, this changes with it, and a
disagreement between them is a defect rather than a nuance.

**Cadence raises these and computes their dates. It does not track whether they
are done** — that lives in the spreadsheet, where the people doing the work
already are. Sam set the split: *"No need for Cadence to track all the steps.
Only thing Cadence should show is when everything is approved and everything is
ready."*

**One list, so adding an item is one line.** The sheet's rows, the due dates and
the tests all derive from `CHECKLIST`; nothing counts items by hand.

The two hard rules from the masterplan survive as phases you can see rather than
lead times buried in a table: **business cards at 14 days, anything made for us
at 21.**
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import NamedTuple, Optional

from . import requirements

#: When an item applies.
#:
#:   always        — every show
#:   exhibiting    — only where we take a stand
#:   demo          — only where a demo was promised
#:   submission    — only where there is a paper or demo deadline
#:   per_person    — one row for each confirmed attendee
#:   per_traveller — one row for each attendee who needs travel
ALWAYS = "always"
EXHIBITING = "exhibiting"
DEMO = "demo"
SUBMISSION = "submission"
PER_PERSON = "per_person"
PER_TRAVELLER = "per_traveller"

PER_REGISTRATION = (PER_PERSON, PER_TRAVELLER)

#: Who is expected to do it. A line with no owner is a line nobody has taken, and
#: the tests refuse one.
SAM = "Sam"
JO = "Jo"
OPERATIONS = "Operations"


class Item(NamedTuple):
    phase: str
    item: str
    owner: str
    #: Days from the show's first day. Negative is before, positive is after.
    offset: int
    applies: str = ALWAYS
    #: For a per-person line, the thing the person has to have asked for — a
    #: material key, or a travel mode. Empty on a per-traveller line means the
    #: line follows the nights rather than the mode.
    requires: str = ""


#: The playbook, in order. Phases are named for what they are *for*, so somebody
#: reading the sheet knows why a line is there without opening anything.
CHECKLIST: list[Item] = [
    # ── Decide · six weeks out ───────────────────────────────────────────────
    Item("Decide", "Decision confirmed", SAM, -42),
    Item("Decide", "Stand booked and contract signed", SAM, -42, EXHIBITING),
    Item("Decide", "Tickets booked", OPERATIONS, -42),
    # A missed submission cannot be recovered at any price, which is why it is
    # diarised six weeks out rather than noticed three weeks out.
    Item("Decide", "Submission deadline diarised", SAM, -42, SUBMISSION),

    # ── Reach · four weeks out ───────────────────────────────────────────────
    Item("Reach", "Target list built — who we want to meet, by name", SAM, -28),
    Item("Reach", "Outreach begun to book meetings at the show", SAM, -28),

    # ── Make · three weeks out. The bespoke rule. ────────────────────────────
    Item("Make", "Pull-up banner ordered", JO, -21),
    Item("Make", "Backdrop or stand graphics ordered", JO, -21, EXHIBITING),
    Item("Make", "Table covering ordered", JO, -21, EXHIBITING),
    Item("Make", "Printed collateral ordered", JO, -21),
    Item("Make", "Hoodie or quarter-zip ordered", JO, -21, PER_PERSON, "clothing"),
    Item("Make", "Lanyards ordered", JO, -21),
    Item("Make", "Giveaways ordered", JO, -21),
    Item("Make", "Demo kit assembled", OPERATIONS, -21, DEMO),
    Item("Make", "Demo hardware prepared", OPERATIONS, -21, PER_PERSON, "demo"),
    Item("Make", "Freight booked", OPERATIONS, -21, EXHIBITING),

    # ── Ready · two weeks out. The business-card rule. ───────────────────────
    Item("Ready", "Business cards ordered", JO, -14, PER_PERSON, "cards"),
    Item("Ready", "Demo rehearsed on the hardware being taken", OPERATIONS, -14, DEMO),
    Item("Ready", "Stand power ordered", OPERATIONS, -14, EXHIBITING),
    Item("Ready", "Stand network ordered", OPERATIONS, -14, EXHIBITING),
    Item("Ready", "Badges and passes collected", OPERATIONS, -14),
    # One line per mode the person actually asked for. Operations books a train
    # differently from a flight, and a single "travel" line hides which it is.
    *[Item("Ready", mode.raises, OPERATIONS, -14, PER_TRAVELLER, mode.key)
      for mode in requirements.MODES],
    # No `requires`: the hotel follows the nights, whatever got them there.
    Item("Ready", requirements.ACCOMMODATION, OPERATIONS, -14, PER_TRAVELLER),

    # ── Final week ───────────────────────────────────────────────────────────
    Item("Final week", "Meetings confirmed", SAM, -7),
    Item("Final week", "Follow-up owner named per attendee", SAM, -7),
    Item("Final week", "Capture method agreed and tested", SAM, -7),

    # ── Day before ───────────────────────────────────────────────────────────
    Item("Day before", "Kit checked against the demo kit list", OPERATIONS, -1, DEMO),
    Item("Day before", "Power and network confirmed in writing by the organiser",
         OPERATIONS, -1, EXHIBITING),

    # ── After · the ten days that convert it ─────────────────────────────────
    Item("After", "Every conversation answered", SAM, 2),
    Item("After", "Every conversation has a next step or an explicit no", SAM, 10),
    Item("After", "Recap written", SAM, 14),
]

PHASES = tuple(dict.fromkeys(item.phase for item in CHECKLIST))

#: Every line the playbook knows, in the order it runs — the spreadsheet's
#: dropdown. Somebody adding a line by hand picks from what the playbook already
#: names before inventing wording of their own, which is what keeps two rows
#: meaning the same thing from reading as two different jobs.
ITEMS = tuple(dict.fromkeys(item.item for item in CHECKLIST))

#: Who a line can belong to. A line with nobody's name on it is a line nobody does.
OWNERS = (SAM, JO, OPERATIONS)


def due_on(starts_on: date, item: Item) -> date:
    """When this line is owed, counted from the show's first day."""
    return starts_on + timedelta(days=item.offset)


def applies_to(item: Item, event: dict) -> bool:
    """Whether a show needs this line at all.

    A checklist that lists a stand for a conference somebody is merely attending
    is a checklist people learn to skim, so the conditions are honoured rather
    than everything being raised and marked "not needed".
    """
    if item.applies == ALWAYS:
        return True
    if item.applies == EXHIBITING:
        return bool(event.get("exhibiting"))
    if item.applies == DEMO:
        return bool(event.get("demo_required"))
    if item.applies == SUBMISSION:
        return bool(event.get("submission_deadline"))
    return item.applies in PER_REGISTRATION


def wants_registration(item: Item, registration: dict) -> bool:
    """Whether a per-person line applies to this particular person.

    Two gates, and both matter. A **confirmed** place, because ordering cards and
    booking flights for somebody whose place has not been agreed is exactly the
    spend the approval gate exists to prevent. And **they asked for it**: the
    line follows the answer they gave on the form rather than an assumption that
    everybody needs the same things.
    """
    if registration["status"] != "approved":
        return False

    if item.applies == PER_PERSON:
        if not registration.get("needs_material"):
            return False
        return item.requires in requirements.load(registration.get("material_items"))

    if item.applies == PER_TRAVELLER:
        if not registration.get("needs_travel"):
            return False
        legs = requirements.load(registration.get("travel_legs"))
        if not item.requires:
            # The accommodation line, which follows the nights.
            return requirements.nights(legs) > 0
        return any(leg.get("mode") == item.requires for leg in legs)

    return False


def bespoke_lines(registration: dict) -> list[Item]:
    """Lines for material the list did not have a name for.

    Somebody choosing *Something else* and typing what they need has said the one
    thing nothing in this module could have predicted, so it is raised verbatim
    and given to Jo. Silently dropping it would make the free-text box a lie.
    """
    if registration["status"] != "approved" or not registration.get("needs_material"):
        return []
    chosen = requirements.load(registration.get("material_items"))
    note = (registration.get("material_note") or "").strip()
    if requirements.OTHER not in chosen or not note:
        return []
    return [Item("Make", f"Ordered: {note}", JO, -21, PER_PERSON, requirements.OTHER)]


def for_event(event: dict) -> list[tuple[Item, Optional[dict]]]:
    """Every line this show needs, with the person it belongs to where it has one.

    Returns pairs rather than rows so the caller decides what a row looks like —
    the store writes database rows and the sheet writes cells, and neither should
    have to know about the other's shape.
    """
    lines: list[tuple[Item, Optional[dict]]] = []
    registrations = event.get("registrations", [])

    for item in CHECKLIST:
        if not applies_to(item, event):
            continue
        if item.applies in PER_REGISTRATION:
            lines.extend(
                (item, r) for r in registrations if wants_registration(item, r)
            )
        else:
            lines.append((item, None))

    # Free-text material last, so the standard lines keep the playbook's order
    # and anything bespoke reads as the exception it is.
    for registration in registrations:
        lines.extend((item, registration) for item in bespoke_lines(registration))
    return lines
