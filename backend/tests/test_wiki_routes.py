"""Route-level tests for `/api/wiki` — the contract the Learn surfaces depend on.

The reading rules are pinned in `test_wiki.py`. This file covers only what the
transport layer owes the frontend:

  * the response shape, field by field, because the UI is built against it;
  * a missing page reads as 404, so a stale link shows "not found" rather than
    rendering an empty page as though it were real;
  * the corpus is company-internal, so an unauthenticated caller gets nothing.
"""
from __future__ import annotations

import base64
import json
import os
import tempfile

import itsdangerous
import pytest

# Defaults, never overwrites — another route-test module may have imported main
# first, and the cookie must be signed with whatever secret the app loaded.
os.environ.setdefault("DATA_ROOT", tempfile.mkdtemp())
os.environ.setdefault("SESSION_SECRET", "wiki-routes-test-secret-not-real")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from agents.shared import sources, wiki  # noqa: E402
from auth import require_authed  # noqa: E402

USER = "wiki-test-user"

TERM = """---
id: t1
title: Holdover
type: glossary
aliases: [Free-running]
tags: [holdover, ocxo]
---

How long a clock keeps time after losing its reference.
"""

DYNAMIC_TERM = """---
id: t2
title: Jitter Attenuation
description: Smoothing short-term phase noise.
type: glossary
first_seen_in: call-live
source_title: A discovery call
contributed_by: wiki-test-user
created_at: 2026-06-02T11:00:00+00:00
---

Smoothing short-term phase noise.
"""

PRODUCT = """---
title: open-time-appliance
slug: open-time-appliance
tagline: Grandmaster clock platform.
category: hardware
tags: ["products", "hardware"]
---

# open-time-appliance

Three oscillator grades, and [[Holdover]] measured in nanoseconds. See [[Nothing Here]].
"""


def _session_cookie(user: str = USER) -> str:
    payload = base64.b64encode(json.dumps({"user": user}).encode()).decode()
    return itsdangerous.TimestampSigner(os.environ["SESSION_SECRET"]).sign(payload).decode()


@pytest.fixture
def vault(tmp_path, monkeypatch):
    root = tmp_path / "vault"
    for rel, text in {
        "company/glossary/holdover.md": TERM,
        "company/products/hardware/open-time-appliance.md": PRODUCT,
        "dynamic/glossary/jitter-attenuation.md": DYNAMIC_TERM,
    }.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(wiki, "vault_dir", lambda: root)
    # The page endpoint joins provenance against the call store; give it one.
    monkeypatch.setattr(
        sources, "call_records",
        lambda _sessions: {
            "call-live": sources.CallRecord("call-live", "A discovery call", USER),
        },
    )
    wiki.invalidate_cache()
    yield root
    wiki.invalidate_cache()


@pytest.fixture
def client(vault):
    main.app.dependency_overrides[require_authed] = lambda: {"username": USER, "access": "admin"}
    with TestClient(main.app, cookies={"cadence_session": _session_cookie()}) as c:
        yield c
    main.app.dependency_overrides.clear()


def test_index_shape(client):
    body = client.get("/api/wiki/index").json()
    assert body["total"] == 3
    assert body["types"] == ["glossary", "product"]
    assert "holdover" in body["tags"]

    node = next(n for n in body["nodes"] if n["slug"] == "product/open-time-appliance")
    assert node == {
        "slug": "product/open-time-appliance",
        "title": "Open Time Appliance",
        "type": "product",
        "pillar": "company",
        "tags": ["products", "hardware"],
        "aliases": [],
        "tagline": "Grandmaster clock platform.",
        # Attribution: presentation only. A company-tier page has no contributor,
        # and `mine` is false for everyone — it never hides a page from anybody.
        "contributed_by": "",
        "mine": False,
    }


def test_search_reports_the_match_reason(client):
    body = client.get("/api/wiki/search", params={"q": "Free-running"}).json()
    assert body["hits"][0]["node"]["slug"] == "glossary/holdover"
    assert body["hits"][0]["matched_on"] == "alias"


def test_search_with_no_query_is_empty_not_everything(client):
    """An empty box must not dump the corpus — the UI shows a prompt instead."""
    assert client.get("/api/wiki/search", params={"q": ""}).json()["hits"] == []


def test_page_carries_blocks_links_and_backlinks(client):
    body = client.get("/api/wiki/page/product/open-time-appliance").json()
    assert body["title"] == "Open Time Appliance"
    assert [b["kind"] for b in body["blocks"]] == ["para"]

    links = {link["target"]: link["slug"] for link in body["links"]}
    assert links["Holdover"] == "glossary/holdover"
    assert links["Nothing Here"] is None
    assert body["unresolved"] == ["Nothing Here"]

    back = client.get("/api/wiki/page/glossary/holdover").json()
    assert [n["slug"] for n in back["backlinks"]] == ["product/open-time-appliance"]


def test_missing_page_is_404(client):
    assert client.get("/api/wiki/page/glossary/no-such-term").status_code == 404


def test_slug_with_a_slash_survives_routing(client):
    """Slugs are `type/name`, so the route must accept the separator as data."""
    assert client.get("/api/wiki/page/glossary/holdover").status_code == 200


def test_knowledge_is_not_public(vault):
    """No dependency override — company knowledge must require a session."""
    with TestClient(main.app) as anon:
        for path in ("/api/wiki/index", "/api/wiki/search?q=holdover"):
            assert anon.get(path).status_code in (401, 403), path


# --- provenance -------------------------------------------------------------

def test_a_page_grown_from_a_call_says_which_call(client):
    body = client.get("/api/wiki/page/glossary/jitter-attenuation").json()
    assert body["sources"] == [
        {
            "call_id": "call-live",
            "title": "A discovery call",
            "contributed_by": "wiki-test-user",
            "captured_at": "2026-06-02T11:00:00+00:00",
            "status": "open",
        }
    ]


def test_a_company_page_cites_nothing(client):
    """Company truth is the company's own; the pillar mark already says so."""
    assert client.get("/api/wiki/page/glossary/holdover").json()["sources"] == []


def test_the_index_is_not_burdened_with_provenance(client):
    """`/index` and backlinks reuse the node shape, and stay lean."""
    node = client.get("/api/wiki/index").json()["nodes"][0]
    assert "sources" not in node


def test_a_dynamic_page_uses_its_description_as_a_tagline(client):
    """The runtime writers set `description`; reading only `tagline` showed blank."""
    body = client.get("/api/wiki/page/glossary/jitter-attenuation").json()
    assert body["tagline"] == "Smoothing short-term phase noise."
