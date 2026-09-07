"""The acceptance bar for the events surface — the gate and the notification.

Two things are worth proving at the HTTP layer, because neither is visible in
the store:

  * **A normal employee cannot approve an event.** The page hides the button;
    that is a courtesy, not a control. `require_admin` is the control, and it is
    asserted here against a non-admin session rather than assumed.
  * **A failed email never costs somebody their registration.** The record is
    written first and the notifier's answer reported, so an unconfigured or
    unreachable SMTP server produces `emailed: false` and a saved registration —
    not a 500 and a lost form.

`DATA_ROOT` is a throwaway directory and the events database is redirected at
`tmp_path`, so no test can reach real state.
"""
import base64
import json
import os
import tempfile

import itsdangerous
import pytest

os.environ.setdefault("DATA_ROOT", tempfile.mkdtemp())
os.environ.setdefault("SESSION_SECRET", "events-route-secret-not-real")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

_SECRET = os.environ["SESSION_SECRET"]

from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import main  # noqa: E402
from agents.events import db, notify, sheet  # noqa: E402

USER = "events-test-user"
ADMIN = "events-test-admin"

# Real user profiles, so `require_authed` and `require_admin` run their actual
# logic. Overriding the dependencies instead would prove only that the override
# works — and the first version of this file did exactly that, asserting a 403
# it was getting for free as a 401.
PROFILES = {
    USER: {"username": USER, "name": "Test Employee", "access": "user", "agents": []},
    ADMIN: {"username": ADMIN, "name": "Test Admin", "access": "admin", "agents": []},
}

IBC = {
    "name": "Northgate Expo 2026",
    "location": "Sødra Hallen",
    "country": "Netherlands",
    "starts_on": "2026-09-11",
    "ends_on": "2026-09-14",
    "needs_travel": True,
    "travel_legs": [{"mode": "flight", "from": "London", "to": "Amsterdam", "nights": 3}],
    "needs_material": True,
    "material_items": ["cards", "clothing"],
    "invited": True,
    "ticket_cost": 0,
    "rationale": "Lumen Broadcast and Halvard Media run ST 2110 trucks and are both reachable there.",
    "decide_by": "2026-08-20",
}


def _session_cookie(user: str) -> str:
    payload = base64.b64encode(json.dumps({"user": user}).encode()).decode()
    return itsdangerous.TimestampSigner(_SECRET).sign(payload).decode()


@pytest.fixture(autouse=True)
def events_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "events.db")
    db.init_db()


@pytest.fixture(autouse=True)
def known_users(monkeypatch):
    """The two test people exist; nobody else does."""
    monkeypatch.setattr(auth, "find_user", lambda username: PROFILES.get(username))


#: Enough for `notifications.is_configured()` to say yes. Set only by the tests
#: that are about a configured Cadence — the default here is an unconfigured one,
#: which is what this machine actually is.
SMTP_SETTINGS = {
    "SMTP_HOST": "smtp.example.com",
    "SMTP_PORT": "587",
    "SMTP_USER": "cadence@example.com",
    "SMTP_PASSWORD": "not-a-real-password",
    "ADMIN_NOTIFY_EMAIL": "sam@example.com",
}


@pytest.fixture(autouse=True)
def no_spreadsheet(monkeypatch):
    """No test may reach Google.

    `push` already short-circuits without `EVENTS_SHEET_ID`, but `main.py` loads
    `backend/.env` at import — so a machine that has the id set would run these
    tests against the real sheet. The same trap the SMTP settings sprang the day
    they were filled in.
    """
    monkeypatch.delenv("EVENTS_SHEET_ID", raising=False)
    monkeypatch.setattr(sheet, "push", lambda event: sheet.UNCONFIGURED)


@pytest.fixture(autouse=True)
def silent_smtp(monkeypatch):
    """No test may reach a mail server, and none may read the developer's.

    `main.py` calls `load_dotenv()` at import, so a machine with real SMTP
    settings in `backend/.env` would run these tests against a *configured*
    Cadence and quietly change what they assert. Clearing them here makes the
    unconfigured case the default — which is what a fresh checkout is — and
    leaves `configured_smtp` to opt in. Found the day the credentials landed:
    two tests that had always passed began failing on one machine only.
    """
    for key in SMTP_SETTINGS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(notify, "send_admin_email", lambda **kwargs: False)


@pytest.fixture
def configured_smtp(monkeypatch):
    for key, value in SMTP_SETTINGS.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
def employee():
    with TestClient(main.app, cookies={"cadence_session": _session_cookie(USER)}) as c:
        yield c


@pytest.fixture
def admin():
    with TestClient(main.app, cookies={"cadence_session": _session_cookie(ADMIN)}) as c:
        yield c


class TestRegisteringInterest:
    def test_an_employee_can_register_and_the_event_appears_on_the_calendar(self, employee):
        res = employee.post("/api/events", json=IBC)
        assert res.status_code == 201
        event = res.json()["event"]
        assert event["status"] == "proposed"

        table = employee.get("/api/events").json()
        assert [e["name"] for e in table["events"]] == ["Northgate Expo 2026"]
        assert table["years"] == [2026]

    def test_a_bad_date_comes_back_as_a_readable_400(self, employee):
        res = employee.post("/api/events", json={**IBC, "starts_on": "next September"})
        assert res.status_code == 400
        assert "YYYY-MM-DD" in res.json()["detail"]

    def test_an_incomplete_show_block_is_a_400_that_names_the_field(self, employee):
        # The conditional requirements live in the store, not in the model, so a
        # missing stand cost must come back as a readable 400 rather than a 422.
        res = employee.post("/api/events", json={**IBC, "exhibiting": True})
        assert res.status_code == 400
        assert "Stand cost is required" in res.json()["detail"]

    def test_registering_twice_is_a_400_not_a_crash(self, employee):
        employee.post("/api/events", json=IBC)
        res = employee.post("/api/events", json=IBC)
        assert res.status_code == 400
        assert "already registered" in res.json()["detail"]


class TestTheEmailToTheAdmin:
    def test_the_admin_is_told_who_wants_to_go_where(
        self, employee, monkeypatch, configured_smtp
    ):
        sent = {}

        def _capture(*, subject, body, html=None):
            sent["subject"] = subject
            sent["body"] = body
            sent["html"] = html
            return True

        monkeypatch.setattr(notify, "send_admin_email", _capture)

        res = employee.post("/api/events", json=IBC)
        assert res.json()["delivery"] == "sent"
        assert res.json()["emailed"] is True
        assert USER in sent["subject"] and "Northgate Expo 2026" in sent["subject"]
        assert "Sødra Hallen" in sent["body"]
        assert "11–14 Sep 2026" in sent["body"]   # the app's voice, not ISO
        assert "free" in sent["body"]          # a zero ticket price, said plainly
        assert "yes" in sent["body"]           # travel needed
        # Both halves go out: a client that will not render HTML still gets a
        # whole message rather than a fallback apology.
        assert sent["html"].startswith("<!doctype html>")

    def test_an_unreachable_mail_server_still_saves_the_registration(
        self, employee, configured_smtp
    ):
        # Configured, and the autouse fixture answers False — a server that
        # would not take it. The registration stands regardless.
        res = employee.post("/api/events", json=IBC)
        assert res.status_code == 201
        assert res.json()["delivery"] == "failed"
        assert res.json()["emailed"] is False
        assert len(employee.get("/api/events").json()["events"]) == 1

    def test_an_unconfigured_cadence_says_so_rather_than_blaming_the_server(self, employee):
        # No SMTP settings at all, which is this machine's real state. Reporting
        # a failure here would send somebody to debug a server nobody named.
        res = employee.post("/api/events", json=IBC)
        assert res.json()["delivery"] == "unconfigured"


class TestTheApprovalGate:
    def test_an_employee_cannot_approve_an_event(self, employee):
        event_id = employee.post("/api/events", json=IBC).json()["event"]["id"]
        res = employee.post(f"/api/events/{event_id}/approve", json={})
        assert res.status_code == 403

    def test_an_employee_cannot_set_the_stand_cost(self, employee):
        event_id = employee.post("/api/events", json=IBC).json()["event"]["id"]
        res = employee.patch(f"/api/events/{event_id}", json={"exhibit_cost": 1})
        assert res.status_code == 403

    def test_an_admin_approves_and_the_checklist_appears(self, employee, admin):
        event_id = employee.post("/api/events", json=IBC).json()["event"]["id"]
        res = admin.post(f"/api/events/{event_id}/approve", json={"note": "STAC clash checked"})
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "approved"
        assert body["decision_note"] == "STAC clash checked"
        assert body["checklist_total"] > 0
        assert {i["phase"] for i in body["checklist"]} >= {"Decide", "Make", "After"}


class TestTheScopeOverHTTP:
    """The store being right says nothing about a route that forgets to use it."""

    def test_an_employee_sees_only_their_own_shows(self, employee, admin):
        employee.post("/api/events", json=IBC)
        admin.post("/api/events", json={**IBC, "name": "STAC Summit",
                                        "starts_on": "2026-10-06", "ends_on": "2026-10-06"})

        mine = employee.get("/api/events").json()
        assert [e["name"] for e in mine["events"]] == ["Northgate Expo 2026"]
        assert mine["admin"] is False

    def test_the_admin_sees_both_and_is_told_so(self, employee, admin):
        employee.post("/api/events", json=IBC)
        admin.post("/api/events", json={**IBC, "name": "STAC Summit",
                                        "starts_on": "2026-10-06", "ends_on": "2026-10-06"})

        all_of_them = admin.get("/api/events").json()
        assert len(all_of_them["events"]) == 2
        assert all_of_them["admin"] is True

    def test_opening_somebody_elses_show_reads_as_absent(self, employee, admin):
        theirs = admin.post("/api/events", json=IBC).json()["event"]["id"]
        res = employee.get(f"/api/events/{theirs}")
        assert res.status_code == 400
        assert res.json()["detail"] == "No such event"

    # There is no per-item write left to scope: whether a checklist line is done
    # lives in the spreadsheet, so Cadence has nothing to refuse. The reads above
    # are the whole surface.


class TestReading:
    def test_an_unknown_event_is_a_400_with_a_sentence(self, employee):
        res = employee.get("/api/events/does-not-exist")
        assert res.status_code == 400
        assert res.json()["detail"] == "No such event"


class TestWhatReachesTheSpreadsheet:
    """Every route that changes a show has to tell the shared document.

    Two did not, and both failed the same way — silently, leaving a row that
    reads as live long after the decision went the other way.
    """

    def _pushes(self, monkeypatch) -> list:
        pushed: list = []
        monkeypatch.setattr(sheet, "push", lambda event: pushed.append(event) or sheet.SYNCED)
        return pushed

    def test_deleting_a_show_reaches_the_sheet(self, employee, admin, monkeypatch):
        # This was the one mutating route that pushed nothing, so a cancelled
        # show kept its rows and somebody could still have ordered for it.
        event_id = employee.post("/api/events", json=IBC).json()["event"]["id"]
        pushed = self._pushes(monkeypatch)

        assert admin.delete(f"/api/events/{event_id}").status_code == 200
        assert [e["id"] for e in pushed] == [event_id]
        assert pushed[0]["deleted_at"]

    def test_declining_a_place_reaches_the_sheet(self, employee, admin, monkeypatch):
        event_id = employee.post("/api/events", json=IBC).json()["event"]["id"]
        registration = admin.get(f"/api/events/{event_id}").json()["registrations"][0]
        pushed = self._pushes(monkeypatch)

        res = admin.post(f"/api/events/registrations/{registration['id']}/decline")
        assert res.status_code == 200
        # Approving a place already pushed; declining one left Operations a row
        # saying somebody was going.
        assert len(pushed) == 1

    def test_a_failing_spreadsheet_does_not_undo_the_delete(self, employee, admin,
                                                            monkeypatch):
        event_id = employee.post("/api/events", json=IBC).json()["event"]["id"]
        monkeypatch.setattr(sheet, "push",
                            lambda event: (_ for _ in ()).throw(RuntimeError("no")))

        # `push` swallows its own failures; this proves the route does not add a
        # way for Google to refuse a deletion that has already happened.
        with pytest.raises(RuntimeError):
            admin.delete(f"/api/events/{event_id}")
        assert admin.get("/api/events").json()["events"] == []

    def test_every_route_that_changes_a_show_reaches_the_sheet(self, employee, admin,
                                                              monkeypatch):
        # The gap this closes twice over: `PATCH` changes the columns three
        # teams read — dates, exhibiting, stand cost, quote contact — and said
        # nothing, so Alex and Nils decided off yesterday's figures.
        event_id = employee.post("/api/events", json=IBC).json()["event"]["id"]
        pushed = self._pushes(monkeypatch)

        for call in (
            lambda: admin.patch(f"/api/events/{event_id}", json={"exhibiting": True}),
            lambda: admin.post(f"/api/events/{event_id}/approve", json={"note": "go"}),
            lambda: admin.post(f"/api/events/{event_id}/clone",
                               json={"year": 2027, "starts_on": "2027-09-10",
                                     "ends_on": "2027-09-13"}),
        ):
            before = len(pushed)
            res = call()
            assert res.status_code < 400, res.text
            assert len(pushed) == before + 1, f"{res.request.url} pushed nothing"

    def test_the_outcome_of_the_push_comes_back_on_the_show(self, employee, monkeypatch):
        # It used to be computed and dropped, so a failed push was visible only
        # in a log — while the email's identical three states were reported.
        monkeypatch.setattr(sheet, "push", lambda event: sheet.FAILED)
        body = employee.post("/api/events", json=IBC).json()
        assert body["event"]["sheet"] == sheet.FAILED

    def test_the_calendar_says_where_the_spreadsheet_is(self, employee, monkeypatch):
        # The page tells people to tick things off in the shared spreadsheet and
        # had no way of saying where that is.
        monkeypatch.setattr(sheet, "url", lambda: "https://docs.google.com/x")
        assert employee.get("/api/events").json()["sheet_url"] == \
            "https://docs.google.com/x"

    def test_no_spreadsheet_means_no_link_rather_than_a_broken_one(self, employee):
        assert employee.get("/api/events").json()["sheet_url"] is None

    def test_the_calendar_asks_for_a_fresh_read_of_the_ticks(self, employee, monkeypatch):
        # The only clock this application has — there is no scheduler.
        asked: list = []
        monkeypatch.setattr(sheet, "maybe_refresh_progress", lambda: asked.append(1))

        assert employee.get("/api/events").status_code == 200
        assert asked == [1]


class TestTheLazyReadBack:
    """It must not hit Google on every page load, nor retry a dead one.

    And it must actually run after a restart: `time.monotonic()` counts from
    process start here, so a "never asked" sentinel of zero would read as "asked
    a moment ago" and hold the sheet off for a whole TTL every time the server
    came up. That is the first thing below.
    """

    def test_a_freshly_started_server_reads_straight_away(self, monkeypatch):
        monkeypatch.setattr(sheet, "_last_attempt", None)
        spawned = self._armed(monkeypatch)
        sheet.maybe_refresh_progress()
        assert len(spawned) == 1


    @pytest.fixture(autouse=True)
    def _forget_the_last_attempt(self, monkeypatch):
        monkeypatch.setattr(sheet, "_last_attempt", None)

    def _armed(self, monkeypatch) -> list:
        spawned: list = []
        # A configured Cadence, without needing a Google grant to exist: the
        # thing under test is the pacing, not the connection.
        monkeypatch.setattr(sheet, "is_configured", lambda: True)
        monkeypatch.setattr(sheet.threading, "Thread",
                            lambda target, daemon: type("T", (), {
                                "start": lambda _self: spawned.append(target)})())
        return spawned

    def test_an_unconfigured_cadence_reads_nothing(self, monkeypatch):
        spawned: list = []
        monkeypatch.setattr(sheet, "is_configured", lambda: False)
        monkeypatch.setattr(sheet.threading, "Thread",
                            lambda **k: spawned.append(1))
        sheet.maybe_refresh_progress()
        assert spawned == []

    def test_it_reads_once_and_then_holds_off(self, monkeypatch):
        spawned = self._armed(monkeypatch)
        sheet.maybe_refresh_progress()
        sheet.maybe_refresh_progress()
        assert len(spawned) == 1

    def test_a_spreadsheet_that_is_down_backs_off_rather_than_retrying(self, monkeypatch):
        # The stamp is set before the call, not after. Otherwise an outage means
        # a thread per page load, all of them failing.
        spawned = self._armed(monkeypatch)
        monkeypatch.setattr(sheet, "refresh_progress",
                            lambda: (_ for _ in ()).throw(RuntimeError("Google says no")))
        sheet.maybe_refresh_progress()
        spawned[0]()          # the daemon body, run here so its failure is visible
        sheet.maybe_refresh_progress()
        assert len(spawned) == 1
