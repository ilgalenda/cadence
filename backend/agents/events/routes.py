"""Events' surface — `/api/events`.

Trade-show readiness: which events Acme is going to, who is going, and
whether everything each of them needs has been done in time.

**Not a sales agent, deliberately.** There is no LLM call anywhere in this
package and it is not registered in `agents/sales/registry.py`, so Owl cannot
invoke it. Mounting it top-level, beside `learn` and `wiki`, keeps that visible
in the route table rather than resting on somebody remembering it.

**Two gates, and they are the only authorisation in here.** Any authenticated
employee can register interest and read their own shows — that is the point of
the tool. Deciding whether Acme *goes*, and what a stand costs, is
`require_admin`. Pages hide what a person cannot do; this enforces it.

How far along a show is comes from the spreadsheet, cached — see `store._progress`.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from agents.events import notify, requirements, sheet, store
from auth import is_admin, require_admin, require_authed

router = APIRouter(prefix="/api/events", tags=["events"])


class InterestRequest(BaseModel):
    """The whole form: the person, the show, and the case for going.

    Every field is declared optional here and required in the store instead —
    deliberately. The requirements are **conditional** (a stand cost matters only
    if we are exhibiting, and not at all if we are attending), and a Pydantic
    `required` cannot express that. Declaring them required here would refuse a
    valid registration with a 422 the page cannot explain, where the store
    refuses it with a 400 that names the field and says why.

    `event_id` is the join case: somebody adding themselves to an edition already
    on the calendar answers only about themselves, because the show has been
    described once already.
    """
    # Joining an edition already on the calendar.
    event_id: Optional[str] = None

    # The person.
    intent: str = "attending"
    needs_travel: bool = False
    travel_note: str = ""
    # Loose types on purpose: the shapes are validated in `requirements`, which
    # is where the vocabulary lives, so the model does not hold a second opinion
    # about which material keys or travel modes exist.
    travel_legs: list[dict] = Field(default_factory=list)
    needs_material: bool = False
    material_items: list[str] = Field(default_factory=list)
    material_note: str = ""
    ticket_cost: Optional[float] = None
    ticket_currency: str = "GBP"
    note: str = ""

    # The show.
    name: str = ""
    location: str = ""
    country: str = ""
    starts_on: str = ""
    ends_on: Optional[str] = None
    website: str = ""
    invited: bool = False
    exhibiting: bool = False
    exhibit_cost: Optional[float] = None
    exhibit_currency: str = "GBP"
    quote_contact_name: str = ""
    quote_contact_email: str = ""
    demo_required: bool = False
    demo_type: str = ""
    has_submission_deadline: bool = False
    submission_deadline: Optional[str] = None
    submission_note: str = ""

    # The case for going.
    rationale: str = ""
    decide_by: Optional[str] = None


class DecisionRequest(BaseModel):
    note: str = ""


class CloneRequest(BaseModel):
    starts_on: str
    ends_on: Optional[str] = None


def _synced(event: dict) -> dict:
    """Push a show to the shared spreadsheet, and say on the show whether it went.

    Wrapped around the routes that change a show, so the sheet is fed at the
    moments that matter rather than on a clock Cadence does not have. `push`
    never raises: the record is already written, and a spreadsheet being
    unreachable must not undo it.

    **The outcome is carried back.** It used to be computed and dropped, so a
    push that failed — a quota, an expired grant, no sheet configured — was
    visible only in a server log, while the *email's* identical three states
    were reported to the person who filed the registration. The spreadsheet is
    the one four people work from; it is the one worth being told about.
    """
    event["sheet"] = sheet.push(event)
    return event


def _ok(fn, *args, **kwargs):
    """Run a store call, turning its business rules into a 400.

    The store raises `ValueError` with a message written for the person who
    typed the thing; the page renders `detail` verbatim. Same three-layer shape
    as `agents/sales/signals`.
    """
    try:
        return fn(*args, **kwargs)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Reading — open to anybody signed in
# ---------------------------------------------------------------------------

def _scope(user: dict) -> Optional[str]:
    """Whose calendar this is. `None` for an admin, who sees every show.

    One helper rather than the expression repeated at each read, so a route
    added later cannot forget the scope by copying the wrong line.
    """
    return None if is_admin(user) else user["username"]


@router.get("")
def list_events(
    year: Optional[int] = None,
    status: Optional[str] = None,
    user: dict = Depends(require_authed),
):
    """The calendar. An admin sees every show; anybody else sees their own."""
    # The only clock this application has. Returns at once unless the cached
    # tick-counts are stale, and never blocks the page either way.
    sheet.maybe_refresh_progress()

    return {
        "events": _ok(store.list_events, year=year, status=status,
                      username=_scope(user)),
        "years": store.years(),
        # The page draws a table and a switcher only for somebody who can use
        # them. The scope above is what actually enforces it.
        "admin": is_admin(user),
        # The form's options, served rather than repeated in the page. A list
        # written down twice is a list that disagrees with itself the first time
        # somebody adds to one copy.
        # Where the checklist actually lives. The page tells people to tick
        # things off in the shared spreadsheet and had no way of saying where
        # that is; `None` when nothing is configured, so the link simply is not
        # drawn rather than pointing at a document that does not exist.
        "sheet_url": sheet.url(),
        "material": [
            {"key": m.key, "label": m.label, "hint": m.hint}
            for m in requirements.MATERIAL
        ] + [{"key": requirements.OTHER, "label": "Something else",
              "hint": "Tell us what you need and Jo will price it."}],
        "travel_modes": [{"key": m.key, "label": m.label, "routed": m.routed}
                         for m in requirements.MODES],
    }


@router.get("/{event_id}")
def get_event(event_id: str, user: dict = Depends(require_authed)):
    """One event with its people and its checklist."""
    return _ok(store.get_event, event_id, username=_scope(user))


# ---------------------------------------------------------------------------
# Registering interest — open to anybody signed in
# ---------------------------------------------------------------------------

@router.post("", status_code=201)
def register_interest(req: InterestRequest, user: dict = Depends(require_authed)):
    """Register interest, and tell the admin by email.

    The record is written first and the email sent second. A mail server being
    unreachable must never cost somebody their registration, so the outcome is
    reported rather than raised, and the surface says plainly what happened.

    Sending is synchronous on purpose. The daemon-thread pattern in
    `agents/services/sitemap.py` is the house answer for slow work, but threaded,
    this route could no longer tell the person whether their registration was
    actually announced — and a truthful receipt is worth more than a second of
    latency on something done a few times a month.
    """
    event = _synced(_ok(store.register_interest, user["username"], req.model_dump()))
    # One of `sent` / `unconfigured` / `failed`. The last two both mean no mail
    # arrived and are different faults — one is a setting nobody made, the other
    # a server that would not take it — so the page can say which.
    delivery = notify.registration_filed(event, user["username"])
    return {
        "event": event,
        "delivery": delivery,
        "emailed": delivery == notify.SENT,
        # True when a proposal turned out to be already on the calendar, so the
        # page can say so rather than appearing to have ignored what was typed.
        "joined_existing": event.get("joined_existing", False),
    }


# ---------------------------------------------------------------------------
# The checklist lives in the spreadsheet
# ---------------------------------------------------------------------------
#
# There is deliberately no route here for ticking a line. Cadence raises the
# checklist and computes its dates; whether a line is done is the sheet's to
# say, and Cadence reads back only how many remain. Sam set that split:
# *"No need for Cadence to track all the steps. Only thing Cadence should show
# is when everything is approved and everything is ready."*


# ---------------------------------------------------------------------------
# Decisions — admin only
# ---------------------------------------------------------------------------

@router.post("/{event_id}/approve")
def approve_event(
    event_id: str, req: DecisionRequest, admin: dict = Depends(require_admin)
):
    """Commit to the event. This is what raises its checklist."""
    return _synced(_ok(
        store.decide_event,
        event_id,
        status="approved",
        admin=admin["username"],
        note=req.note,
    ))


@router.post("/{event_id}/decline")
def decline_event(
    event_id: str, req: DecisionRequest, admin: dict = Depends(require_admin)
):
    """Say no, with the reason kept — it is next year's evidence."""
    return _synced(_ok(
        store.decide_event,
        event_id,
        status="declined",
        admin=admin["username"],
        note=req.note,
    ))


@router.post("/{event_id}/attended")
def mark_attended(
    event_id: str, req: DecisionRequest, admin: dict = Depends(require_admin)
):
    """Close an event off once it has happened."""
    return _synced(_ok(
        store.decide_event,
        event_id,
        status="attended",
        admin=admin["username"],
        note=req.note,
    ))


@router.post("/registrations/{registration_id}/approve")
def approve_registration(registration_id: str, admin: dict = Depends(require_admin)):
    """Confirm a person's place, which gives them their cards and their kit."""
    return _synced(_ok(
        store.decide_registration,
        registration_id,
        status="approved",
        admin=admin["username"],
    ))


@router.post("/registrations/{registration_id}/decline")
def decline_registration(registration_id: str, admin: dict = Depends(require_admin)):
    """Decline a person's place. The event itself is untouched.

    Pushed like its opposite. Approving a place reached the sheet and declining
    one did not, which left Operations a row saying somebody was going after the
    decision had gone the other way.
    """
    return _synced(_ok(
        store.decide_registration,
        registration_id,
        status="declined",
        admin=admin["username"],
    ))


@router.patch("/{event_id}")
def update_event(event_id: str, payload: dict, admin: dict = Depends(require_admin)):
    """The show requirements: exhibiting, demo, deadlines, cost, quote contact.

    Takes a raw dict rather than a model because the store already declares
    every field it accepts and how each is coerced (`_EVENT_FIELDS`). A second
    declaration here would be a second place to forget one.
    """
    # Pushed, like every other route that changes a show. This one changes the
    # columns three teams read — dates, exhibiting, stand cost, quote contact —
    # so leaving the document on yesterday's figures is the worst version of the
    # fault the delete route had.
    return _synced(_ok(store.update_event, event_id, payload))


@router.post("/{event_id}/clone", status_code=201)
def clone_event(event_id: str, req: CloneRequest, admin: dict = Depends(require_admin)):
    """Create next year's edition, carrying the show forward but not the year."""
    return _synced(
        _ok(store.clone_event, event_id, req.model_dump(), username=admin["username"]))


@router.delete("/{event_id}")
def delete_event(event_id: str, _admin: dict = Depends(require_admin)):
    """Soft-delete an event, and tell the spreadsheet.

    This was the one mutating route that did not push, and it is the one where
    saying nothing does the most harm: the show's rows stayed in the shared
    document looking live, so somebody could order a banner for a show that was
    called off. `store.delete_event` hands back what it retired precisely so
    there is something to write out.
    """
    _synced(_ok(store.delete_event, event_id))
    return {"ok": True}
