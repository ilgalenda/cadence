"""The seam between the review gate and the mailbox.

Composer and Recap both file text for review and both, once approved, should put a
draft in the person's Gmail. That is one behaviour with one set of rules, so it lives
here rather than twice.

**Two rules, and they are the whole point of the module.**

*The approval is the human's act and must survive the API.* So callers record the
decision first and draft second. A Gmail failure returns an error to report; it never
un-approves anything, because the person did approve it and the system saying
otherwise would be a lie about their action.

*A draft is created on approval, not on composition.* The gate exists so a human
decides. Filling the Drafts folder with unreviewed text is clutter at best and an
invitation to send something nobody approved at worst. Canon's "populates as Gmail
drafts" is satisfied either way; this reading is the safer one.

Nothing here sends. See ``integrations/gmail.py`` for why that is structural.
"""
from __future__ import annotations

from typing import Iterable

from integrations import gmail
from integrations import google_oauth as grant

#: What a surface should tell someone who has not connected Gmail yet. Kept here so
#: both agents say the same thing about the same state.
NOT_CONNECTED = "Google is not connected, so no draft was created."
NEEDS_RECONNECT = (
    "Your Google connection predates Gmail drafting — reconnect on Integrations and "
    "the draft will be created next time."
)
NO_RECIPIENT = "No recipient, so no draft was created."


def looks_like_an_address(value: object) -> bool:
    """A shallow check, deliberately.

    One `@` with something either side of it. Anything stricter rejects addresses
    that are perfectly valid — quoted locals, new TLDs, unicode domains — and
    anything looser just fails later at the API with a worse message. The real
    validator is Gmail.
    """
    text = str(value or "").strip()
    if "@" not in text or text != "".join(text.split()):
        return False
    local, _, domain = text.rpartition("@")
    return bool(local and "." in domain and not domain.startswith(".") and not domain.endswith("."))


def can_draft(username: str) -> tuple[bool, str]:
    """Whether a draft is possible for this user, and why not when it is not.

    Distinguishes "never connected" from "connected before the Gmail scope existed",
    because they need different things from the person and a single "not connected"
    would send them to reconnect a connection they do not have.
    """
    if grant.get_creds(username) is None:
        return False, NOT_CONNECTED
    if not grant.can_draft_email(username):
        return False, NEEDS_RECONNECT
    return True, ""


def draft(
    username: str,
    *,
    recipient: str,
    subject: str,
    body: str,
    cc: Iterable[str] = (),
) -> dict:
    """Create one Gmail draft. Returns the outcome; never raises.

    `{"gmail_draft_id", "gmail_thread_id", "gmail_error"}` — exactly one of the ids
    or the error is meaningful. Returning rather than raising is what lets the caller
    keep an approval it has already recorded.

    Every reason a draft did not happen is a *stated* reason, because "approved, and
    silently nothing in your mailbox" is the failure mode that would cost someone a
    follow-up they thought was queued.
    """
    empty = {"gmail_draft_id": "", "gmail_thread_id": ""}

    if not looks_like_an_address(recipient):
        return {**empty, "gmail_error": NO_RECIPIENT}

    allowed, why_not = can_draft(username)
    if not allowed:
        return {**empty, "gmail_error": why_not}

    try:
        created = gmail.create_draft(
            username, to=str(recipient).strip(), subject=subject, body=body, cc=cc,
        )
    except gmail.GmailError as e:
        return {**empty, "gmail_error": str(e)}
    except Exception as e:  # noqa: BLE001 — an approval must survive anything
        return {**empty, "gmail_error": f"Gmail was unreachable: {e}"}

    return {
        "gmail_draft_id": created["draft_id"],
        "gmail_thread_id": created["thread_id"],
        "gmail_error": None,
    }
