from __future__ import annotations
"""The Google grant — one OAuth flow, shared by every Google client.

Split out of ``google_calendar.py`` in Phase 4a. That module owned the scopes, the
token file, the refresh and the code exchange, which was fine while Calendar was the
only consumer; with Gmail arriving, the shared grant would have lived in a module
named after one of the things using it.

Raw httpx and the OAuth 2.0 flow directly — no Authlib for a flow this small. Tokens
are per-user in ``google_tokens.json``, keyed by username, so each person connects
their own account. The transient ``state`` lives in the session, not here.

**Synchronous, like ``integrations/lusha.py``.** The callers are sync — an agent's
`decide()` runs inside a sync FastAPI route, which FastAPI already dispatches to a
threadpool, so blocking I/O belongs there. The async form this grew from existed only
because the Calendar client was written async, and its one caller was retired in
Stage 3.3. One HTTP style across the integrations means no `asyncio.run` inside sync
agent code and no event-loop hazard to reason about.

**The token file and its path are unchanged by the split**, so grants made before it
keep working — until the scope change forces a re-consent, which is a separate thing
and is what `missing_scopes()` exists to report.

Required env vars (in ~/.env):
  GOOGLE_CLIENT_ID
  GOOGLE_CLIENT_SECRET
  GOOGLE_REDIRECT_URI  (e.g. http://localhost:8000/api/integrations/google/callback)
"""
import json
import os
import time
import urllib.parse
from typing import Any, Iterable

import httpx

from paths import sales_google_tokens

TOKENS_FILE = sales_google_tokens()

OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
OAUTH_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"
EMAIL_SCOPE = "https://www.googleapis.com/auth/userinfo.email"
#: Create and update drafts. **Not** `gmail.modify` — this scope cannot read the
#: mailbox and cannot send, so "the human always sends" is enforced by Google rather
#: than by our own discipline. Widening it is a deliberate decision with a
#: re-consent attached, not a convenience; see the Phase 4a plan for why the
#: draft-vs-sent learning that would need a read scope is deferred.
GMAIL_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
#: Read and write spreadsheets — the shared events working document, which the
#: people who decide and deliver an event use because most of them have no
#: Cadence account. **Not** a Drive scope: the Sheets API creates the file under
#: the connecting account, and sharing it is a permissions decision a person
#: should make once in Drive rather than one an API makes on their behalf.
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"

#: Everything the grant asks for. Adding to this list makes every user re-consent,
#: so it is asserted by test rather than left to a reviewer to notice.
SCOPES = [CALENDAR_SCOPE, EMAIL_SCOPE, GMAIL_COMPOSE_SCOPE, SHEETS_SCOPE]


class GoogleAuthError(RuntimeError):
    """The user is not connected, or their grant cannot be refreshed."""


def _client_config() -> tuple[str, str, str]:
    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
    redirect_uri = os.getenv(
        "GOOGLE_REDIRECT_URI", "http://localhost:8000/api/integrations/google/callback",
    )
    return client_id, client_secret, redirect_uri


def is_configured() -> bool:
    """Whether the operator has set the client up. Distinct from being connected."""
    cid, csec, _ = _client_config()
    return bool(cid and csec)


def redirect_host() -> str:
    """Hostname (no scheme/port) of the configured OAuth redirect URI."""
    from urllib.parse import urlparse

    _, _, redirect_uri = _client_config()
    return (urlparse(redirect_uri).hostname or "").lower()


def build_authorize_url(state: str) -> str:
    """The consent URL.

    `include_granted_scopes` means a re-consent keeps what was already granted, so
    adding Gmail does not silently drop Calendar.
    """
    cid, _, redirect_uri = _client_config()
    params = {
        "client_id": cid,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{OAUTH_AUTH_URL}?{urllib.parse.urlencode(params)}"


def exchange_code(code: str) -> dict[str, Any]:
    """Trade the callback code for tokens, and record what was actually granted.

    Google returns the granted scopes, which may be fewer than asked for — a user can
    decline one at the consent screen. Storing them is what lets a surface say
    "connected, but reconnect for Gmail" instead of a flat "connected" that fails on
    first use.
    """
    cid, csec, redirect_uri = _client_config()
    with httpx.Client(timeout=15) as client:
        resp = client.post(
            OAUTH_TOKEN_URL,
            data={
                "client_id": cid,
                "client_secret": csec,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
        resp.raise_for_status()
        token = resp.json()

        ui = client.get(
            OAUTH_USERINFO_URL,
            headers={"Authorization": f"Bearer {token['access_token']}"},
        )
        email = ui.json().get("email", "") if ui.status_code == 200 else ""

    return {
        "access_token": token["access_token"],
        "refresh_token": token.get("refresh_token", ""),
        "expires_at": int(time.time()) + int(token.get("expires_in", 3600)) - 30,
        "email": email,
        "scopes": (token.get("scope") or "").split(),
    }


def _refresh(creds: dict[str, Any]) -> dict[str, Any]:
    cid, csec, _ = _client_config()
    with httpx.Client(timeout=15) as client:
        resp = client.post(
            OAUTH_TOKEN_URL,
            data={
                "client_id": cid,
                "client_secret": csec,
                "refresh_token": creds["refresh_token"],
                "grant_type": "refresh_token",
            },
        )
        resp.raise_for_status()
        token = resp.json()
    return {
        **creds,
        "access_token": token["access_token"],
        "expires_at": int(time.time()) + int(token.get("expires_in", 3600)) - 30,
        # A refresh response may restate the scopes; keep what we had if it does not.
        "scopes": (token.get("scope") or "").split() or creds.get("scopes") or [],
    }


def ensure_fresh_token(creds: dict[str, Any]) -> dict[str, Any]:
    """The same creds with a valid access token.

    A grant with no refresh token is returned as-is rather than raising — the caller
    will get a 401 from Google, which is the honest error, and pretending we knew
    better here would hide a grant that needs redoing.
    """
    if creds.get("expires_at", 0) > int(time.time()):
        return creds
    if not creds.get("refresh_token"):
        return creds
    return _refresh(creds)


# --------------------------------------------------------------------------- #
# Token storage
# --------------------------------------------------------------------------- #

def _load_all_tokens() -> dict[str, dict[str, Any]]:
    if not TOKENS_FILE.exists():
        return {}
    try:
        return json.loads(TOKENS_FILE.read_text())
    except Exception:
        return {}


def _save_all_tokens(tokens: dict[str, dict[str, Any]]) -> None:
    TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKENS_FILE.write_text(json.dumps(tokens, indent=2))


def get_creds(username: str) -> dict[str, Any] | None:
    return _load_all_tokens().get(username)


def set_creds(username: str, creds: dict[str, Any]) -> None:
    tokens = _load_all_tokens()
    tokens[username] = creds
    _save_all_tokens(tokens)


def clear_creds(username: str) -> None:
    tokens = _load_all_tokens()
    if username in tokens:
        del tokens[username]
        _save_all_tokens(tokens)


def granted_scopes(username: str) -> list[str]:
    """What this user's grant actually covers.

    Empty for a grant made before Phase 4a recorded scopes — which reads the same as
    "nothing granted" and is therefore reported as missing everything, correctly:
    such a grant predates Gmail and does need reconnecting.
    """
    creds = get_creds(username) or {}
    scopes = creds.get("scopes")
    return list(scopes) if isinstance(scopes, list) else []


def missing_scopes(username: str, required: Iterable[str] = ()) -> list[str]:
    """Which of `required` this user has not granted. Defaults to the full set."""
    wanted = list(required) or SCOPES
    held = set(granted_scopes(username))
    return [scope for scope in wanted if scope not in held]


def can_draft_email(username: str) -> bool:
    """Whether this user's grant covers Gmail drafting."""
    return not missing_scopes(username, [GMAIL_COMPOSE_SCOPE])


# --------------------------------------------------------------------------- #
# Authorised requests
# --------------------------------------------------------------------------- #

def authorised_request(
    username: str,
    method: str,
    url: str,
    *,
    json_body: dict | None = None,
    timeout: int = 15,
) -> dict[str, Any]:
    """One authorised call to a Google API, refreshing the token first if needed.

    Owned here so both clients share the refresh-and-persist dance rather than each
    remembering to do it. Returns the parsed body; raises `GoogleAuthError` when the
    user is not connected and `RuntimeError` with Google's own words on an API error,
    because a Google message is more use to whoever reads the log than ours would be.
    """
    creds = get_creds(username)
    if not creds:
        raise GoogleAuthError("Not connected to Google.")

    creds = ensure_fresh_token(creds)
    set_creds(username, creds)

    with httpx.Client(timeout=timeout) as client:
        resp = client.request(
            method,
            url,
            headers={"Authorization": f"Bearer {creds['access_token']}"},
            json=json_body,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Google API error: {resp.status_code} {resp.text[:300]}")
        if not resp.content:
            return {}
        return resp.json()
