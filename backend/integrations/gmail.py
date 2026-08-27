from __future__ import annotations
"""Gmail — drafts, and only drafts.

Canon's platform rule is *agents draft & populate; the human always sends*. Until
Phase 4a only the second half was true: Composer and Recap produced text and told the
person to paste it somewhere. This module is the first half.

**The fence is the design, and it is deliberate that this module is short.**

- There is **no send**. Not because we chose not to call it, but because the grant
  asks for `gmail.compose`, which Google does not permit to send. "The human always
  sends" is therefore enforced outside our code, where a future refactor cannot
  quietly undo it.
- There is **no read, no list and no search**. `gmail.compose` cannot read the
  mailbox at all. Adding a reader here would need a scope change and a re-consent
  from every user, so it is a decision someone has to take on purpose rather than a
  line someone can slip in.

If you are here to add mailbox reading — the likely reason is Style Personalisation's
draft-vs-sent learning — read the Phase 4a plan first. The Gmail API deletes a draft
on send and mints a **new** message id, and Google documents no way to correlate a
manually-sent draft to its sent message. That correlation needs verifying against a
real mailbox before any scope is widened for it.

`thread_id` is returned and recorded by callers because it costs nothing now and is
the most likely key for that correlation later.

Synchronous, like ``lusha.py`` and the grant it composes — see ``google_oauth.py``
for why.

Docs: https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.drafts
"""
import base64
from email.message import EmailMessage
from typing import Any, Iterable

from integrations.google_oauth import authorised_request

DRAFTS_URL = "https://gmail.googleapis.com/gmail/v1/users/me/drafts"


class GmailError(RuntimeError):
    """A draft could not be created or changed."""


def _encode(*, to: str, subject: str, body: str, cc: Iterable[str] = ()) -> str:
    """One RFC 2822 message, base64url-encoded as the API wants it.

    `EmailMessage` does the work so that unicode subjects, long lines and address
    quoting are the standard library's problem rather than ours — the class of bug
    that hand-rolled MIME strings are made of.

    URL-safe base64, because the API's `raw` field is documented as web-safe and the
    standard alphabet's `+` and `/` are rejected.
    """
    message = EmailMessage()
    message["To"] = to
    recipients_cc = [address for address in cc if str(address).strip()]
    if recipients_cc:
        message["Cc"] = ", ".join(recipients_cc)
    message["Subject"] = subject
    message.set_content(body)

    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")


def _result(data: dict[str, Any]) -> dict[str, str]:
    """The two ids worth keeping from a Draft resource.

    `draft_id` is the stable handle — the one to update or delete by. `message_id` is
    explicitly **not** returned: it changes on every update and again on send, so
    storing it would invite exactly the stale-id bug this module's docstring warns
    about.
    """
    message = data.get("message") or {}
    return {
        "draft_id": str(data.get("id") or ""),
        "thread_id": str(message.get("threadId") or ""),
    }


def create_draft(
    username: str,
    *,
    to: str,
    subject: str,
    body: str,
    cc: Iterable[str] = (),
) -> dict[str, str]:
    """Put a draft in this user's mailbox. Returns `{draft_id, thread_id}`.

    Raises `GmailError` on anything that is not a draft coming back — including the
    grant lacking the Gmail scope, which is what a connection made before Phase 4a
    looks like from here.
    """
    if not (to or "").strip():
        raise GmailError("A draft needs a recipient.")

    try:
        data = authorised_request(
            username,
            "POST",
            DRAFTS_URL,
            json_body={"message": {"raw": _encode(to=to, subject=subject, body=body, cc=cc)}},
        )
    except Exception as e:
        raise GmailError(str(e)) from e

    result = _result(data)
    if not result["draft_id"]:
        raise GmailError("Gmail accepted the request but returned no draft id.")
    return result


def update_draft(
    username: str,
    draft_id: str,
    *,
    to: str,
    subject: str,
    body: str,
    cc: Iterable[str] = (),
) -> dict[str, str]:
    """Replace a draft's content, keeping its id.

    A whole-message replacement, which is what the API offers — there is no partial
    update of a draft's body.
    """
    if not (draft_id or "").strip():
        raise GmailError("Which draft?")
    if not (to or "").strip():
        raise GmailError("A draft needs a recipient.")

    try:
        data = authorised_request(
            username,
            "PUT",
            f"{DRAFTS_URL}/{draft_id}",
            json_body={
                "id": draft_id,
                "message": {"raw": _encode(to=to, subject=subject, body=body, cc=cc)},
            },
        )
    except Exception as e:
        raise GmailError(str(e)) from e

    return _result(data)


def delete_draft(username: str, draft_id: str) -> None:
    """Discard a draft. Used when a decision is reversed, not on a whim."""
    if not (draft_id or "").strip():
        raise GmailError("Which draft?")
    try:
        authorised_request(username, "DELETE", f"{DRAFTS_URL}/{draft_id}")
    except Exception as e:
        raise GmailError(str(e)) from e
