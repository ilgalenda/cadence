"""The Google connection — `/api/integrations/google`.

Connecting, checking and disconnecting a user's Google account. Lifted out of the
retired `agents/lead` router in Stage 3.3: OAuth is not something a sales agent
owns, and Phase 4's Gmail will connect through this same grant rather than a second
one.

**The callback path is registered with Google.** `/callback` here must match the
authorised redirect URI in the Google Cloud Console and `GOOGLE_REDIRECT_URI` in
the environment. Changing this prefix means changing both, or the flow fails with
`redirect_uri_mismatch`.

Per-user by construction: the grant is stored against the username that started
it, and the callback refuses a session that is not the one that began the flow —
so a redirect landing in someone else's browser cannot bind their account.
"""
from __future__ import annotations

import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from auth import require_authed
from integrations import google_oauth as grant

router = APIRouter(prefix="/api/integrations/google", tags=["integrations"])

#: Where the browser is sent once the exchange is done, one way or the other. The
#: page reads `ok` / `error` from the query string and says what happened.
CALLBACK_PAGE = "/work/integrations/callback"


@router.get("/status")
def status(user: dict = Depends(require_authed)):
    """Whether Google is configured on this deployment, and connected for this user.

    `configured` is about the operator; `connected` is about the person. They fail
    for different reasons and the page says something different for each.

    `can_draft_email` is the third case, and the reason it exists: Phase 4a added a
    Gmail scope to the grant, so a connection made before it is *connected* and still
    unable to draft. Reporting only "connected" would leave the page telling the
    truth and the feature failing anyway.
    """
    username = user["username"]
    creds = grant.get_creds(username)
    return {
        "configured": grant.is_configured(),
        "connected": bool(creds),
        "email": (creds or {}).get("email", ""),
        "can_draft_email": bool(creds) and grant.can_draft_email(username),
        "missing_scopes": grant.missing_scopes(username) if creds else [],
    }


@router.get("/connect")
def connect(request: Request, user: dict = Depends(require_authed)):
    """Start the OAuth flow.

    The `state` and the username go into the session, not the URL: they are what
    the callback checks the redirect against.
    """
    if not grant.is_configured():
        raise HTTPException(
            status_code=500,
            detail="Google OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
        )
    state = secrets.token_urlsafe(24)
    request.session["google_oauth_state"] = state
    request.session["google_oauth_user"] = user["username"]
    return RedirectResponse(grant.build_authorize_url(state))


@router.get("/callback")
def callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    """Finish the OAuth flow and store the grant.

    Every failure redirects rather than raising: the caller here is a browser
    mid-redirect from Google, and a JSON error would leave the person on a blank
    page with no way back.
    """
    if error:
        return RedirectResponse(f"{CALLBACK_PAGE}?error={error}")

    saved_state = request.session.pop("google_oauth_state", None)
    saved_user = request.session.pop("google_oauth_user", None)

    if not code or not state or state != saved_state or not saved_user:
        return RedirectResponse(f"{CALLBACK_PAGE}?error=invalid_state")
    # The person who finished the flow must be the one who started it.
    if request.session.get("user") != saved_user:
        return RedirectResponse(f"{CALLBACK_PAGE}?error=user_mismatch")

    try:
        creds = grant.exchange_code(code)
        grant.set_creds(saved_user, creds)
    except Exception as e:  # noqa: BLE001 — any failure has to land on the page
        return RedirectResponse(f"{CALLBACK_PAGE}?error={str(e)[:120]}")

    return RedirectResponse(f"{CALLBACK_PAGE}?ok=1")


@router.post("/disconnect")
def disconnect(user: dict = Depends(require_authed)):
    """Forget this user's grant. Their calendar is untouched."""
    grant.clear_creds(user["username"])
    return {"ok": True}
