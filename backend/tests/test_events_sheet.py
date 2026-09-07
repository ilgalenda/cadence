"""The shared spreadsheet: what lands in it.

The row builders are pure and carry the whole point of the feature — four people
who do not use Cadence read these columns — so they get the attention. The
Google conversation is faked throughout; no test may reach a spreadsheet.

The rule that matters most: **the header and the row come from one list.** A
header written by hand beside a row built in code is how a column ends up under
the wrong heading, and on a document three teams work from that is worse than a
missing column.
"""
from __future__ import annotations

import pytest

from agents.events import sheet
from integrations import google_sheets as api

#: Captured before the autouse guard replaces it, so the test that exercises the
#: real function has something to put back.
_real_delete_rows = api.delete_rows

EVENT = {
    "id": "ev1",
    "name": "Northgate Expo 2026",
    "year": 2026,
    "starts_on": "2026-09-11",
    "ends_on": "2026-09-14",
    "location": "Sødra Hallen",
    "country": "Netherlands",
    "status": "approved",
    "rationale": "Lumen Broadcast and Halvard Media run ST 2110 trucks.",
    "decide_by": "2026-08-20",
    "invited": 1,
    "exhibiting": 1,
    "exhibit_cost": 12500,
    "exhibit_currency": "GBP",
    "quote_contact_name": "RAI stand sales",
    "quote_contact_email": "stands@acme.example",
    "demo_required": 1,
    "demo_type": "vGMC + OTA Mini",
    "submission_deadline": "2026-08-29",
    "decision_note": "Broadcast is the wedge.",
    "updated_at": "2026-09-03T12:00:00+00:00",
    "registrations": [
        {"id": "r1", "username": "sam", "created_at": "2026-08-01T09:00:00+00:00",
         "intent": "exhibiting", "needs_travel": 1, "ticket_cost": 0,
         "ticket_currency": "GBP", "status": "approved",
         "decided_by": "sam", "decided_at": "2026-08-02T09:00:00+00:00"},
        {"id": "r2", "username": "theo", "created_at": "2026-08-03T09:00:00+00:00",
         "intent": "attending", "needs_travel": 0, "ticket_cost": 340,
         "ticket_currency": "EUR", "status": "proposed",
         "decided_by": None, "decided_at": None},
        {"id": "r3", "username": "roy", "created_at": "2026-08-04T09:00:00+00:00",
         "intent": "attending", "needs_travel": 1, "ticket_cost": 0,
         "ticket_currency": "GBP", "status": "declined",
         "decided_by": "sam", "decided_at": "2026-08-05T09:00:00+00:00"},
    ],
    "checklist_total": 4,
    "outstanding": 3,
    "ready": False,
    "next_due": "2026-08-21",
    "checklist": [
        # Cards belong to a person; the banner belongs to the show. That
        # distinction is what the masterplan's two-week rule turns on.
        {"id": "m1", "phase": "Ready", "item": "Business cards ordered",
         "registration_id": "r1", "owner": "Jo", "due_on": "2026-08-28"},
        {"id": "m2", "phase": "Make", "item": "Pull-up banner ordered",
         "registration_id": None, "owner": "Jo", "due_on": "2026-08-21"},
        {"id": "m3", "phase": "Make", "item": "Printed collateral ordered",
         "registration_id": None, "owner": "Jo", "due_on": "2026-08-21"},
        {"id": "m4", "phase": "Make", "item": "Hoodie or quarter-zip ordered",
         "registration_id": "r2", "owner": "", "due_on": "2026-08-21"},
    ],
}


@pytest.fixture(autouse=True)
def never_reach_google(monkeypatch):
    """No test may touch the real spreadsheet.

    `main.py` and the app read `backend/.env`, which now carries a live
    `EVENTS_SHEET_ID` — so without this the suite talks to the file the team
    uses. It already did once, and answered with a 404 from Google rather than
    an assertion. Cleared by default; the tests that exercise `push` set their
    own and fake every call.
    """
    monkeypatch.delenv("EVENTS_SHEET_ID", raising=False)
    monkeypatch.delenv("SHEET_SYNC_USER", raising=False)

    # Derived from the module rather than listed. The list was written by hand
    # and had already fallen three functions behind, which is a guard that stops
    # guarding exactly when somebody adds the call worth guarding.
    for name, value in vars(sheet.api).items():
        if name.startswith("_") or not callable(value) or name == "sheet_url":
            continue
        if getattr(value, "__module__", None) != sheet.api.__name__:
            continue
        monkeypatch.setattr(
            sheet.api, name,
            lambda *a, _n=name, **k: pytest.fail(f"a test called Google: {_n}"),
        )


def _header(tab: str) -> list:
    groups, mine = sheet.LAYOUT[tab]
    return sheet.header(groups, mine)


class TestTheColumnsAgree:
    def test_every_row_has_a_cell_for_every_cadence_heading(self):
        # Sam's columns are on the right and Cadence never fills them, so a row
        # is exactly as wide as the block it owns.
        assert len(sheet.event_row(EVENT)) == sheet.cadence_width(sheet.EVENT_GROUPS)
        for row in sheet.request_rows(EVENT):
            assert len(row) == sheet.cadence_width(sheet.REQUEST_GROUPS)
        for row in sheet.checklist_rows(EVENT):
            assert len(row) == sheet.cadence_width(sheet.CHECKLIST_GROUPS)

    def test_the_id_is_the_first_column_of_every_tab(self):
        # `_upsert` finds a row by reading column A, so the id being first is
        # not a preference — it is what makes a re-run idempotent.
        for tab in sheet.LAYOUT:
            assert _header(tab)[0] == "Cadence id"
        assert sheet.event_row(EVENT)[0] == "ev1"
        assert sheet.request_rows(EVENT)[0][0] == "r1"
        assert sheet.checklist_rows(EVENT)[0][0] == "m1"

    def test_no_heading_is_used_twice_on_a_tab(self):
        for tab in sheet.LAYOUT:
            header = _header(tab)
            assert len(set(header)) == len(header), tab


class TestTheBannersSpanTheirOwnColumns:
    """The defect this layout invites: "The decision" over the wrong six columns.

    The spans are derived from the same lists that build the cells, so this
    checks the derivation rather than a hand-count — and would fail the moment
    somebody adds a column outside a group.
    """

    def test_a_banner_cell_exists_for_every_column(self):
        for tab, (groups, mine) in sheet.LAYOUT.items():
            assert len(sheet.banner(groups, mine)) == len(_header(tab)), tab

    def test_the_spans_tile_the_row_without_gap_or_overlap(self):
        for tab, (groups, mine) in sheet.LAYOUT.items():
            at = 0
            for _, _, start, end in sheet.spans(groups, mine):
                assert start == at, tab
                at = end
            assert at == len(_header(tab)), tab

    def test_each_label_sits_over_the_first_column_it_describes(self):
        groups, mine = sheet.LAYOUT[sheet.EVENTS]
        cells = sheet.banner(groups, mine)
        for label, _, start, _ in sheet.spans(groups, mine):
            assert cells[start] == label

    def test_sams_block_starts_where_cadence_stops(self):
        # The whole safety of the layout: `write_row` reaches `cadence_width`
        # columns and no further, so Sam's block must begin exactly there.
        for tab, (groups, mine) in sheet.LAYOUT.items():
            _, _, start, end = sheet.spans(groups, mine)[-1]
            assert start == sheet.cadence_width(groups), tab
            assert end == start + len(mine), tab


class TestColumnLetters:
    """`chr(ord("A") + i)` works until column 26 and then emits `[`.

    Google rejected the resulting formula outright, which was lucky: a silently
    wrong letter would have coloured the wrong column. "Next deadline" is column
    27 on the Events tab, so this is not a hypothetical boundary.
    """

    def test_it_counts_the_way_a_spreadsheet_does(self):
        assert [sheet.a1_column(i) for i in (0, 25, 26, 27, 51, 52)] == \
            ["A", "Z", "AA", "AB", "AZ", "BA"]

    def test_every_column_of_every_tab_has_a_usable_letter(self):
        for tab, (groups, mine) in sheet.LAYOUT.items():
            for i in range(len(sheet.header(groups, mine))):
                assert sheet.a1_column(i).isalpha(), (tab, i)


class TestWhatEachReaderNeeds:
    def _cell(self, name: str) -> object:
        return sheet.event_row(EVENT)[_header(sheet.EVENTS).index(name)]

    def test_the_decision_block_carries_the_case_and_the_cost(self):
        assert "Lumen Broadcast and Halvard" in self._cell("Why we should go")
        assert self._cell("Stand cost") == "GBP 12,500.00"
        assert self._cell("Quote email") == "stands@acme.example"
        assert self._cell("Decide by") == "2026-08-20"

    def test_operations_gets_who_is_going_and_who_needs_travel(self):
        # A declined registration is not somebody going, and not somebody to
        # book a flight for.
        assert self._cell("Who is going") == "sam, theo"
        assert self._cell("Travel needed") == "sam"

    def test_the_show_row_carries_progress_rather_than_every_item(self):
        # The detail is one tab away; the show's row answers only the question
        # Cadence still asks.
        assert self._cell("Checklist") == 4
        assert self._cell("Outstanding") == 3
        assert self._cell("Next due") == "2026-08-21"

    def test_a_show_nobody_has_synced_says_so_rather_than_claiming_zero(self):
        fresh = {**EVENT, "checklist_total": 0, "outstanding": 0, "next_due": None}
        row = sheet.event_row(fresh)
        assert row[_header(sheet.EVENTS).index("Next due")] == sheet.NONE


class TestTheChecklistTab:
    """One row per thing that has to be done — the tab people work in."""

    def _cells(self, item_id: str) -> dict:
        head = _header(sheet.CHECKLIST)
        row = next(r for r in sheet.checklist_rows(EVENT) if r[0] == item_id)
        return dict(zip(head, row))

    def test_a_personal_line_names_the_person(self):
        assert self._cells("m1")["For"] == "sam"
        assert self._cells("m4")["For"] == "theo"

    def test_a_show_level_line_says_so_rather_than_leaving_it_blank(self):
        # Blank would read as "nobody has said whose this is".
        assert self._cells("m2")["For"] == "the show"

    def test_every_line_gets_its_own_row(self):
        assert len(sheet.checklist_rows(EVENT)) == 4

    def test_the_row_carries_its_phase_and_its_date(self):
        assert self._cells("m1")["Phase"] == "Ready"
        assert self._cells("m1")["Due by"] == "2026-08-28"
        assert self._cells("m2")["Due by"] == "2026-08-21"

    def test_an_unowned_line_says_so(self):
        assert self._cells("m4")["Owner"] == sheet.NONE
        assert self._cells("m1")["Owner"] == "Jo"

    def test_done_is_the_last_thing_and_outside_cadences_block(self):
        # The one cell Cadence reads and never writes. If it fell inside the
        # written block, every tick would be erased on the next change.
        groups, mine = sheet.LAYOUT[sheet.CHECKLIST]
        head = _header(sheet.CHECKLIST)
        assert "Done" in mine
        assert head.index("Done") >= sheet.cadence_width(groups)

    def test_no_row_carries_a_countdown(self):
        # A "days left" number is wrong tomorrow in a document only rewritten
        # when something changes. The date is durable; the colour is the
        # conditional format's job.
        assert not any("days" in h.lower() for h in _header(sheet.CHECKLIST))


class TestEmptyValues:
    def test_an_absent_value_reads_as_a_dash_not_as_none(self):
        # An empty cell reads as "nobody has filled this in"; a dash reads as
        # "there is nothing to fill in". On a shared document that matters.
        bare = {**EVENT, "quote_contact_name": "", "decision_note": "",
                "exhibit_cost": None, "submission_deadline": None}
        row = sheet.event_row(bare)
        for name in ("Quote contact", "Decision note", "Stand cost", "Submission deadline"):
            assert row[_header(sheet.EVENTS).index(name)] == sheet.NONE

    def test_a_free_ticket_is_free_and_an_unknown_one_is_a_dash(self):
        rows = sheet.request_rows(EVENT)
        cost = _header(sheet.REQUESTS).index("Ticket cost")
        assert rows[0][cost] == "free"
        assert rows[1][cost] == "EUR 340.00"

    def test_an_undecided_request_leaves_its_decision_cells_empty(self):
        rows = sheet.request_rows(EVENT)
        by = _header(sheet.REQUESTS).index("Decided by")
        assert rows[1][by] == sheet.NONE
        assert rows[0][by] == "sam"

    def test_every_registration_gets_a_row_including_a_declined_one(self):
        # The Requests tab is the record of what was asked and answered, so a
        # refusal belongs in it.
        assert len(sheet.request_rows(EVENT)) == 3


def _fake_sheet(monkeypatch, *, existing_ids, rewritten=None,
                deleted=None, relaid=None, batched=None) -> list:
    """A whole spreadsheet in memory, so `push` can run without Google.

    Every call is stubbed rather than some of them — the autouse guard fails a
    test that leaves one open, which is how the four-tab layout was caught
    reaching the live file.
    """
    monkeypatch.setenv("EVENTS_SHEET_ID", "sheet123")
    monkeypatch.setattr(sheet, "_writer", lambda: "sam")
    monkeypatch.setattr(sheet.api, "tab_names", lambda *a, **k: list(sheet.TABS))
    monkeypatch.setattr(sheet.api, "add_tab", lambda *a, **k: None)
    monkeypatch.setattr(sheet.api, "column", lambda *a, **k: list(existing_ids))
    appended: list = []
    # `rewritten or []` would have discarded every write: an empty list is falsy,
    # so each call appended to a fresh throwaway and the assertion saw nothing.
    writes = [] if rewritten is None else rewritten
    monkeypatch.setattr(sheet.api, "append",
                        lambda u, s, tab, rows: appended.extend(list(rows)))
    monkeypatch.setattr(sheet.api, "write_row",
                        lambda u, s, tab, n, values: writes.append((tab, n)))
    # Cadence no longer appends: it works out the row itself, because
    # `values.append` lands after the last cell holding anything at all and the
    # Done column is pre-filled with checkboxes. So every row now arrives here,
    # and `writes` records **where** each went — which is what tells an
    # overwrite from a duplicate now that both take the same path.
    monkeypatch.setattr(
        sheet.api, "write_rows",
        lambda u, s, updates: [
            (writes.append((tab, n)), appended.append(row)) for tab, n, row in updates
        ] and None)
    monkeypatch.setattr(sheet.api, "tab_ids",
                        lambda *a, **k: {tab: n for n, tab in enumerate(sheet.TABS)})
    # Recorded, not discarded: the checkbox range is a `batch_update` request and
    # nothing else can see how far down the tab it reaches.
    monkeypatch.setattr(
        sheet.api, "batch_update",
        lambda u, s, requests: (batched if batched is not None
                                else []).extend(list(requests)))
    monkeypatch.setattr(sheet.api, "delete_rows",
                        lambda u, s, sid, rows: (deleted if deleted is not None
                                                 else []).append((sid, list(rows))))
    monkeypatch.setattr(sheet, "format_sheet",
                        lambda *a, **k: (relaid if relaid is not None else []).append(1))
    return appended


class TestWhenItWillNotWrite:
    def test_no_sheet_id_means_unconfigured_rather_than_a_failure(self, monkeypatch):
        monkeypatch.delenv("EVENTS_SHEET_ID", raising=False)
        assert sheet.push(EVENT) == sheet.UNCONFIGURED

    def test_a_google_error_is_reported_not_raised(self, monkeypatch):
        # Deliberately overriding the guard: this test *is* the failure path.
        # The record is already written by the time this runs. A spreadsheet
        # being unreachable must never undo somebody's registration.
        monkeypatch.setenv("EVENTS_SHEET_ID", "sheet123")
        monkeypatch.setattr(sheet, "_writer", lambda: "sam")
        monkeypatch.setattr(sheet.api, "tab_names",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Google says no")))
        assert sheet.push(EVENT) == sheet.FAILED

    def test_a_working_push_reports_synced(self, monkeypatch):
        written = _fake_sheet(monkeypatch, existing_ids=["Cadence id"])

        assert sheet.push(EVENT) == sheet.SYNCED
        assert any(row[0] == "ev1" for row in written)   # the show
        assert any(row[0] == "r1" for row in written)    # its requests
        assert any(row[0] == "m1" for row in written)    # and its checklist

    def test_an_existing_row_is_overwritten_rather_than_duplicated(self, monkeypatch):
        # The show is already on row 4; nothing else is there yet.
        rewritten: list[tuple[str, int]] = []
        appended = _fake_sheet(
            monkeypatch, existing_ids=["Cadence id", "x", "y", "ev1"], rewritten=rewritten
        )

        sheet.push(EVENT)
        # Written where it already is, not added at the bottom a second time.
        # Rows 1 and 2 are the banner and the header, which are rewritten every
        # run by design; nothing should land below row 4.
        assert (sheet.EVENTS, 4) in rewritten
        assert max(n for tab, n in rewritten if tab == sheet.EVENTS) == 4


class TestDeletingRows:
    """The one thing this client does that destroys, so it is pinned hard.

    Both rules the API imposes are invisible when broken: nothing errors, the
    wrong rows simply go.
    """

    def _ranges(self, monkeypatch, rows):
        # The guard stubs every call in the module, this one included — and here
        # it *is* the unit under test, so the real one is put back and only the
        # transport beneath it is faked.
        sent: list = []
        monkeypatch.setattr(api, "delete_rows", _real_delete_rows)
        monkeypatch.setattr(api, "batch_update", lambda u, s, r: sent.extend(r))
        api.delete_rows("sam", "sheet123", 7, rows)
        return [r["deleteDimension"]["range"] for r in sent]

    def test_a_row_number_becomes_a_zero_based_half_open_range(self, monkeypatch):
        # Written as literals rather than derived: the off-by-one is on the end.
        assert self._ranges(monkeypatch, [4]) == [
            {"sheetId": 7, "dimension": "ROWS", "startIndex": 3, "endIndex": 4}]

    def test_rows_are_removed_bottom_up(self, monkeypatch):
        # Top-down, the second request names a row that has already shifted.
        starts = [r["startIndex"] for r in self._ranges(monkeypatch, [3, 7, 9])]
        assert starts == sorted(starts, reverse=True)

    def test_a_run_of_rows_collapses_into_one_request(self, monkeypatch):
        # Rows 4, 5 and 6 are indices 3, 4 and 5, so the half-open end is 6.
        assert self._ranges(monkeypatch, [4, 5, 6]) == [
            {"sheetId": 7, "dimension": "ROWS", "startIndex": 3, "endIndex": 6}]

    def test_runs_are_found_whatever_order_they_arrive_in(self, monkeypatch):
        assert len(self._ranges(monkeypatch, [6, 4, 12, 5])) == 2

    def test_the_same_row_twice_is_removed_once(self, monkeypatch):
        assert len(self._ranges(monkeypatch, [4, 4])) == 1

    def test_nothing_to_delete_calls_nothing(self, monkeypatch):
        # Not an empty batch: an empty `requests` list is a request Google bills
        # for and a round trip nobody needed.
        assert self._ranges(monkeypatch, []) == []
        assert self._ranges(monkeypatch, [0, -1]) == []


class TestRetiringAShow:
    """A show that is off keeps its record and loses its work.

    Sam's decision, and the split matters: Events and Requests are what was
    asked and what was answered, which next year reads. The Checklist is a list
    of things to do, and a dead show's list is things nobody should do.
    """

    DELETED = {**EVENT, "deleted_at": "2026-09-04T10:00:00+00:00"}
    DECLINED = {**EVENT, "status": "declined"}

    def _push(self, monkeypatch, event, existing_ids):
        removed: list = []
        relaid: list = []
        written = _fake_sheet(monkeypatch, existing_ids=existing_ids,
                              deleted=removed, relaid=relaid)
        assert sheet.push(event) == sheet.SYNCED
        return written, removed, relaid

    def test_a_deleted_show_says_cancelled_rather_than_what_it_was(self):
        head = _header(sheet.EVENTS)
        row = sheet.event_row(self.DELETED)
        assert row[head.index("Status")] == sheet.CANCELLED

    def test_a_declined_show_keeps_its_own_word(self):
        # Said no at the gate and called off after approval are different facts.
        head = _header(sheet.EVENTS)
        assert sheet.event_row(self.DECLINED)[head.index("Status")] == "declined"

    def test_the_person_keeps_their_answer_beside_the_shows_fate(self):
        # Overwriting the registration's status with the show's would lose what
        # somebody was actually told.
        head = _header(sheet.REQUESTS)
        row = sheet.request_rows(self.DELETED)[0]
        assert row[head.index("Status")] == "approved"
        assert row[head.index("Show status")] == sheet.CANCELLED

    def test_its_record_is_still_written(self, monkeypatch):
        written, _, _ = self._push(monkeypatch, self.DELETED, ["Cadence id"])
        assert any(row[0] == "ev1" for row in written)
        assert any(row[0] == "r1" for row in written)

    def test_its_checklist_lines_are_removed(self, monkeypatch):
        ids = ["Cadence id", "other", "m1", "m2"]
        _, removed, _ = self._push(monkeypatch, self.DELETED, ids)
        assert removed and removed[0][1] == [3, 4]

    def test_only_this_shows_lines_go(self, monkeypatch):
        # Another show's rows are interleaved; they must survive.
        ids = ["Cadence id", "m1", "someone-elses", "m2"]
        _, removed, _ = self._push(monkeypatch, self.DELETED, ids)
        assert removed[0][1] == [2, 4]

    def test_a_declined_show_loses_its_lines_too(self, monkeypatch):
        _, removed, _ = self._push(monkeypatch, self.DECLINED,
                                   ["Cadence id", "m1", "m2"])
        assert removed and removed[0][1] == [2, 3]

    def test_no_lines_in_the_sheet_means_no_call(self, monkeypatch):
        _, removed, _ = self._push(monkeypatch, self.DELETED, ["Cadence id"])
        assert removed == []

    def test_the_layout_is_rebuilt_after_rows_are_removed(self, monkeypatch):
        # Deleting rows shrinks every range that spanned them, and none of it
        # grows back on its own.
        _, _, relaid = self._push(monkeypatch, self.DELETED,
                                  ["Cadence id", "m1", "m2"])
        assert relaid

    def test_a_live_show_still_writes_its_lines_and_deletes_nothing(self, monkeypatch):
        written, removed, _ = self._push(monkeypatch, EVENT, ["Cadence id"])
        assert any(row[0] == "m1" for row in written)
        assert removed == []

    def test_a_show_brought_back_writes_its_lines_again(self, monkeypatch):
        # Declining then re-approving keeps the same line ids, so the rows that
        # were removed have to come back — unticked, which is the right loss.
        written, removed, _ = self._push(monkeypatch, EVENT, ["Cadence id"])
        assert {"m1", "m2"} <= {row[0] for row in written}


class TestTheGreying:
    """Declarative, so nothing has to remember which rows it made grey."""

    def _rule(self, tab):
        groups, mine, column = {
            sheet.EVENTS: (sheet.EVENT_GROUPS, sheet.EVENT_MINE, "Status"),
            sheet.REQUESTS: (sheet.REQUEST_GROUPS, sheet.REQUEST_MINE, "Show status"),
        }[tab]
        return sheet._retired_rule(1, groups, mine, column)

    def _formula(self, tab):
        rule = self._rule(tab)["addConditionalFormatRule"]["rule"]
        return rule["booleanRule"]["condition"]["values"][0]["userEnteredValue"]

    @pytest.mark.parametrize("tab", [sheet.EVENTS, sheet.REQUESTS])
    def test_it_matches_the_word_cadence_actually_writes(self, tab):
        # The formula and the cell drifting apart is a rule that never fires and
        # never says so.
        assert f'"{sheet.CANCELLED}"' in self._formula(tab)
        assert '"declined"' in self._formula(tab)

    @pytest.mark.parametrize("tab,column", [(sheet.EVENTS, "Status"),
                                            (sheet.REQUESTS, "Show status")])
    def test_it_points_at_that_tabs_own_status_column(self, tab, column):
        # Guards a column being inserted to the left of Status.
        letter = sheet.a1_column(_header(tab).index(column))
        assert f"${letter}3=" in self._formula(tab)

    def test_it_covers_every_column_including_sams(self, tab=sheet.EVENTS):
        rule = self._rule(tab)["addConditionalFormatRule"]["rule"]
        assert rule["ranges"][0]["endColumnIndex"] == len(_header(tab))

    def test_it_outranks_the_deadline_colours(self, monkeypatch):
        # Every rule is inserted at index 0, so the last one appended wins. A
        # past-due date must not paint red over a show that is off.
        monkeypatch.setattr(sheet, "get_creds", lambda u: {"email": "sam@x"})
        tabs = {tab: n for n, tab in enumerate(sheet.TABS)}
        emitted = sheet.format_requests(tabs, "sam@x", {"sheets": []})

        rules = [n for n, r in enumerate(emitted) if "addConditionalFormatRule" in r]
        greying = [n for n in rules
                   if sheet.CANCELLED in str(emitted[n])]
        assert greying and min(greying) > min(set(rules) - set(greying))


class TestTheCostOfAPush:
    """Google allows sixty writes a minute per user, and a push must fit.

    This was two calls per row: one to find it, one to write it. Approving a
    show with an eighteen-line checklist spent thirty-six of the sixty, and
    everything past the limit failed *silently* — the sheet simply stopped
    updating and looked out of date instead of broken. That is why this is
    counted rather than left to judgement.
    """

    def _calls(self, monkeypatch) -> dict:
        counts: dict = {}

        def count(name):
            def _fn(*a, **k):
                counts[name] = counts.get(name, 0) + 1
                if name == "column":
                    return []
                if name == "tab_ids":
                    return {tab: n for n, tab in enumerate(sheet.TABS)}
                return None
            return _fn

        monkeypatch.setenv("EVENTS_SHEET_ID", "sheet123")
        monkeypatch.setattr(sheet, "_writer", lambda: "sam")
        monkeypatch.setattr(sheet.api, "tab_names", lambda *a, **k: list(sheet.TABS))
        for name in ("add_tab", "column", "append", "write_rows", "delete_rows",
                     "tab_ids", "batch_update"):
            monkeypatch.setattr(sheet.api, name, count(name))
        assert sheet.push(EVENT) == sheet.SYNCED
        return counts

    def test_the_id_column_is_read_once_per_tab_not_once_per_row(self, monkeypatch):
        # Three tabs carry rows, plus one read to trim the Read me, plus the one
        # `_tidy_checklist` makes to find how far down the Checklist tab goes.
        # That fifth read is the price of the checkbox range describing the tab
        # rather than the show being pushed — see `_last_used_row`.
        assert self._calls(monkeypatch)["column"] == 5

    def test_a_tabs_rows_are_written_in_one_request(self, monkeypatch):
        counts = self._calls(monkeypatch)
        # One batched write for the banners, headers and Read me, then one per
        # tab that carries rows. Nothing appends any more. The `batch_update`
        # is the sort.
        assert counts.get("append") is None
        assert counts.get("write_rows") == 4
        assert counts.get("batch_update") == 1

    def test_a_whole_push_stays_well_inside_the_minute(self, monkeypatch):
        # The show above carries three registrations and a checklist, and this
        # was thirty-six requests before the batching. A dozen leaves room for
        # five shows to change in the same minute, which is the real shape of a
        # bad afternoon: a decision meeting where several are approved at once.
        assert sum(self._calls(monkeypatch).values()) <= 12


class TestLinesAddedByHand:
    """The tab became a place work is *defined*, not only progressed.

    Sam asked for the dropdowns so a line could be typed straight in. A line
    nothing counts is a line that does not exist, so Cadence has to pick these
    up — and be careful about which rows it treats as one.
    """

    HEAD = None

    def _rows(self, *rows):
        head = _header(sheet.CHECKLIST)
        self.HEAD = head
        return list(enumerate([list(r) + [""] * (len(head) - len(r)) for r in rows],
                              start=sheet.FIRST_DATA_ROW))

    def _row(self, **cells):
        head = _header(sheet.CHECKLIST)
        row = [""] * len(head)
        for name, value in cells.items():
            row[head.index(name)] = value
        return row

    def test_a_typed_row_is_picked_up(self):
        added = sheet.written_in(self._rows(
            self._row(Show="ITSF 2026", Phase="Make", Item="Roll banner", Owner="Jo")))
        assert [a["item"] for a in added] == ["Roll banner"]
        assert added[0]["row"] == sheet.FIRST_DATA_ROW

    def test_a_row_cadence_wrote_is_left_alone(self):
        # It already has an id, so it is already counted.
        rows = self._rows(self._row(**{_header(sheet.CHECKLIST)[0]: "abc"},
                                    Show="ITSF 2026", Item="Roll banner"))
        assert sheet.written_in(rows) == []

    def test_half_a_row_is_not_an_instruction(self):
        # A thousand rows carry dropdowns; somebody will pick one and stop.
        assert sheet.written_in(self._rows(self._row(Show="ITSF 2026"))) == []
        assert sheet.written_in(self._rows(self._row(Item="Roll banner"))) == []

    def test_an_empty_row_is_not_one_either(self):
        assert sheet.written_in(self._rows([""] * 3)) == []

    def test_what_was_typed_is_carried_verbatim(self):
        added = sheet.written_in(self._rows(self._row(
            Show=" ITSF 2026 ", Phase="Ready", Item=" Roll banner ",
            Owner="Jo", **{"Due by": "2026-10-19"})))[0]
        assert added["show"] == "ITSF 2026"
        assert added["item"] == "Roll banner"
        assert added["due_on"] == "2026-10-19"

    def test_the_shows_start_date_is_carried_so_two_years_can_be_told_apart(self):
        added = sheet.written_in(self._rows(self._row(
            Show="Northgate Expo", Item="Roll banner", **{"Show starts": "2027-09-10"})))[0]
        assert added["starts_on"] == "2027-09-10"

    def test_the_ticks_still_read_from_the_same_rows(self):
        rows = self._rows(
            self._row(**{_header(sheet.CHECKLIST)[0]: "m1", "Done": "TRUE"}),
            self._row(**{_header(sheet.CHECKLIST)[0]: "m2", "Done": "FALSE"}),
        )
        assert sheet.ticked(rows) == {"m1"}


class TestTheChecklistIsReadable:
    """What Sam asked for after calling the tab senseless: a spine, dropdowns
    and a view each."""

    HEAD = None

    def setup_method(self):
        self.HEAD = _header(sheet.CHECKLIST)

    def test_every_phase_has_its_own_colour(self):
        rules = sheet._phase_spine(3, self.HEAD)
        assert len(rules) == len(sheet.playbook.PHASES)
        washes = [str(r["addConditionalFormatRule"]["rule"]["booleanRule"]
                      ["format"]["backgroundColor"]) for r in rules]
        assert len(set(washes)) == len(washes)

    def test_the_spine_names_every_phase_the_playbook_has(self):
        # A phase added to the playbook and not here would render as blank.
        formulas = str(sheet._phase_spine(3, self.HEAD))
        for phase in sheet.playbook.PHASES:
            assert f'"{phase}"' in formulas, phase

    def test_the_spine_colours_the_phase_cell_not_the_row(self):
        # Colouring the row would swallow the deadline reds and the done greens.
        first = sheet._phase_spine(3, self.HEAD)[0]["addConditionalFormatRule"]
        span = first["rule"]["ranges"][0]
        assert span["endColumnIndex"] - span["startColumnIndex"] == 1

    def test_the_columns_a_line_is_joined_on_carry_a_dropdown(self):
        columns = {r["setDataValidation"]["range"]["startColumnIndex"]
                   for r in sheet._checklist_dropdowns(3, self.HEAD)}
        assert columns == {self.HEAD.index(n) for n in ("Show", "Phase", "Item", "Owner")}

    def test_the_item_list_accepts_something_it_has_never_heard_of(self):
        # Refusing it would move the work into Notes, where nothing counts it.
        rules = {r["setDataValidation"]["range"]["startColumnIndex"]:
                 r["setDataValidation"]["rule"]
                 for r in sheet._checklist_dropdowns(3, self.HEAD)}
        assert rules[self.HEAD.index("Item")]["strict"] is False
        assert rules[self.HEAD.index("Owner")]["strict"] is True

    def test_the_show_list_reads_the_events_tab_rather_than_a_copy(self):
        # A copy is a list that is wrong the moment a show is registered.
        rules = {r["setDataValidation"]["range"]["startColumnIndex"]:
                 r["setDataValidation"]["rule"]
                 for r in sheet._checklist_dropdowns(3, self.HEAD)}
        rule = rules[self.HEAD.index("Show")]
        assert rule["condition"]["type"] == "ONE_OF_RANGE"
        assert sheet.EVENTS in rule["condition"]["values"][0]["userEnteredValue"]

    def test_there_is_a_saved_view_for_each_person_and_one_for_the_work_left(self):
        titles = [v["addFilterView"]["filter"]["title"]
                  for v in sheet._owner_views(3, self.HEAD)]
        assert titles == ["Sam's lines", "Jo's lines", "Operations' lines",
                          "Still to do"]

    def test_the_outstanding_view_hides_the_ticked_rows(self):
        # `Done` is a checkbox, so its cells hold the literal TRUE. There is no
        # boolean condition type for this and the API rejects one — which took
        # the whole formatting batch down with it, since a batch is atomic.
        view = sheet._owner_views(3, self.HEAD)[-1]["addFilterView"]["filter"]
        criteria = view["criteria"][str(self.HEAD.index("Done"))]
        assert criteria == {"hiddenValues": ["TRUE"]}

    def test_a_rerun_clears_the_views_it_made_last_time(self):
        # Four copies of "Jo's lines" in the view menu is worse than none.
        existing = {"sheets": [{"properties": {"sheetId": 3},
                                "filterViews": [{"filterViewId": 7}]}]}
        tabs = {tab: n for n, tab in enumerate(sheet.TABS)}
        emitted = sheet.format_requests(tabs, "sam@x", existing)
        assert {"deleteFilterView": {"filterId": 7}} in emitted


class TestEveryRowCanBeTicked:
    """The checkbox range follows the rows, on every push.

    `format_sheet` runs from `check_sheet.py` and from retirement — never from a
    push — so the range stayed frozen at whatever the last manual run sized it
    to. Approve a third show and its lines fall past the margin with no checkbox
    on them: untickable, therefore permanently outstanding, therefore a show
    that can never read ready.
    """

    def _at(self, requests, at):
        return [r for r in requests
                if "setDataValidation" in r
                and r["setDataValidation"]["range"]["startColumnIndex"] == at]

    def test_the_range_reaches_past_the_last_row_written(self):
        head = _header(sheet.CHECKLIST)
        at = head.index("Done")
        applied = self._at(sheet._checkbox_requests(3, head, 120), at)[-1]
        assert applied["setDataValidation"]["range"]["endRowIndex"] >= 120

    def test_the_whole_column_is_cleared_before_it_is_narrowed(self):
        # Narrowing a range does not lift the validation a wider earlier run
        # left behind, so without this the rows below keep their checkboxes.
        head = _header(sheet.CHECKLIST)
        at = head.index("Done")
        first, second = [r["setDataValidation"]
                         for r in self._at(sheet._checkbox_requests(3, head, 60), at)]
        assert "rule" not in first
        assert first["range"]["endRowIndex"] == sheet.GRID_ROWS
        assert second["rule"]["condition"]["type"] == "BOOLEAN"

    def test_it_never_runs_past_the_grid(self):
        # A range that starts after its own end is refused outright, and a
        # `batchUpdate` is atomic — it would take the whole layout with it.
        head = _header(sheet.CHECKLIST)
        for request in sheet._checkbox_requests(3, head, sheet.GRID_ROWS + 500):
            span = request["setDataValidation" if "setDataValidation" in request
                           else "repeatCell"]["range"]
            assert span["startRowIndex"] <= span["endRowIndex"] <= sheet.GRID_ROWS

    def test_the_values_below_the_last_row_are_cleared(self):
        # A literal FALSE is data, and data below the last row is what sent an
        # appended row to the bottom of the grid.
        head = _header(sheet.CHECKLIST)
        cleared = [r for r in sheet._checkbox_requests(3, head, 60)
                   if "repeatCell" in r][0]
        assert cleared["repeatCell"]["range"]["startRowIndex"] == 60
        assert cleared["repeatCell"]["fields"] == "userEnteredValue"

    def test_a_push_resizes_it_rather_than_waiting_for_a_manual_format(self, monkeypatch):
        sent: list = []
        _fake_sheet(monkeypatch, existing_ids=["Cadence id"])
        monkeypatch.setattr(sheet.api, "batch_update", lambda u, s, r: sent.extend(r))

        assert sheet.push(EVENT) == sheet.SYNCED
        assert any("setDataValidation" in r for r in sent), \
            "a push must re-range the checkboxes; nothing else does it"

    def test_the_range_describes_the_tab_and_not_the_show_being_pushed(self, monkeypatch):
        """A show with no lines of its own must not clear anybody else's ticks.

        The range runs from the last used row *down to the bottom of the grid*,
        clearing the `Done` column as it goes. Sized from the rows this push
        wrote, a `proposed` show — which has no checklist yet — reported row 2,
        and every tick in the tab went with it.
        """
        sent: list = []
        # Ten shows' worth of lines already in the tab, and the show being pushed
        # owns none of them.
        _fake_sheet(monkeypatch,
                    existing_ids=["Cadence id"] + [f"m{n}" for n in range(1, 41)],
                    batched=sent)

        assert sheet.push({**EVENT, "status": "proposed", "checklist": []}) == sheet.SYNCED

        cleared = [r["repeatCell"]["range"] for r in sent if "repeatCell" in r]
        assert cleared, "the push must still tidy the tab"
        for span in cleared:
            assert span["startRowIndex"] >= 41, (
                "the clear reached into rows this push did not write — "
                f"started at {span['startRowIndex']}, tab ends at 41"
            )


class TestPushNeverRaises:
    def test_a_transport_failure_is_reported_not_raised(self, monkeypatch):
        # `authorised_request` uses httpx, so an unreachable Google raises
        # `httpx.ConnectError` — a subclass of none of the types this used to
        # catch. It escaped, and the route answered 500 *after* the
        # registration was committed and the admin emailed, so the person
        # retried into "you have already registered interest in this show".
        import httpx

        monkeypatch.setenv("EVENTS_SHEET_ID", "sheet123")
        monkeypatch.setattr(sheet, "_writer", lambda: "sam")
        monkeypatch.setattr(sheet.api, "tab_names", lambda *a, **k: (_ for _ in ()).throw(
            httpx.ConnectError("nowhere to connect to")))

        assert sheet.push(EVENT) == sheet.FAILED
