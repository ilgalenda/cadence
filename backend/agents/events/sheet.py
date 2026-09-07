"""The shared events spreadsheet: what goes in it, how it reads, and when.

Four tabs, written by Cadence and read by people who mostly have no Cadence
account — Alex and Nils decide, Jo produces the material, an operations manager
books travel:

  * **Read me** — who reads what, the two lead times, which columns are overwritten.
  * **Events** — one row per show, everything a decision needs.
  * **Requests** — one row per registration, what was asked and what was answered.
  * **Checklist** — one row per thing that has to be done, from the playbook's
    own six-week timeline. This is the tab people work in: every line carries a
    phase, an owner, a date and a **checkbox**, and the checkbox is the one cell
    Cadence reads and never writes.

**Sam drives it; the others read it.** His words: *"I maintain control on
progressing the file and tick boxes. Each relevant team member reviews what needs
to be done."* So every tab is Cadence's block from column A, then Sam's columns
to the right, and the Cadence block is protected with him as the only editor.

**Why the split is at column A and contiguous.** `google_sheets.write_row` PUTs
from `A{n}` across exactly the columns Cadence knows. Columns to the right of
that survive a write; interleaved ones would be silently overwritten, which is
the one way this design could lose somebody's work.

**Columns are declared inside their group**, so the banner that spans a group is
derived from the same list that fills the cells. A banner reading "The decision"
over the wrong six columns is the defect this layout invites, and deriving the
span is what makes it impossible rather than merely unlikely.

**Nothing is read back**; see `integrations/google_sheets.py` for why.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import date
from typing import Any, Callable, Optional, Sequence

from integrations import google_sheets as api
from integrations.google_oauth import GoogleAuthError, get_creds

from . import checklist as playbook
from . import requirements


#: What happened, in one word — the vocabulary `notify.py` reports in.
SYNCED = "synced"
UNCONFIGURED = "unconfigured"
FAILED = "failed"

TITLE = "Acme — Events"
READ_ME = "Read me"
EVENTS = "Events"
REQUESTS = "Requests"
CHECKLIST = "Checklist"
TABS = (READ_ME, EVENTS, REQUESTS, CHECKLIST)

#: What a deleted show's Status reads. Not a status in Cadence's vocabulary —
#: deletion is a timestamp there — but the sheet needs a word, and "cancelled"
#: is the one the people reading it use. `declined` keeps its own word: said no
#: at the gate and called off after approval are different facts.
CANCELLED = "cancelled"

#: Shown where a value is genuinely absent. An empty cell reads as "nobody has
#: filled this in yet"; a dash reads as "there is nothing to fill in", and on a
#: document three teams read those are different facts.
NONE = "—"

#: Row 1 names the audience for each block; row 2 holds the headers.
BANNER_ROW, HEADER_ROW, FIRST_DATA_ROW = 1, 2, 3

#: How tall every tab is kept. Ranges are written against it, and Google refuses
#: one that runs past the grid — which takes the whole formatting batch with it.
GRID_ROWS = 1000

#: Group washes, from the brand palette by way of `design-system/tokens.css`.
#: One hue per audience, so somebody finds their block without being told where.
BLUE = {"red": 0.910, "green": 0.953, "blue": 1.0}      # --accent-wash
AMBER = {"red": 0.996, "green": 0.957, "blue": 0.878}   # --signal-drift-wash
GREEN = {"red": 0.914, "green": 0.957, "blue": 0.894}   # --signal-locked-wash
GOLD = {"red": 0.969, "green": 0.941, "blue": 0.886}    # --field-gold, lightened
GREY = {"red": 0.957, "green": 0.953, "blue": 0.945}    # --surface-sunken
RED_INK = {"red": 0.757, "green": 0.176, "blue": 0.133}   # --signal-fault
AMBER_INK = {"red": 0.545, "green": 0.353, "blue": 0.0}   # --signal-drift, darkened
GREEN_INK = {"red": 0.122, "green": 0.400, "blue": 0.0}   # --signal-locked
RED_WASH = {"red": 0.984, "green": 0.918, "blue": 0.910}
GREEN_WASH = {"red": 0.914, "green": 0.957, "blue": 0.894}
GREY_INK = {"red": 0.545, "green": 0.537, "blue": 0.518}   # --ink-muted

#: One wash per phase, in the order the work happens — the tab's spine. Cool at
#: the far end where there is time, warming as the show approaches, and grey
#: again afterwards when the pressure is off and the follow-up begins.
PHASE_WASH = {
    "Decide":     {"red": 0.910, "green": 0.953, "blue": 1.000},
    "Reach":      {"red": 0.914, "green": 0.965, "blue": 0.965},
    "Make":       {"red": 0.914, "green": 0.957, "blue": 0.894},
    "Ready":      {"red": 0.996, "green": 0.976, "blue": 0.878},
    "Final week": {"red": 0.996, "green": 0.949, "blue": 0.878},
    "Day before": {"red": 0.996, "green": 0.918, "blue": 0.910},
    "After":      {"red": 0.957, "green": 0.953, "blue": 0.945},
}


def _yes(value: Any) -> str:
    return "yes" if value else "no"


def _text(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else NONE


def _money(amount: Any, currency: str) -> str:
    if amount in (None, ""):
        return NONE
    if float(amount) == 0:
        return "free"
    return f"{currency} {float(amount):,.2f}"


def _day(iso: Optional[str]) -> str:
    return iso or NONE


def _attending(event: dict) -> str:
    live = [r for r in event.get("registrations", []) if r["status"] != "declined"]
    return ", ".join(r["username"] for r in live) or NONE


def _travellers(event: dict) -> str:
    live = [r for r in event.get("registrations", [])
            if r["status"] != "declined" and r["needs_travel"]]
    return ", ".join(r["username"] for r in live) or NONE


Column = tuple[str, Callable[..., Any]]
Group = tuple[str, Optional[dict], list[Column]]

# ── Events ──────────────────────────────────────────────────────────────────

EVENT_GROUPS: list[Group] = [
    ("The show", BLUE, [
        ("Cadence id",          lambda e: e["id"]),
        ("Show",                lambda e: e["name"]),
        ("Year",                lambda e: e["year"]),
        ("Starts",              lambda e: e["starts_on"]),
        ("Ends",                lambda e: e["ends_on"]),
        ("Location",            lambda e: _text(e["location"])),
        ("Country",             lambda e: _text(e["country"])),
    ]),
    ("The decision — Alex and Nils", AMBER, [
        ("Status",              lambda e: _status(e)),
        ("Why we should go",    lambda e: _text(e.get("rationale"))),
        ("Decide by",           lambda e: _day(e.get("decide_by"))),
        ("Invited",             lambda e: _yes(e["invited"])),
        ("Exhibiting",          lambda e: _yes(e["exhibiting"])),
        ("Stand cost",          lambda e: _money(e["exhibit_cost"], e["exhibit_currency"])),
        ("Quote contact",       lambda e: _text(e["quote_contact_name"])),
        ("Quote email",         lambda e: _text(e["quote_contact_email"])),
        ("Demo needed",         lambda e: _yes(e["demo_required"])),
        ("Demo type",           lambda e: _text(e["demo_type"])),
        ("Submission deadline", lambda e: _day(e.get("submission_deadline"))),
        ("Decision note",       lambda e: _text(e["decision_note"])),
    ]),
    ("Operations", GREEN, [
        ("Who is going",        _attending),
        ("Travel needed",       _travellers),
    ]),
    ("Progress — the Checklist tab has the detail", GOLD, [
        ("Checklist",           lambda e: e.get("checklist_total", 0)),
        ("Outstanding",         lambda e: e.get("outstanding", 0)),
        ("Next due",            lambda e: _day(e.get("next_due"))),
        ("Last updated",        lambda e: e["updated_at"]),
    ]),
]

#: Sam's columns. To the right of everything Cadence writes, and never touched
#: by it — this is where the file gets progressed.
EVENT_MINE = ("Owner", "Next step", "Notes")

# ── Requests ────────────────────────────────────────────────────────────────

def _material(registration: dict) -> str:
    """What this person asked for, one item per line."""
    if not registration.get("needs_material"):
        return ""
    return requirements.describe_material(
        requirements.load(registration.get("material_items")),
        registration.get("material_note") or "",
    )


def _travel(registration: dict) -> str:
    """Each leg on its own line, so Operations books from the cell.

    Falls back to the free-text note for rows written before the form asked for
    legs. A request made under the old shape is still a request.
    """
    if not registration.get("needs_travel"):
        return ""
    legs = requirements.load(registration.get("travel_legs"))
    return requirements.describe_travel(legs) or _text(registration.get("travel_note"))


REQUEST_GROUPS: list[Group] = [
    ("The request", BLUE, [
        ("Cadence id",    lambda e, r: r["id"]),
        ("Show",          lambda e, r: e["name"]),
        # Beside the show it describes, and separate from the person's own
        # status further along. Two different facts: a place approved for a show
        # that was later called off is still an approved place, and collapsing
        # them loses the answer somebody was actually given. This is also the
        # column the greying rule keys on for this tab.
        ("Show status",   lambda e, r: _status(e)),
        ("Starts",        lambda e, r: e["starts_on"]),
        ("Requested by",  lambda e, r: r["username"]),
        ("Requested on",  lambda e, r: r["created_at"][:10]),
        ("Going as",      lambda e, r: r["intent"]),
        ("Ticket cost",   lambda e, r: _money(r["ticket_cost"], r["ticket_currency"])),
    ]),
    ("The answer — Alex and Nils", AMBER, [
        ("Status",        lambda e, r: r["status"]),
        ("Decided by",    lambda e, r: _text(r.get("decided_by"))),
        ("Decided on",    lambda e, r: _text((r.get("decided_at") or "")[:10])),
    ]),
    # Jo's block. What somebody asked for, in their words where the list had no
    # name for it — the column Jo works from when placing an order.
    ("What they need — Jo", GOLD, [
        ("Material needed", lambda e, r: _yes(r.get("needs_material"))),
        ("Material",        lambda e, r: _material(r)),
    ]),
    ("Operations", GREEN, [
        ("Travel needed", lambda e, r: _yes(r["needs_travel"])),
        ("Travel",        lambda e, r: _travel(r)),
    ]),
]

REQUEST_MINE = ("Flights booked", "Hotel booked", "Notes")

# ── Checklist ───────────────────────────────────────────────────────────────

def _for_whom(event: dict, item: dict) -> str:
    """Whose line this is — the distinction the masterplan turns on.

    Cards and flights belong to a person; a banner and the stand's power belong
    to the show. A blank would read as "nobody has said", so a show-level line
    says so outright.
    """
    if not item.get("registration_id"):
        return "the show"
    for registration in event.get("registrations", []):
        if registration["id"] == item["registration_id"]:
            return registration["username"]
    return NONE


CHECKLIST_GROUPS: list[Group] = [
    ("What needs doing", GOLD, [
        ("Cadence id",  lambda e, i: i["id"]),
        ("Show",        lambda e, i: e["name"]),
        ("Show starts", lambda e, i: e["starts_on"]),
        ("Phase",       lambda e, i: i["phase"]),
        ("Item",        lambda e, i: i["item"]),
        ("For",         _for_whom),
        ("Owner",       lambda e, i: _text(i.get("owner"))),
        ("Due by",      lambda e, i: i["due_on"]),
    ]),
]

#: `Done` is a checkbox, and it is the one cell in the whole document that
#: **Cadence reads and never writes**. One writer, so there is no conflict to
#: lose — which is why read-back is safe here and was not for rich cells.
CHECKLIST_MINE = ("Done", "Notes")

# ── Headers and rows, derived from the groups ───────────────────────────────

def _columns(groups: list[Group]) -> list[Column]:
    return [column for _, _, columns in groups for column in columns]


def header(groups: list[Group], mine: Sequence[str]) -> list[str]:
    return [name for name, _ in _columns(groups)] + list(mine)


def banner(groups: list[Group], mine: Sequence[str]) -> list[str]:
    """Row 1: each group's label over its first column, blank across the rest.

    Written as values as well as merged, so the label survives somebody removing
    the merge — and so a tab still reads correctly with no formatting at all.
    """
    cells: list[str] = []
    for label, _, columns in groups:
        cells.append(label)
        cells.extend([""] * (len(columns) - 1))
    if mine:
        cells.append("Sam — progress")
        cells.extend([""] * (len(mine) - 1))
    return cells


def spans(groups: list[Group], mine: Sequence[str]) -> list[tuple[str, Optional[dict], int, int]]:
    """Each group as (label, wash, first column, last column), zero-indexed."""
    out, at = [], 0
    for label, wash, columns in groups:
        out.append((label, wash, at, at + len(columns)))
        at += len(columns)
    if mine:
        out.append(("Sam — progress", GREY, at, at + len(mine)))
    return out


def cadence_width(groups: list[Group]) -> int:
    """How far Cadence's block reaches. Everything past it belongs to Sam."""
    return len(_columns(groups))


def retired(event: dict) -> bool:
    """A show nobody should still be working on.

    Deleted in Cadence, or declined. Both mean the same thing to somebody
    reading the document — do not order anything for this — so both grey the row
    and both take the checklist lines away.
    """
    return bool(event.get("deleted_at")) or event.get("status") == "declined"


def _status(event: dict) -> str:
    return CANCELLED if event.get("deleted_at") else event["status"]


def event_row(event: dict) -> list[Any]:
    return [get(event) for _, get in _columns(EVENT_GROUPS)]


def request_rows(event: dict) -> list[list[Any]]:
    return [[get(event, r) for _, get in _columns(REQUEST_GROUPS)]
            for r in event.get("registrations", [])]


def checklist_rows(event: dict) -> list[list[Any]]:
    return [[get(event, i) for _, get in _columns(CHECKLIST_GROUPS)]
            for i in event.get("checklist", [])]


#: Tab name → (groups, Sam's columns, row builder name). One place, so a tab
#: cannot be added to the file and forgotten by the formatter.
LAYOUT: dict[str, tuple[list[Group], Sequence[str]]] = {
    EVENTS: (EVENT_GROUPS, EVENT_MINE),
    REQUESTS: (REQUEST_GROUPS, REQUEST_MINE),
    CHECKLIST: (CHECKLIST_GROUPS, CHECKLIST_MINE),
}

READ_ME_TEXT = [
    ["Acme — Events"],
    [],
    ["This is the working document for a trade show, from the request to the day"],
    ["it opens. Cadence writes most of it; Sam progresses the rest."],
    [],
    ["Who reads what"],
    ["Alex and Nils", "the amber blocks — the case, the cost, the decision"],
    ["Jo", "the Checklist tab, filtered to Owner = Jo"],
    ["Operations", "the Checklist tab, filtered to Owner = Operations"],
    ["Sam", "everything, and the grey block only he can edit"],
    [],
    ["The Checklist tab is where the work happens"],
    ["", "Every line a show needs, with a phase, an owner and a date. The phase"],
    ["", "is colour-coded, so the tab reads down its left-hand edge."],
    ["", "Tick 'Done' when a line is finished. Cadence reads those ticks and uses"],
    ["", "them to say whether a show is ready."],
    ["", ""],
    ["", "Use the view menu — Data ▸ Filter views — to see only your own lines."],
    ["", "A filter view is yours alone; changing it changes nothing for anybody"],
    ["", "else, which an ordinary filter does not."],
    [],
    ["Adding a line yourself"],
    ["", "Type it on the first empty row. Show, Phase, Item and Owner are all"],
    ["", "dropdowns; Item takes anything if the list has no name for it."],
    ["", "Fill in at least the Show and the Item. Cadence picks the line up on"],
    ["", "its next pass, puts an id in column A and counts it from then on."],
    [],
    ["Two deadlines govern everything"],
    ["Business cards", "ordered at least 14 days before the show"],
    ["Anything made for us", "at least 21 days — banner, demo kit, collateral, clothing"],
    ["", "A 'Due by' date turns red once it has passed, amber in the week before."],
    [],
    ["When a show stops happening"],
    ["", "Its row here and on Requests goes grey and stays — what was asked and"],
    ["", "what was answered is the record next year reads."],
    ["", "Its Checklist lines are removed. Nobody should work a dead show's list."],
    [],
    ["Do not delete a row that has an id"],
    ["", "Cadence finds a line by the id in column A and rebuilds any row it"],
    ["", "wrote. Delete one and the tick goes with it — the line comes back"],
    ["", "unticked. Adding rows is fine; removing them is not."],
    ["", "To take a show off, remove it in Cadence and this document follows."],
    [],
    ["What is written by Cadence"],
    ["", "Every column up to the grey block. Edits there are overwritten the next"],
    ["", "time the show changes, so they are protected rather than merely discouraged."],
    ["", "To change one, change it in Cadence at /work/events."],
]


# ---------------------------------------------------------------------------
# Talking to Google
# ---------------------------------------------------------------------------

def _writer() -> Optional[str]:
    """Whose Google connection writes the sheet.

    A setting rather than whoever happened to click: the file lives in one
    person's Drive, and a registration filed by somebody with no Google grant
    must still reach it.
    """
    named = os.environ.get("SHEET_SYNC_USER", "").strip()
    if named:
        return named if get_creds(named) else None

    from auth import load_users  # imported here: `auth` reads files tests redirect

    for user in load_users():
        if user.get("access") == "admin" and get_creds(user["username"]):
            return user["username"]
    return None


def sheet_id() -> str:
    return os.environ.get("EVENTS_SHEET_ID", "").strip()


def url() -> Optional[str]:
    """The document's address, or `None` when there is not one yet."""
    return api.sheet_url(sheet_id()) if is_configured() else None


def is_configured() -> bool:
    """Both halves are needed, and they fail for different reasons: no id means
    nobody has run `check_sheet.py`; no writer means the owning account has not
    connected Google."""
    return bool(sheet_id()) and _writer() is not None


#: Tabs this module used to write. A stale tab full of headings nobody feeds
#: reads as current to whoever opens it, so it is removed rather than left.
RETIRED_TABS = ("Material",)


def _trim_read_me(username: str, spreadsheet_id: str) -> None:
    """Remove what a longer previous Read me left trailing below this one.

    The text itself is laid down with everything else in `ensure_tabs`; only the
    surplus needs a read to find, and usually there is none.
    """
    existing = len(api.column(username, spreadsheet_id, READ_ME))
    surplus = list(range(len(READ_ME_TEXT) + 1, existing + 1))
    if surplus:
        api.delete_rows(username, spreadsheet_id,
                        api.tab_ids(username, spreadsheet_id)[READ_ME], surplus)


def ensure_tabs(username: str, spreadsheet_id: str) -> None:
    """Every tab exists and carries its banner and header. Idempotent."""
    existing = api.tab_names(username, spreadsheet_id)
    for tab in TABS:
        if tab not in existing:
            api.add_tab(username, spreadsheet_id, tab)

    retired = [t for t in RETIRED_TABS if t in existing and t not in TABS]
    if retired:
        ids = api.tab_ids(username, spreadsheet_id)
        for tab in retired:
            api.drop_tab(username, spreadsheet_id, ids[tab])

    # The banner, the header and the Read me are all rewritten every run, not
    # written once. They are Cadence's rows, and a column added to the code
    # while the sheet keeps yesterday's heading is worse than no heading — it
    # puts a true label over the wrong data on a document three teams read.
    #
    # All of it in **one** request. Written a row at a time this was six writes
    # for the headings and one per line of the Read me, on every push, against
    # a limit of sixty a minute.
    updates: list[tuple] = []
    for tab, (groups, mine) in LAYOUT.items():
        updates.append((tab, BANNER_ROW, banner(groups, mine)))
        updates.append((tab, HEADER_ROW, header(groups, mine)))
    updates.extend((READ_ME, number, line or [""])
                   for number, line in enumerate(READ_ME_TEXT, start=1))

    api.write_rows(username, spreadsheet_id, updates)
    _trim_read_me(username, spreadsheet_id)


def create_sheet(username: str) -> str:
    spreadsheet_id = api.create(username, TITLE, list(TABS))
    ensure_tabs(username, spreadsheet_id)
    return spreadsheet_id


# ── The document's design, as batchUpdate requests ──────────────────────────

def a1_column(index: int) -> str:
    """A zero-based column index as its spreadsheet letters.

    `chr(ord("A") + index)` works until column 26 and then produces `[`, which
    Google rejects as a formula — and "Next deadline" is column 27. Base-26 with
    no zero digit, which is what a spreadsheet actually counts in.
    """
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def _grid(sheet_id_: int, r0: int, r1: int, c0: int, c1: int) -> dict:
    return {"sheetId": sheet_id_, "startRowIndex": r0, "endRowIndex": r1,
            "startColumnIndex": c0, "endColumnIndex": c1}


def _date_rule(sheet_id_: int, r0: int, c0: int, c1: int,
               formula: str, wash: dict, ink: dict) -> dict:
    return {"addConditionalFormatRule": {"index": 0, "rule": {
        "ranges": [_grid(sheet_id_, r0, GRID_ROWS, c0, c1)],
        "booleanRule": {
            "condition": {"type": "CUSTOM_FORMULA",
                          "values": [{"userEnteredValue": formula}]},
            "format": {"backgroundColor": wash,
                       "textFormat": {"foregroundColor": ink, "bold": True}},
        },
    }}}


def _one_of(values: Sequence[str], strict: bool = True) -> dict:
    """A dropdown of fixed choices.

    `strict=False` shows the list and still accepts something typed over it —
    the right default for a vocabulary that describes the work rather than
    defining it. Refusing an item nobody thought of would just move the work
    into the Notes column, where nothing can count it.
    """
    return {"condition": {"type": "ONE_OF_LIST",
                          "values": [{"userEnteredValue": v} for v in values]},
            "showCustomUi": True, "strict": strict}


def _one_of_range(a1: str) -> dict:
    """A dropdown that reads its choices from a range, so it keeps itself current."""
    return {"condition": {"type": "ONE_OF_RANGE",
                          "values": [{"userEnteredValue": f"={a1}"}]},
            "showCustomUi": True, "strict": False}


def _checklist_dropdowns(checklist_id: int, head: list) -> list[dict]:
    """The lists that let somebody add a line without inventing its wording.

    Sam asked for this: *"there should be a drop list for the items needed"*.
    A row typed straight into the tab is a real line — Cadence adopts it on the
    next read and starts counting it — so the columns it is joined on are the
    ones worth constraining. The show list points at the Events tab rather than
    a copy, so a show registered this morning is in the list this afternoon.
    """
    show_column = a1_column(header(EVENT_GROUPS, EVENT_MINE).index("Show"))
    lists = {
        "Show":  _one_of_range(f"{EVENTS}!${show_column}$3:${show_column}"),
        "Phase": _one_of(playbook.PHASES),
        "Item":  _one_of(playbook.ITEMS, strict=False),
        "Owner": _one_of(playbook.OWNERS),
    }

    requests: list[dict] = []
    for column, rule in lists.items():
        at = head.index(column)
        requests.append({"setDataValidation": {
            "range": _grid(checklist_id, 2, GRID_ROWS, at, at + 1), "rule": rule}})
    return requests


def _phase_spine(checklist_id: int, head: list) -> list[dict]:
    """Colour the Phase cell by which phase it is.

    The tab is read down the left-hand edge, and a run of identical grey text
    is the thing that made it unreadable. Colouring the cell rather than the row
    keeps the deadline reds and the done greens meaning what they mean.
    """
    at = head.index("Phase")
    letter = a1_column(at)
    return [{"addConditionalFormatRule": {"index": 0, "rule": {
        "ranges": [_grid(checklist_id, 2, GRID_ROWS, at, at + 1)],
        "booleanRule": {
            "condition": {"type": "CUSTOM_FORMULA", "values": [
                {"userEnteredValue": f'=${letter}3="{phase}"'}]},
            "format": {"backgroundColor": wash,
                       "textFormat": {"bold": True}},
        }}}} for phase, wash in PHASE_WASH.items()]


def _owner_views(checklist_id: int, head: list) -> list[dict]:
    """One saved filter view per owner, and one for what is still outstanding.

    A **filter view**, not a filter: it is somebody's own lens on the tab and
    changing it does not change what anybody else sees. That is what makes this
    usable by four people at once, which an ordinary filter is not.
    """
    owner_at = head.index("Owner")
    done_at = head.index("Done")
    span = _grid(checklist_id, 1, GRID_ROWS, 0, len(head))

    # "Operations' lines", not "Operations's" — a name ending in s takes a bare
    # apostrophe, and these titles are read by the people they name.
    possessive = lambda name: f"{name}'" if name.endswith("s") else f"{name}'s"

    views = [(f"{possessive(owner)} lines", owner_at,
              {"condition": {"type": "TEXT_EQ",
                             "values": [{"userEnteredValue": owner}]}})
             for owner in playbook.OWNERS]
    # Hidden values, not a condition: `Done` is a checkbox, so its cells hold
    # the literal TRUE and FALSE, and hiding one value is exactly the ask.
    # There is no boolean *condition* type for this — the API rejects one.
    views.append(("Still to do", done_at, {"hiddenValues": ["TRUE"]}))

    return [{"addFilterView": {"filter": {
        "title": title,
        "range": span,
        "criteria": {str(column): criteria},
    }}} for title, column, criteria in views]


def _retired_rule(sheet_id_: int, groups: list, mine: tuple, column: str) -> dict:
    """Grey a whole row once its Status says the show is off.

    Declarative, keyed on the cell: Cadence never formats a row it has retired,
    and a row that is somehow revived clears itself. The alternative — painting
    each row as it is retired — is a formatting call per delete and a record of
    which rows are grey that has to stay true.
    """
    head = header(groups, mine)
    letter = a1_column(head.index(column))
    return {"addConditionalFormatRule": {"index": 0, "rule": {
        "ranges": [_grid(sheet_id_, 2, GRID_ROWS, 0, len(head))],
        "booleanRule": {
            "condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue":
                f'=OR(${letter}3="{CANCELLED}", ${letter}3="declined")'}]},
            "format": {"backgroundColor": GREY,
                       "textFormat": {"foregroundColor": GREY_INK, "italic": True}},
        },
    }}}


def format_requests(tab_ids: dict[str, int], editor_email: str,
                    existing: dict, used_rows: int = 0) -> list[dict]:
    """Every piece of the document's appearance, as one list.

    Deletes before it adds: conditional formats and protected ranges accumulate,
    and a rule applied twice is invisible until somebody wonders why a cell has
    two. So a re-run leaves the same document rather than a thicker one.
    """
    requests: list[dict] = []

    for sheet in existing.get("sheets", []):
        sid = sheet["properties"]["sheetId"]
        for _ in sheet.get("conditionalFormats", []) or []:
            requests.append({"deleteConditionalFormatRule": {"sheetId": sid, "index": 0}})
        for protected in sheet.get("protectedRanges", []) or []:
            requests.append({"deleteProtectedRange":
                             {"protectedRangeId": protected["protectedRangeId"]}})
        # Filter views accumulate the same way, and four copies of "Jo's lines"
        # in the view menu is worse than none.
        for view in sheet.get("filterViews", []) or []:
            requests.append({"deleteFilterView": {"filterId": view["filterViewId"]}})

    for tab, (groups, mine) in LAYOUT.items():
        sid = tab_ids[tab]
        width = cadence_width(groups)
        total = width + len(mine)

        # The grid is sized first. A tab created with fewer columns than the
        # layout needs rejects every format aimed past its edge — "exceeds grid
        # limits", which reads as a formatting bug and is a sizing one.
        requests.append({"updateSheetProperties": {
            "properties": {"sheetId": sid,
                           "gridProperties": {"columnCount": total, "rowCount": GRID_ROWS}},
            "fields": "gridProperties(columnCount,rowCount)"}})

        # Two frozen rows — the banner and the header — and two frozen columns,
        # so the id and the show stay visible however far right somebody reads.
        requests.append({"updateSheetProperties": {
            "properties": {"sheetId": sid, "gridProperties":
                           {"frozenRowCount": 2, "frozenColumnCount": 2}},
            "fields": "gridProperties(frozenRowCount,frozenColumnCount)"}})

        # The banner is coloured, not merged. Two reasons, and the second is the
        # better one: Google refuses a merge that crosses the frozen-column
        # boundary, and **merged cells break sorting and filtering** — which is
        # the first thing anybody does to a sheet like this. The label sits in
        # the block's first cell and the wash carries the grouping.
        for label, wash, c0, c1 in spans(groups, mine):
            requests.append({"repeatCell": {
                "range": _grid(sid, 0, 1, c0, c1),
                "cell": {"userEnteredFormat": {
                    "backgroundColor": wash,
                    "horizontalAlignment": "LEFT",
                    "textFormat": {"bold": True, "fontSize": 10}}},
                "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,textFormat)"}})

        requests.append({"repeatCell": {
            "range": _grid(sid, 1, 2, 0, total),
            "cell": {"userEnteredFormat": {
                "textFormat": {"bold": True},
                "wrapStrategy": "CLIP",
                "borders": {"bottom": {"style": "SOLID"}}}},
            "fields": "userEnteredFormat(textFormat,wrapStrategy,borders)"}})

        # The id is kept narrow rather than hidden: a hidden column is one
        # somebody deletes while tidying, and every row is found by it.
        requests.append({"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS",
                      "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": 60}, "fields": "pixelSize"}})
        requests.append({"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS",
                      "startIndex": 1, "endIndex": total},
            "properties": {"pixelSize": 150}, "fields": "pixelSize"}})

        requests.append({"setBasicFilter": {"filter": {
            "range": _grid(sid, 1, GRID_ROWS, 0, total)}}})

        # Sam's block is the only part anybody progresses, so it is the only
        # part left unprotected — and it is shaded to say so.
        requests.append({"repeatCell": {
            "range": _grid(sid, 2, GRID_ROWS, width, total),
            "cell": {"userEnteredFormat": {"backgroundColor": GREY}},
            "fields": "userEnteredFormat.backgroundColor"}})
        requests.append({"addProtectedRange": {"protectedRange": {
            "range": _grid(sid, 0, GRID_ROWS, 0, width),
            "description": "Written by Cadence — change it at /work/events",
            "warningOnly": False,
            "editors": {"users": [editor_email]}}}})

    # The deadline colours, on the two columns that carry an order-by date. The
    # same rule the app runs on, said the same way: past is late, the week
    # before is a warning.
    events_id = tab_ids[EVENTS]
    next_due = header(EVENT_GROUPS, EVENT_MINE).index("Next due")
    checklist_id = tab_ids[CHECKLIST]
    head = header(CHECKLIST_GROUPS, CHECKLIST_MINE)
    due_by = head.index("Due by")

    for sid, col in ((events_id, next_due), (checklist_id, due_by)):
        letter = a1_column(col)
        requests.append(_date_rule(
            sid, 2, col, col + 1,
            f'=AND(ISNUMBER(DATEVALUE(${letter}3)), DATEVALUE(${letter}3)<TODAY())',
            RED_WASH, RED_INK))
        requests.append(_date_rule(
            sid, 2, col, col + 1,
            f'=AND(ISNUMBER(DATEVALUE(${letter}3)), DATEVALUE(${letter}3)>=TODAY(),'
            f' DATEVALUE(${letter}3)<=TODAY()+7)',
            {"red": 0.996, "green": 0.957, "blue": 0.878}, AMBER_INK))

    # `Done` is a real checkbox, which is what makes the tab tickable rather than
    # a list somebody types "yes" into — and it is the only cell Cadence reads.
    # The same helper a push uses, so the two can never disagree about how wide
    # the tickable area is.
    requests.extend(_checkbox_requests(checklist_id, head, used_rows))

    # A ticked line goes quiet: the row it sits on stops asking for attention,
    # which is the whole point of ticking it.
    done_letter = a1_column(head.index("Done"))
    requests.append({"addConditionalFormatRule": {"index": 0, "rule": {
        "ranges": [_grid(checklist_id, 2, GRID_ROWS, 0, len(header(CHECKLIST_GROUPS, CHECKLIST_MINE)))],
        "booleanRule": {
            "condition": {"type": "CUSTOM_FORMULA",
                          "values": [{"userEnteredValue": f"=${done_letter}3=TRUE"}]},
            "format": {"backgroundColor": GREEN_WASH,
                       "textFormat": {"foregroundColor": GREEN_INK}},
        },
    }}})

    # What makes the tab readable and addable-to: a coloured phase down the left
    # edge, a dropdown on every column a line is joined on, and a saved view per
    # person so nobody has to read anybody else's work.
    requests.extend(_phase_spine(checklist_id, head))
    requests.extend(_checklist_dropdowns(checklist_id, head))
    requests.extend(_owner_views(checklist_id, head))

    # Appended last, and that is load-bearing: every rule goes in at index 0,
    # so the last one added sits first and wins. A past-due date must not
    # paint red over a show that is no longer happening.
    #
    # Each tab greys on the column carrying the *show's* fate — on Requests
    # that is "Show status", not the person's own answer beside it.
    requests.append(_retired_rule(tab_ids[EVENTS], EVENT_GROUPS, EVENT_MINE, "Status"))
    requests.append(
        _retired_rule(tab_ids[REQUESTS], REQUEST_GROUPS, REQUEST_MINE, "Show status"))

    return requests


def format_sheet(username: str, spreadsheet_id: str) -> None:
    """Apply the document's design. Safe to run again.

    Run *after* the rows, so the checkbox column can be sized to what is there.
    """
    creds = get_creds(username) or {}
    editor = creds.get("email", "")
    existing = api.describe(username, spreadsheet_id)
    tabs = {s["properties"]["title"]: s["properties"]["sheetId"]
            for s in existing.get("sheets", [])}
    api.batch_update(
        username, spreadsheet_id,
        format_requests(tabs, editor, existing,
                        _last_used_row(username, spreadsheet_id, CHECKLIST)))


# ── Writing ─────────────────────────────────────────────────────────────────

def _last_used_row(username: str, spreadsheet_id: str, tab: str) -> int:
    """The last row of `tab` that carries an id in column A.

    The **last row carrying an id**, not the length of the column: a blank cell
    that once held something still comes back, so the raw length counted a
    thousand empty rows as used and sized the checkboxes to match.

    This is the only honest answer to "how far down does this tab go", and it has
    to come from the tab itself. Anything derived from the rows *one event* just
    wrote describes that event, not the tab — and a range over the tab built from
    one event's extent reaches across everybody else's work.
    """
    ids = api.column(username, spreadsheet_id, tab)
    return max([n for n, key in enumerate(ids, start=1) if key.strip()],
               default=HEADER_ROW)


def _upsert_all(username: str, spreadsheet_id: str, tab: str,
                rows: Sequence[Sequence[Any]]) -> None:
    """Write each row where its id already is, and add the rest at the bottom.

    The id in column A is what makes a re-run idempotent, and what lets a sheet
    somebody cleared rebuild itself rather than growing a second copy.

    **Three requests for a whole tab, not two per row.** This read the id column
    again for every single row and wrote each one on its own, so approving a
    show with an eighteen-line checklist spent thirty-six of the sixty writes a
    minute Google allows — and the ones past the limit failed silently, leaving
    a sheet that looked merely out of date.

    It used to return the last row it wrote, and the checkbox range was sized
    from that — which described this event rather than the tab, and cleared
    everybody else's ticks below it. `_last_used_row` answers that question now.
    """
    if not rows:
        return

    ids = api.column(username, spreadsheet_id, tab)
    at = {key.strip(): n for n, key in enumerate(ids, start=1) if key.strip()}

    # Where a new row goes, worked out from the ids rather than left to Google.
    # `values.append` puts a row after the last cell holding *anything* in the
    # tab — and the Done column is pre-filled with checkboxes, so an append
    # landed on row 1017, outside the grid and outside every sort. The last row
    # carrying an id is the only honest answer to "where does the next one go".
    next_row = max([*at.values(), HEADER_ROW]) + 1

    updates = []
    for row in rows:
        key = str(row[0]).strip()
        if key in at:
            updates.append((tab, at[key], row))
        else:
            updates.append((tab, next_row, row))
            next_row += 1

    api.write_rows(username, spreadsheet_id, updates)


def _read_checklist() -> "list[tuple[int, list]]":
    """Every row of the Checklist tab, with the number it sits on."""
    head = header(CHECKLIST_GROUPS, CHECKLIST_MINE)
    rows = api.columns(_writer(), sheet_id(), CHECKLIST,
                       f"A{FIRST_DATA_ROW}:{a1_column(len(head) - 1)}")
    return list(enumerate(rows, start=FIRST_DATA_ROW))


def ticked(rows: "Optional[list]" = None) -> set:
    """The checklist lines the sheet says are done, by their own id.

    Keyed on the line's id in column A, not on the show's name: two shows can
    share a name across years, and a wrong join here would report one year's
    progress against another's.

    A row shorter than the Done column is unticked — Sheets omits trailing empty
    cells, so an untouched checkbox comes back as a missing one.
    """
    if rows is None:
        if not is_configured():
            return set()
        rows = _read_checklist()

    head = header(CHECKLIST_GROUPS, CHECKLIST_MINE)
    done_at = head.index("Done")

    return {
        row[0] for _, row in rows
        if row and row[0]
        and len(row) > done_at and str(row[done_at]).strip().upper() == "TRUE"
    }


def written_in(rows: "list") -> "list[dict]":
    """Lines somebody added by hand: a row with an item but no Cadence id.

    Sam asked for the dropdowns so a line could be added straight into the tab,
    and a line nothing counts is a line that does not exist. So Cadence picks
    these up, gives each one an id, and from then on treats it exactly like a
    line the playbook raised.

    A row is only taken seriously if it names **a show and an item**. The tab
    has a thousand rows of validation on it and somebody will click a dropdown
    and change their mind; half a row is not an instruction.
    """
    head = header(CHECKLIST_GROUPS, CHECKLIST_MINE)
    at = {name: head.index(name) for name in
          ("Show", "Show starts", "Phase", "Item", "For", "Owner", "Due by")}

    def cell(row: list, name: str) -> str:
        index = at[name]
        return str(row[index]).strip() if len(row) > index else ""

    added = []
    for number, row in rows:
        if not row or (row[0] or "").strip():
            continue
        if not (cell(row, "Show") and cell(row, "Item")):
            continue
        added.append({
            "row": number,
            "show": cell(row, "Show"),
            # Two years of one show carry the same name here — the year is its
            # own column on Events and is not repeated in this tab. The start
            # date is what tells them apart.
            "starts_on": cell(row, "Show starts"),
            "phase": cell(row, "Phase"),
            "item": cell(row, "Item"),
            "owner": cell(row, "Owner"),
            "due_on": cell(row, "Due by"),
        })
    return added


def _tidy_checklist(username: str, spreadsheet_id: str) -> None:
    """Put the tab back in order, and give every row a checkbox.

    **Sorted**, because rows are only ever written at the bottom: a line added
    by hand, or a person confirmed after the others, lands away from the phase
    it belongs to. Show first, then due date — the order the phases already run
    in — so the phase colours come out as bands rather than confetti. A
    whole-row sort, so the id, the tick and anybody's notes travel together.

    **And the `Done` column is re-ranged to the rows that now exist.** This is
    the fault that would have bitten hardest: `format_sheet` runs from
    `check_sheet.py` and from retirement, never from a push, so the checkbox
    range stayed frozen at whatever the last manual run sized it to. Approve a
    third show and its lines fall past the margin with no checkbox on them —
    untickable, therefore permanently outstanding, therefore a show that can
    never read ready.

    **The extent is read from the tab, never passed in.** Both callers used to
    supply it, and both supplied their own extent rather than the tab's — the
    rows one push wrote, or the lines one refresh adopted. Since the range runs
    from that row *down to the bottom of the grid*, clearing the `Done` column
    as it goes, a push for a show with no checklist lines yet reported row 2 and
    wiped every tick in the tab. The tab's own id column is the only thing that
    knows how far down the tab goes, so this asks it.

    One request for all of it, so keeping the tab usable costs nothing.
    """
    head = header(CHECKLIST_GROUPS, CHECKLIST_MINE)
    checklist_id = api.tab_ids(username, spreadsheet_id)[CHECKLIST]
    last_row = _last_used_row(username, spreadsheet_id, CHECKLIST)
    api.batch_update(username, spreadsheet_id,
                     [_sort_request(checklist_id, head)]
                     + _checkbox_requests(checklist_id, head, last_row))


def _sort_request(checklist_id: int, head: list) -> dict:
    columns = [head.index(name) for name in ("Show", "Due by", "Item")]
    return {"sortRange": {
        "range": _grid(checklist_id, FIRST_DATA_ROW - 1, GRID_ROWS, 0, len(head)),
        "sortSpecs": [{"dimensionIndex": at, "sortOrder": "ASCENDING"}
                      for at in columns],
    }}


def _checkbox_requests(checklist_id: int, head: list, last_row: int) -> list[dict]:
    """The `Done` column: a checkbox on every row that exists and none below.

    Cleared across the whole column first — narrowing a range does not lift the
    validation a wider earlier run left behind — then applied to the rows there
    are, plus a small margin so a line or two can be typed in by hand.
    """
    at = head.index("Done")
    last = min(max(last_row, HEADER_ROW), GRID_ROWS)
    edge = min(max(last + 20, 40), GRID_ROWS)

    return [
        {"setDataValidation": {
            "range": _grid(checklist_id, 2, GRID_ROWS, at, at + 1)}},
        {"setDataValidation": {
            "range": _grid(checklist_id, 2, edge, at, at + 1),
            "rule": {"condition": {"type": "BOOLEAN"}, "showCustomUi": True}}},
        # A literal FALSE below the rows that exist is **data**, and data below
        # the last row is what sent an appended row to the bottom of the grid.
        {"repeatCell": {
            "range": _grid(checklist_id, last, GRID_ROWS, at, at + 1),
            "fields": "userEnteredValue"}},
    ]


def _drop_checklist(username: str, spreadsheet_id: str, event: dict) -> None:
    """Take a retired show's lines out of the Checklist tab.

    The record of what was proposed stays on Events and Requests, greyed — see
    `retired`. The **work** does not: a cancelled show's checklist is a list of
    things nobody should do, and leaving it there greyed still leaves it there,
    in the one tab three people work from top to bottom.

    Which rows those are needs no extra read. The ids come from the show itself
    and their positions from the same column lookup `_upsert_all` makes.
    """
    ours = {row[0] for row in checklist_rows(event)}
    if not ours:
        return

    ids = api.column(username, spreadsheet_id, CHECKLIST)
    rows = [n for n, key in enumerate(ids, start=1) if key in ours]
    if not rows:
        return

    api.delete_rows(username, spreadsheet_id,
                    api.tab_ids(username, spreadsheet_id)[CHECKLIST], rows)
    # Deleting rows shrinks every range that spanned them — the checkbox column
    # and each conditional format included — and none of it grows back. The
    # layout is rebuilt rather than repaired: `format_sheet` clears its rules
    # before adding them and re-sizes the checkboxes to what is now there.
    format_sheet(username, spreadsheet_id)


#: How long a cached tick-count is trusted before the page is worth a fresh
#: read. There is no scheduler in this application, so a page load is the only
#: clock there is — and Sam asked Cadence for one thing, whether a show is
#: ready, which is not a number that turns on the minute.
PROGRESS_TTL_SECONDS = 15 * 60

_progress_lock = threading.Lock()

#: When the sheet was last asked, or `None` for never. **Not `0.0`** — on this
#: platform `time.monotonic()` counts from process start, so a zero would read
#: as "asked a moment ago" and no restart would read the sheet for a full TTL.
_last_attempt: Optional[float] = None


def refresh_progress() -> int:
    """The whole round trip with the spreadsheet. Returns shows changed.

    Three things, in this order and for a reason:

    1. **Read the tab once.** Everything below works off that one read.
    2. **Adopt what somebody added by hand**, and stamp the id Cadence gave it
       into column A. That has to happen before the count, or a line added this
       minute would be missing from it — and before anything else writes, or the
       row would be adopted again on the next pass.
    3. **Count what is ticked**, which is the number the page reports.

    Synchronous, so `check_sheet.py` and anybody who wants a truthful answer can
    have one. `maybe_refresh_progress` is the lazy door on to it.
    """
    from . import store  # here, not at the top: `store` is the lower layer.

    with _progress_lock:
        if not is_configured():
            return 0

        rows = _read_checklist()
        adopted, duplicates = store.adopt_lines(written_in(rows))

        if duplicates:
            # Typed a line the show already had. Removing the row is the honest
            # answer: the line is on the list, once, where it always was.
            api.delete_rows(_writer(), sheet_id(),
                            api.tab_ids(_writer(), sheet_id())[CHECKLIST],
                            duplicates)
            print(f"[sheet] removed {len(duplicates)} duplicate line(s)")

        if adopted:
            # Column A only. The rest of the row is what they typed, and the
            # columns to the right are theirs.
            api.write_rows(_writer(), sheet_id(),
                           [(CHECKLIST, number, [line_id])
                            for number, line_id in sorted(adopted.items())])
            # Sorted straight away: an adopted line was appended at the bottom,
            # and leaving it there is leaving it away from its phase.
            _tidy_checklist(_writer(), sheet_id())
            print(f"[sheet] adopted {len(adopted)} line(s) added by hand")

        return store.record_progress(ticked(rows))


def maybe_refresh_progress() -> None:
    """If nobody has read the sheet lately, read it in the background.

    The pattern `agents/services/sitemap.py:121` already establishes — a TTL, a
    lock, a daemon thread, and never blocking the caller. The page keeps
    rendering the cached numbers while the refresh lands, so a tick made a
    moment ago shows on the next load rather than this one.

    **The stamp is set before the call, not after.** A spreadsheet that is
    unreachable then backs off for a full TTL instead of spawning a thread on
    every single page load.
    """
    global _last_attempt

    if not is_configured():
        return
    if _last_attempt is not None and \
            time.monotonic() - _last_attempt < PROGRESS_TTL_SECONDS:
        return
    if _progress_lock.locked():
        return
    _last_attempt = time.monotonic()

    def _run() -> None:
        try:
            refresh_progress()
        except Exception as e:
            print(f"[sheet] background tick read failed: {e}")

    threading.Thread(target=_run, daemon=True).start()


def push(event: dict) -> str:
    """Put one show, its requests and its checklist into the sheet. Never raises."""
    if not is_configured():
        return UNCONFIGURED

    username = _writer()
    spreadsheet_id = sheet_id()
    try:
        ensure_tabs(username, spreadsheet_id)
        _upsert_all(username, spreadsheet_id, EVENTS, [event_row(event)])
        _upsert_all(username, spreadsheet_id, REQUESTS, request_rows(event))

        # A retired show keeps its record and loses its work.
        if retired(event):
            _drop_checklist(username, spreadsheet_id, event)
        else:
            _upsert_all(username, spreadsheet_id, CHECKLIST,
                        checklist_rows(event))
            _tidy_checklist(username, spreadsheet_id)
        return SYNCED
    except Exception as e:
        # **Every** exception, not a named few. The list used to be
        # `(GoogleAuthError, RuntimeError, KeyError, ValueError)`, which misses
        # the case that matters most: `authorised_request` uses httpx, so an
        # unreachable Google raises `httpx.ConnectError` — a subclass of none of
        # them. It escaped, and the route answered 500 *after* the registration
        # was committed and the admin emailed, so the person retried into "you
        # have already registered interest in this show".
        #
        # A blanket catch is the right shape here precisely because the contract
        # is absolute: the record is already saved, and a spreadsheet being
        # unreachable must never undo it.
        print(f"[sheet] could not update {event.get('name', '?')}: {e}")
        return FAILED
