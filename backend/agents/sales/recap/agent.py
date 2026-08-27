"""Recap — the follow-up the client gets, in writing, for a human to send.

Canon's contract: *draft the client follow-up email — meeting summary + next steps
in writing*. Trigger: after Call Analysis. Owl · Sonnet. **Review gate before send.**

Two passes with the per-user style overlay on both, so the order is draft →
Owl-voice → how this person actually writes. They send it as themselves; that is
what the overlay is for. `services/outreach.two_pass` does the composing.

**Nothing here sends anything, and now it does not have to.** Every recap is filed
to the review queue as pending; on approval, Phase 4a puts a real draft in the
person's Gmail (`services/mail_draft`). They still press send — the grant cannot send,
so that is enforced by Google rather than by our restraint.

**Grounded in the reading, not the transcript.** The summary, the objections and the
agreed next steps are what a follow-up is made of, and Call Analysis has already
extracted them. Re-sending the transcript would pay for it twice and invite the model
to quote things nobody meant to be quoted.
"""
from __future__ import annotations

from agents.sales import prompts
from agents.sales.store import calls as store
from agents.services import mail_draft, outreach
from agents.services.review import ReviewQueue
from paths import sales_data

#: Where the gate's records live. Its own queue rather than Composer's: approving a
#: follow-up and approving first-touch outreach are different decisions, and mixing
#: them would make either list impossible to work through.
REVIEW_FILE = sales_data() / "recap_review.json"

#: What the gate calls these, so the queue can be filtered by kind.
REVIEW_KIND = "call_recap"

TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "call_id": {
            "type": "string",
            "description": (
                "The analysed call to write the follow-up for. Required — the recap "
                "is built from the call's reading."
            ),
        },
        "recipient": {
            "type": "string",
            "description": (
                "Optional. The client's email address. Without it the follow-up is "
                "still written and filed, but no Gmail draft can be created."
            ),
        },
        "notes": {
            "type": "string",
            "description": "Optional. Anything the follow-up should take account of.",
        },
    },
    "required": ["call_id"],
}


def _queue() -> ReviewQueue:
    """Built per call so a test pointing `sales_data` elsewhere is honoured."""
    return ReviewQueue(REVIEW_FILE)


def _usable(draft) -> tuple[dict, str | None]:
    """The recap if it came back complete, or a reason it did not.

    A subject with no body is worse than nothing: it reads as a bug to whoever has
    to send it, and showing it invites them to send it anyway.
    """
    if not isinstance(draft, dict):
        return {}, "nothing_usable"

    subject = str(draft.get("subject") or "").strip()
    body = str(draft.get("body") or "").strip()
    if not subject or not body:
        return {}, "incomplete"

    steps = [str(s).strip() for s in (draft.get("next_steps") or []) if str(s).strip()]
    return {"subject": subject, "body": body, "next_steps": steps}, None


def draft(
    username: str,
    *,
    call_id: str,
    recipient: str = "",
    notes: str = "",
    sandbox: bool = False,
) -> dict:
    """Write the follow-up for one call and file it for review.

    Returns `{"recap", "call", "review_id", "error"}`. `error` is set and `recap`
    empty when there was nothing usable to show — a half-written follow-up is never
    returned.
    """
    empty = {"recap": {}, "call": {}, "review_id": None}

    session = store.get_session(call_id, username, sandbox=sandbox)
    if session is None or session.get("type") != "call_analysis":
        return {**empty, "error": "no_such_call"}

    analysis = session.get("result")
    if not isinstance(analysis, dict) or not analysis.get("summary"):
        # Without a reading there is nothing to recap. Saying so beats writing a
        # follow-up from a title.
        return {**empty, "error": "no_usable_analysis"}

    title = session.get("title") or "Untitled call"

    try:
        composed = outreach.two_pass(
            username=username,
            draft_overlay=prompts.RECAP_DRAFT_OVERLAY,
            draft_prompt=prompts.recap_draft_prompt(
                analysis=analysis, title=title, notes=notes,
            ),
            refine_overlay=prompts.RECAP_REFINE_OVERLAY,
            refine_prompt=prompts.recap_refine_prompt,
            # They send it as themselves, so their own voice is the last word.
            personalise=True,
        )
    except Exception as e:
        return {**empty, "error": f"draft_failed: {e}"}

    recap, problem = _usable(composed)
    if problem:
        return {**empty, "error": problem}

    item = _queue().submit(
        kind=REVIEW_KIND,
        payload={
            "call_id": call_id,
            "call_title": title,
            "recap": recap,
            # Carried so the draft can be addressed at approval time. A call analysis
            # never supplies one, so this is whatever the person gave us.
            "recipient": (recipient or "").strip(),
            "notes": notes,
        },
        submitted_by=username,
    )

    return {
        "recap": recap,
        "call": {"id": call_id, "title": title},
        "review_id": item.id,
        "error": None,
    }


def pending(username: str) -> list[dict]:
    """This user's recaps awaiting their decision, newest first."""
    items = [
        item for item in _queue().pending(kind=REVIEW_KIND)
        if item.submitted_by == username
    ]
    items.sort(key=lambda i: i.created_at, reverse=True)
    return [item.to_dict() for item in items]


def decide(username: str, review_id: str, *, approve: bool, notes: str = "") -> dict:
    """Record the human decision, then put the draft in their Gmail.

    Approval means "I will send this", not "sent" — the grant cannot send.

    **The order is deliberate.** The decision is recorded first and is never undone by
    what follows: if Gmail fails, the item stays approved and carries the reason in
    `outcome.gmail_error`. Drafting first would risk a draft with no decision behind
    it; un-approving on failure would deny that the person decided.
    """
    queue = _queue()
    item = queue.get(review_id)
    if item is None or item.submitted_by != username:
        raise KeyError(review_id)

    if not approve:
        return queue.reject(review_id, reviewed_by=username, notes=notes).to_dict()

    decided = queue.approve(review_id, reviewed_by=username, notes=notes)
    return _draft_for(username, decided).to_dict()


def _draft_for(username: str, item) -> object:
    """Create the Gmail draft for an approved recap and record what happened."""
    payload = item.payload or {}
    recap = payload.get("recap") or {}

    outcome = mail_draft.draft(
        username,
        recipient=payload.get("recipient") or "",
        subject=recap.get("subject") or "",
        body=_as_email_body(recap),
    )
    return _queue().record_outcome(item.id, outcome=outcome)


def _as_email_body(recap: dict) -> str:
    """The recap as one email body.

    The next steps are appended as a list because that is how they read in a mailbox;
    the model was asked to put them in the body too, so this is belt and braces for a
    model that listed them only in the field.
    """
    body = str(recap.get("body") or "").strip()
    steps = [str(s).strip() for s in (recap.get("next_steps") or []) if str(s).strip()]
    if not steps or all(step in body for step in steps):
        return body
    return body + "\n\n" + "\n".join(f"- {step}" for step in steps)


def draft_again(username: str, review_id: str) -> dict:
    """Retry the Gmail draft for an already-approved recap.

    Needed because the queue refuses to re-decide a terminal item — correctly, since
    the decision has not changed. Only the delivery failed, so only the delivery is
    retried.
    """
    queue = _queue()
    item = queue.get(review_id)
    if item is None or item.submitted_by != username:
        raise KeyError(review_id)
    if item.status != "approved":
        raise ValueError("Only an approved recap has a draft to create.")

    return _draft_for(username, item).to_dict()


def run_as_tool(username: str, args: dict) -> str:
    """Draft a follow-up from conversation, reported in prose."""
    call_id = (args.get("call_id") or "").strip()
    if not call_id:
        return "Name the call and I will write the follow-up."

    out = draft(
        username,
        call_id=call_id,
        recipient=(args.get("recipient") or ""),
        notes=(args.get("notes") or ""),
    )

    if out["error"] == "no_such_call":
        return "I cannot find that call in your library."
    if out["error"] == "no_usable_analysis":
        return "That call has no reading to build a follow-up from — analyse it first."
    if out["error"]:
        return f"Could not write the follow-up ({out['error']})."

    recap = out["recap"]
    lines = [
        f"**Follow-up for {out['call']['title']}** — for review, nothing sent.",
        f"\n**{recap['subject']}**\n\n{recap['body']}",
    ]

    if recap["next_steps"]:
        lines.append("\n**Next steps**\n" + "\n".join(f"- {s}" for s in recap["next_steps"]))

    if mail_draft.looks_like_an_address(args.get("recipient")):
        lines.append(
            "\n_Filed for your review. Approve it and it lands as a draft in your "
            "Gmail — addressed, unsent, yours to send._"
        )
    else:
        lines.append(
            "\n_Filed for your review. Give me the client's email address and "
            "approving it will put an addressed draft in your Gmail._"
        )
    return "\n".join(lines)
