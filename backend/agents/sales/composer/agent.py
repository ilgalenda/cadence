"""Composer — the outreach touches, in Owl's voice, for a human to send.

Canon's contract: *generate the outreach touches across email · LinkedIn · call, in
Owl's voice, grounded in Research + Campaign Intelligence*. Two passes — draft, then
refine — with the per-user style overlay on both, so the order is draft → Owl-voice
→ how this person actually writes. They send it as themselves; that is what the
overlay is for.

Both of canon's groundings are real now. Research says what is true about *this*
account; Campaign Intelligence says what this *market* has already told us. The
outline is optional and the touches degrade without it rather than refusing, so a
path that skips Campaign Intelligence still walks.

**Nothing here sends anything, and now it does not have to.** Every composition is
filed to the review queue as pending, which is canon's primary review gate. On
approval, Phase 4a puts the **email** touch into the person's Gmail as a draft
(`services/mail_draft`); LinkedIn and call touches have no mailbox to land in and stay
text to copy. They press send either way — the grant cannot send.

Only the channels asked for are generated. The requested mix decides the JSON shape
the model is given, because asking for a shape you do not want is how an unasked-for
channel ends up in the output.

`agents/services/outreach.py` does the work of composing — this module decides what
to ask for, refuses what came back wrong, and records the decision trail.
"""
from __future__ import annotations

from agents.sales import prompts
from agents.services import mail_draft, outreach
from agents.services.review import ReviewQueue
from paths import sales_data

#: Where the gate's records live. One queue for outreach, per canon's "primary
#: review gate" — approvals belong in the audit trail, not in a page's memory.
REVIEW_FILE = sales_data() / "composer_review.json"

#: What the gate calls these, so the queue can be filtered by kind.
REVIEW_KIND = "outreach_touches"

TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "company": {"type": "string", "description": "The company being approached. Required."},
        "person": {"type": "string", "description": "Optional. Who the touches address."},
        "channels": {
            "type": "array",
            "items": {"type": "string", "enum": list(prompts.COMPOSER_CHANNELS)},
            "description": "Which touches to write. Defaults to email only.",
        },
        "recipient": {
            "type": "string",
            "description": (
                "Optional. The person's email address. Without it the touches are "
                "still written and filed, but no Gmail draft can be created."
            ),
        },
        "notes": {
            "type": "string",
            "description": "Optional. Anything the touches should take account of.",
        },
    },
    "required": ["company"],
}


def _queue() -> ReviewQueue:
    """Built per call so a test pointing `sales_data` elsewhere is honoured."""
    return ReviewQueue(REVIEW_FILE)


def requested_channels(channels) -> list[str]:
    """The channel mix, cleaned: known channels only, in canon's order, deduped.

    Order is fixed rather than the caller's, so two runs asking for the same mix
    produce the same document. An empty or unrecognised request falls back to email
    — the one channel that always makes sense — rather than composing nothing.
    """
    asked = {str(c).strip().lower() for c in (channels or [])}
    ordered = [c for c in prompts.COMPOSER_CHANNELS if c in asked]
    return ordered or ["email"]


def _usable(touches: dict, channels: list[str]) -> tuple[dict, list[str]]:
    """Keep the channels that came back complete; report the ones that did not.

    A half-written touch is worse than a missing one: a subject with no body reads
    as a bug to whoever has to send it, and silently showing it invites them to send
    it anyway.
    """
    required = {
        "email": ("subject", "body"),
        "linkedin": ("connection_note", "follow_up"),
        "call": ("opener", "talking_points"),
    }

    kept: dict = {}
    missing: list[str] = []
    for channel in channels:
        value = touches.get(channel)
        if not isinstance(value, dict):
            missing.append(channel)
            continue
        if all(str(value.get(field) or "").strip() for field in required[channel]):
            kept[channel] = value
        else:
            missing.append(channel)
    return kept, missing


def compose(
    username: str,
    *,
    brief: dict,
    channels=None,
    notes: str = "",
    intel: dict | None = None,
    recipient: str = "",
) -> dict:
    """Write the touches for one brief and file them for review.

    Returns `{"touches", "channels", "missing", "review_id", "error"}`. Anything
    that came back incomplete is named in `missing` rather than shown half-written.

    `intel` is a Campaign Intelligence outline for the market. Optional: it makes
    the touches better, not possible, so a run that skipped Campaign Intelligence
    composes exactly as it did before that agent existed.
    """
    brief = brief or {}
    company = ((brief.get("subject") or {}).get("company") or "").strip()
    if not company:
        return {
            "touches": {}, "channels": [], "missing": [],
            "review_id": None, "error": "no_brief",
        }

    wanted = requested_channels(channels)

    try:
        composed = outreach.two_pass(
            username=username,
            draft_overlay=prompts.COMPOSER_DRAFT_OVERLAY,
            draft_prompt=prompts.composer_draft_prompt(
                brief=brief, channels=wanted, notes=notes, intel=intel,
            ),
            refine_overlay=prompts.COMPOSER_REFINE_OVERLAY,
            refine_prompt=prompts.composer_refine_prompt,
            # The person sends this as themselves, so their own voice is the last
            # word — canon's draft → Owl-voice → user-style order.
            personalise=True,
        )
    except Exception as e:
        return {
            "touches": {}, "channels": wanted, "missing": wanted,
            "review_id": None, "error": f"compose_failed: {e}",
        }

    touches, missing = _usable(composed if isinstance(composed, dict) else {}, wanted)
    if not touches:
        return {
            "touches": {}, "channels": wanted, "missing": missing,
            "review_id": None, "error": "nothing_usable",
        }

    person = brief.get("person") or {}

    item = _queue().submit(
        kind=REVIEW_KIND,
        payload={
            "company": company,
            "person": person.get("name") or "",
            # Carried through when the brief already has it, so whoever makes the
            # call is not hunting for it. Composer never *buys* a number: writing a
            # call opener does not need one, and spending Lusha credit as a side
            # effect of composing text is the kind of silent spend the X-ray side
            # is careful to avoid. A number is bought on a shortlist, deliberately.
            "phone": person.get("phone") or "",
            # Recorded so the email touch can be addressed at approval time. Taken
            # from the caller, falling back to whatever the brief's person carries —
            # an enriched X-ray row has one, an unenriched one does not.
            "recipient": (recipient or person.get("_email") or person.get("email") or "").strip(),
            "channels": list(touches),
            "touches": touches,
            "notes": notes,
        },
        submitted_by=username,
    )

    return {
        "touches": touches,
        "channels": list(touches),
        "missing": missing,
        "review_id": item.id,
        "error": None,
    }


def pending(username: str) -> list[dict]:
    """This user's touches awaiting their decision, newest first."""
    items = [
        item for item in _queue().pending(kind=REVIEW_KIND)
        if item.submitted_by == username
    ]
    items.sort(key=lambda i: i.created_at, reverse=True)
    return [item.to_dict() for item in items]


def decide(username: str, review_id: str, *, approve: bool, notes: str = "") -> dict:
    """Record the human decision, then draft the email touch in their Gmail.

    Approval means "I will send this", not "sent" — the grant cannot send.

    **The order is deliberate.** The decision is recorded first and is never undone by
    what follows: if Gmail fails, the item stays approved and carries the reason in
    `outcome.gmail_error`. Only the **email** touch becomes a draft; LinkedIn and call
    touches have no mailbox to land in.
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
    """Create the Gmail draft for an approved composition and record what happened.

    A composition with no email touch is not a failure and is not reported as one —
    a LinkedIn-only campaign has nothing to draft, and an error there would send
    someone looking for a problem that does not exist.
    """
    payload = item.payload or {}
    email_touch = (payload.get("touches") or {}).get("email")

    if not isinstance(email_touch, dict):
        return _queue().record_outcome(item.id, outcome={
            "gmail_draft_id": "", "gmail_thread_id": "",
            "gmail_error": None,
            "gmail_skipped": "No email touch in this composition, so there is nothing to draft.",
        })

    outcome = mail_draft.draft(
        username,
        recipient=payload.get("recipient") or "",
        subject=email_touch.get("subject") or "",
        body=email_touch.get("body") or "",
    )
    return _queue().record_outcome(item.id, outcome=outcome)


def draft_again(username: str, review_id: str) -> dict:
    """Retry the Gmail draft for an already-approved composition.

    Needed because the queue refuses to re-decide a terminal item — correctly, since
    the decision has not changed. Only the delivery failed, so only it is retried.
    """
    queue = _queue()
    item = queue.get(review_id)
    if item is None or item.submitted_by != username:
        raise KeyError(review_id)
    if item.status != "approved":
        raise ValueError("Only approved touches have a draft to create.")

    return _draft_for(username, item).to_dict()


def run_as_tool(username: str, args: dict) -> str:
    """Compose from conversation.

    Needs a brief to be worth anything, and a conversation rarely has one — so this
    builds the thinnest possible brief from what was said and is explicit that
    running Research first produces better touches.
    """
    company = (args.get("company") or "").strip()
    if not company:
        return "Name the company to write to."

    brief = {
        "subject": {"company": company, "person": (args.get("person") or "").strip()},
        "person": {"name": (args.get("person") or "").strip()},
    }

    out = compose(
        username,
        brief=brief,
        channels=args.get("channels"),
        notes=(args.get("notes") or ""),
        recipient=(args.get("recipient") or ""),
    )

    if out["error"]:
        return f"Could not write the touches ({out['error']})."

    lines = [f"**Draft outreach to {company}** — for review, nothing sent."]
    email = out["touches"].get("email")
    if email:
        lines.append(f"\n**Email** — {email['subject']}\n\n{email['body']}")
    linkedin = out["touches"].get("linkedin")
    if linkedin:
        lines.append(f"\n**LinkedIn** — {linkedin['connection_note']}")
    call = out["touches"].get("call")
    if call:
        points = "\n".join(f"- {p}" for p in call["talking_points"])
        lines.append(f"\n**Call** — {call['opener']}\n{points}")

    if out["missing"]:
        lines.append(f"\n_Could not write: {', '.join(out['missing'])}._")

    lines.append(
        "\n_Written from what you told me. Research the account first and the touches "
        "get materially better — they will be grounded in what is actually happening there._"
    )

    if "email" in out["touches"]:
        if mail_draft.looks_like_an_address(args.get("recipient")):
            lines.append(
                "_Approve it and the email lands as a draft in your Gmail — addressed, "
                "unsent, yours to send._"
            )
        else:
            lines.append(
                "_Give me their email address and approving it will put an addressed "
                "draft in your Gmail._"
            )
    return "\n".join(lines)
