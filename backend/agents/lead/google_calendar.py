from __future__ import annotations
"""Google Calendar OAuth + event creation.

Uses raw httpx + the OAuth 2.0 flow directly (no Authlib dependency needed for
this minimal flow). Tokens are persisted per-user in
`backend/agents/lead/data/google_tokens.json`, keyed by username, so each user
connects their own calendar independently. The transient OAuth `state` still
lives in the session.

Required env vars (in ~/.env):
  GOOGLE_CLIENT_ID
  GOOGLE_CLIENT_SECRET
  GOOGLE_REDIRECT_URI  (e.g. http://localhost:8000/api/lead/google/callback)
"""
import json
import os
import time
import urllib.parse
from pathlib import Path
from typing import Any

import httpx
from fastapi import Request

from paths import lead_google_tokens

TOKENS_FILE = lead_google_tokens()

OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
OAUTH_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
CALENDAR_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/userinfo.email",
]

# Touch -> Google Calendar colourId
TOUCH_COLOURS = {1: "2", 2: "10", 3: "7", 4: "9", 5: "3"}


def _client_config() -> tuple[str, str, str]:
    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/lead/google/callback")
    return client_id, client_secret, redirect_uri


def is_configured() -> bool:
    cid, csec, _ = _client_config()
    return bool(cid and csec)


def redirect_host() -> str:
    """Hostname (no scheme/port) of the configured OAuth redirect URI."""
    from urllib.parse import urlparse
    _, _, redirect_uri = _client_config()
    return (urlparse(redirect_uri).hostname or "").lower()


def build_authorize_url(state: str) -> str:
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


async def exchange_code(code: str) -> dict[str, Any]:
    cid, csec, redirect_uri = _client_config()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
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

        ui = await client.get(
            OAUTH_USERINFO_URL,
            headers={"Authorization": f"Bearer {token['access_token']}"},
        )
        email = ui.json().get("email", "") if ui.status_code == 200 else ""

    return {
        "access_token": token["access_token"],
        "refresh_token": token.get("refresh_token", ""),
        "expires_at": int(time.time()) + int(token.get("expires_in", 3600)) - 30,
        "email": email,
    }


async def _ensure_fresh_token(creds: dict[str, Any]) -> dict[str, Any]:
    if creds.get("expires_at", 0) > int(time.time()):
        return creds
    cid, csec, _ = _client_config()
    if not creds.get("refresh_token"):
        return creds  # caller will hit 401, surface error
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
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
    }


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


async def create_event(
    username: str,
    *,
    summary: str,
    description: str,
    start_iso: str,
    end_iso: str,
    touch: int,
    timezone: str = "UTC",
) -> dict[str, Any]:
    creds = get_creds(username)
    if not creds:
        raise RuntimeError("Not connected to Google Calendar")
    creds = await _ensure_fresh_token(creds)
    set_creds(username, creds)

    body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_iso, "timeZone": timezone},
        "end": {"dateTime": end_iso, "timeZone": timezone},
        "colorId": TOUCH_COLOURS.get(touch, "1"),
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            CALENDAR_EVENTS_URL,
            headers={"Authorization": f"Bearer {creds['access_token']}"},
            json=body,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Google Calendar error: {resp.status_code} {resp.text}")
        data = resp.json()

    return {"event_id": data.get("id"), "html_link": data.get("htmlLink")}