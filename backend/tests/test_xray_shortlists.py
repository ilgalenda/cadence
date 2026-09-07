"""Route-level tests for X-ray's shortlists — the contract the page depends on.

The endpoints shipped in Stage 3.1 with no surface and no tests. R1 of the
platform redesign gives them a surface, so this locks the contract that surface
relies on:

  * the set a human ticked round-trips, *including the enrichment paid for* —
    losing a revealed email means buying it again;
  * saving with an id updates in place rather than accumulating copies, which is
    what makes "Update shortlist" honest;
  * shortlists saved by the retired `lead` X-ray (`title`/`rows`) still open with
    their people, rather than appearing empty;
  * one user can never see or delete another's;
  * "gone" reads as 404 and "illegal" as 400, because the page tells them apart.
"""
from __future__ import annotations

import base64
import json
import os
import tempfile

import itsdangerous
import pytest

# main.py reads these at import time, and another route-test module may have
# imported it already — so these are defaults, never overwrites, and the cookie
# below is signed with whatever secret the app actually loaded. Setting our own
# unconditionally would leave the suite's result dependent on file order.
# DATA_ROOT points at a throwaway directory so no test can reach real state.
os.environ.setdefault("DATA_ROOT", tempfile.mkdtemp())
os.environ.setdefault("SESSION_SECRET", "xray-shortlist-test-secret-not-real")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from agents.sales.store import prospects as storage  # noqa: E402
from auth import require_authed  # noqa: E402

USER = "shortlist-test-user"
OTHER_USER = "shortlist-other-user"

SHORTLISTS = "/api/sales/xray/shortlists"


def _session_cookie(user: str = USER) -> str:
    """The same signed cookie Starlette's SessionMiddleware would set."""
    payload = base64.b64encode(json.dumps({"user": user}).encode()).decode()
    secret = os.environ["SESSION_SECRET"]
    return itsdangerous.TimestampSigner(secret).sign(payload).decode()


@pytest.fixture
def prospects_file(tmp_path, monkeypatch):
    """Point the store at a throwaway file, for both live and sandbox reads."""
    path = tmp_path / "prospects.json"
    monkeypatch.setattr(storage, "_prospects_file", lambda sandbox=False: path)
    return path


@pytest.fixture
def client(prospects_file):
    """A client authenticated as USER."""
    main.app.dependency_overrides[require_authed] = lambda: {"username": USER, "access": "admin"}
    with TestClient(main.app, cookies={"cadence_session": _session_cookie()}) as c:
        yield c
    main.app.dependency_overrides.clear()


def _person(name: str, **extra) -> dict:
    return {"full_name": name, "job_title": "Head of Infrastructure", "company": "Northgate", **extra}


def _save(client: TestClient, **body) -> dict:
    payload = {"name": "Northgate — infrastructure", "source": "Northgate", "people": [_person("Ada Lovelace")]}
    payload.update(body)
    res = client.post(SHORTLISTS, json=payload)
    assert res.status_code == 201, res.text
    return res.json()


# ── Round trip ──────────────────────────────────────────────────────────────


def test_saved_shortlist_reopens_with_its_people(client):
    saved = _save(client, people=[_person("Ada Lovelace"), _person("Grace Hopper")])
    assert saved["count"] == 2

    reopened = client.get(f"{SHORTLISTS}/{saved['id']}").json()
    assert reopened["name"] == "Northgate — infrastructure"
    assert reopened["source"] == "Northgate"
    assert [p["full_name"] for p in reopened["people"]] == ["Ada Lovelace", "Grace Hopper"]


def test_revealed_contact_details_survive_the_round_trip(client):
    """Enrichment costs credit. A shortlist that forgets it makes you pay twice."""
    saved = _save(client, people=[
        _person("Ada Lovelace", _email="ada@northgate.com", _phone="+46 8 000 000"),
    ])

    person = client.get(f"{SHORTLISTS}/{saved['id']}").json()["people"][0]
    assert person["_email"] == "ada@northgate.com"
    assert person["_phone"] == "+46 8 000 000"


def test_index_lists_shortlists_without_their_people(client):
    _save(client, name="First", people=[_person("Ada Lovelace")])
    _save(client, name="Second", people=[_person("Grace Hopper"), _person("Ada Lovelace")])

    listed = client.get(SHORTLISTS).json()
    assert [s["name"] for s in listed] == ["Second", "First"]  # newest first
    assert [s["count"] for s in listed] == [2, 1]
    assert all("people" not in s for s in listed)
    assert all(s["updated_at"] for s in listed)


# ── Updating in place ───────────────────────────────────────────────────────


def test_saving_with_an_id_updates_rather_than_duplicates(client):
    saved = _save(client, name="Northgate — infrastructure")

    updated = _save(
        client,
        id=saved["id"],
        name="Northgate — infrastructure and networking",
        people=[_person("Ada Lovelace"), _person("Grace Hopper")],
    )
    assert updated["id"] == saved["id"]

    listed = client.get(SHORTLISTS).json()
    assert len(listed) == 1
    assert listed[0]["name"] == "Northgate — infrastructure and networking"
    assert listed[0]["count"] == 2


# ── The pre-migration era ───────────────────────────────────────────────────


def test_a_shortlist_from_the_retired_lead_xray_still_opens(client, prospects_file):
    """`lead` wrote `title`/`rows`; sales writes `name`/`people`. Both must read."""
    prospects_file.write_text(json.dumps([{
        "id": "legacy-1",
        "username": USER,
        "title": "Old prospect list",
        "company": "Northgate",
        "rows": [_person("Ada Lovelace")],
        "created_at": "01 Jul 2026",
    }]))

    listed = client.get(SHORTLISTS).json()
    assert listed == [{
        "id": "legacy-1",
        "name": "Old prospect list",
        "source": "Northgate",
        "count": 1,
        "updated_at": "01 Jul 2026",
    }]

    reopened = client.get(f"{SHORTLISTS}/legacy-1").json()
    assert [p["full_name"] for p in reopened["people"]] == ["Ada Lovelace"]


def test_an_unnamed_legacy_shortlist_still_reads(client, prospects_file):
    prospects_file.write_text(json.dumps([
        {"id": "legacy-2", "username": USER, "rows": [_person("Ada Lovelace")]},
    ]))

    assert client.get(SHORTLISTS).json()[0]["name"] == "Untitled"


# ── Isolation ───────────────────────────────────────────────────────────────


def test_one_user_cannot_see_or_open_anothers_shortlist(client, prospects_file):
    mine = _save(client, name="Mine")
    storage.save_prospect_list(
        {"name": "Theirs", "people": [_person("Grace Hopper")]},
        username=OTHER_USER,
    )

    listed = client.get(SHORTLISTS).json()
    assert [s["name"] for s in listed] == ["Mine"]

    theirs = next(s for s in storage.load_prospect_lists() if s["username"] == OTHER_USER)
    assert client.get(f"{SHORTLISTS}/{theirs['id']}").status_code == 404
    assert client.delete(f"{SHORTLISTS}/{theirs['id']}").status_code == 404

    # And theirs is untouched by the refused delete.
    assert any(s["id"] == theirs["id"] for s in storage.load_prospect_lists())
    assert client.get(f"{SHORTLISTS}/{mine['id']}").status_code == 200


def test_saving_over_anothers_shortlist_is_refused_and_destroys_nothing(client, prospects_file):
    """The write path was the one that did not check the owner.

    `ShortlistSave` accepts a client-supplied `id`, which the model it replaced
    did not — so posting somebody else's id replaced their record with yours,
    taking the emails and phone numbers Lusha had been paid for with it. Reading
    and deleting both checked; saving did not.
    """
    storage.save_prospect_list(
        {"name": "Theirs", "people": [_person("Grace Hopper", _email="grace@northgate.com")]},
        username=OTHER_USER,
    )
    theirs = next(s for s in storage.load_prospect_lists() if s["username"] == OTHER_USER)
    before = json.dumps(theirs, sort_keys=True)

    res = client.post(SHORTLISTS, json={
        "id": theirs["id"],
        "name": "Mine now",
        "people": [_person("Ada Lovelace")],
    })
    # Answered as if it never existed, so a saved shortlist cannot be probed for.
    assert res.status_code == 404, res.text

    after = [s for s in storage.load_prospect_lists() if s["id"] == theirs["id"]]
    assert len(after) == 1, "a refused save must not leave two records under one id"
    assert json.dumps(after[0], sort_keys=True) == before


# ── Refusals ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("body, because", [
    ({"name": "Nobody", "people": []}, "there is nobody to save"),
    ({"name": "   ", "people": [_person("Ada Lovelace")]}, "a blank name is not a name"),
])
def test_an_unsaveable_shortlist_is_refused(client, body, because):
    assert client.post(SHORTLISTS, json=body).status_code == 400, because


def test_opening_or_deleting_something_gone_reads_as_gone(client):
    assert client.get(f"{SHORTLISTS}/no-such-id").status_code == 404
    assert client.delete(f"{SHORTLISTS}/no-such-id").status_code == 404


def test_deleting_removes_it(client):
    saved = _save(client)

    assert client.delete(f"{SHORTLISTS}/{saved['id']}").status_code == 200
    assert client.get(SHORTLISTS).json() == []
    assert client.get(f"{SHORTLISTS}/{saved['id']}").status_code == 404
