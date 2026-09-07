"""What the admin is told when somebody registers interest in an event.

Composing the message is separated from sending it for one reason: the wording
is the part worth testing, and the sending is the part that talks to an SMTP
server. `agents/shared/notifications` already owns the second half — it is what
the Owl correction flow uses to raise a hand — so nothing new is built here.

**The mail exists to be answered, not read.** It carries the two things an
approval actually turns on — the case the person made, and the date after which
deciding stops being free — and a link that opens that show's record. A
notification that only announces something leaves the reader to go and find it.

**A failed email must never lose a registration.** The caller records the
interest before it calls this, and this reports what happened rather than
raising. Somebody who filled the form in has registered whether or not a mail
server was reachable, and telling them otherwise would be a lie about their own
action. That is the rule `services/mail_draft.py` states for drafts, applied
here.
"""
from __future__ import annotations

import html as html_escaping
import os
import urllib.parse
from datetime import date

from agents.shared.notifications import is_configured, send_admin_email

from . import requirements

#: What happened, in one word. `unconfigured` and `failed` both mean "no mail
#: arrived" and are different facts: the first is a setting nobody has made, the
#: second is a server that would not take it.
SENT = "sent"
UNCONFIGURED = "unconfigured"
FAILED = "failed"

#: What the admin needs in order to decide without opening anything: who, which
#: show, when, what it costs, whether it moves anybody around the world — and
#: the case for going.
_TEMPLATE = """{who} has registered interest in {name}.

  Event      {name}
  When       {when}
  Where      {where}
  Invited    {invited}
  Going as   {intent}
  Material   {material}
  Travel     {travel}
  Ticket     {ticket}
{decide}
Why we should go
{rationale}
{link}This is a proposal — nothing is ordered and no deadline runs until it is
approved.
"""


def _base_url() -> str:
    """Where this Cadence answers, for a link somebody can click.

    `PUBLIC_BASE_URL` if set. Failing that, the origin of
    `GOOGLE_REDIRECT_URI` — which has to match the deployment's public origin
    already, or the OAuth callback would not resolve, so it is the one setting
    that cannot be wrong without something louder breaking first.

    Empty when neither resolves, and the mail then carries no link rather than a
    broken one.
    """
    explicit = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if explicit:
        return explicit

    redirect = os.environ.get("GOOGLE_REDIRECT_URI", "").strip()
    if not redirect:
        return ""
    parts = urllib.parse.urlsplit(redirect)
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}"


def event_url(event_id: str) -> str:
    """The link that opens this show's record, or empty when there is no base."""
    base = _base_url()
    if not base:
        return ""
    return f"{base}/work/events?event={urllib.parse.quote(event_id)}"


def _money(amount, currency: str) -> str:
    if amount in (None, ""):
        return "not stated"
    if float(amount) == 0:
        return "free"
    return f"{currency} {float(amount):,.2f}"


#: Month names owned outright rather than asked of the locale — the same reason
#: `lib/events.ts` carries them: `%b` follows LC_TIME, so a server in another
#: locale would mail a date the app never shows.
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _day(iso: str) -> str:
    """`28 Aug 2026`. The app's voice, so the mail and the page agree."""
    try:
        d = date.fromisoformat(iso)
    except (TypeError, ValueError):
        return str(iso or "")
    return f"{d.day} {_MONTHS[d.month - 1]} {d.year}"


def _when(event: dict) -> str:
    """`11–14 Sep 2026`, collapsed the way `formatWhen` collapses it."""
    starts, ends = event["starts_on"], event["ends_on"]
    if starts == ends:
        return _day(starts)
    try:
        a, b = date.fromisoformat(starts), date.fromisoformat(ends)
    except (TypeError, ValueError):
        return f"{starts} to {ends}"
    if a.year == b.year and a.month == b.month:
        return f"{a.day}–{b.day} {_MONTHS[a.month - 1]} {a.year}"
    return f"{_day(starts)} – {_day(ends)}"


def _countdown(days: int) -> str:
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    if days > 0:
        return f"in {days} days"
    return f"{abs(days)} days ago"


def _decide_line(event: dict) -> str:
    """The deadline that makes this mail urgent rather than merely informative."""
    if not event.get("decide_by"):
        return ""
    days = event.get("days_to_decide")
    if days is None:
        days = (date.fromisoformat(event["decide_by"]) - date.today()).days
    overdue = " — OVERDUE" if days < 0 else ""
    return f"  Decide by  {_day(event['decide_by'])} ({_countdown(days)}){overdue}\n"


def _asked_for(registration: dict, joiner: str) -> tuple[str, str]:
    """What this person asked for — material and travel — as two blocks.

    One helper for both parts of the email. The text and the HTML differ only in
    how a second line is joined, and reading the answer twice is how the two
    halves drift apart.
    """
    material = "no"
    if registration.get("needs_material"):
        material = requirements.describe_material(
            requirements.load(registration.get("material_items")),
            registration.get("material_note") or "",
        ).replace("\n", joiner) or "yes"

    travel = "no"
    if registration.get("needs_travel"):
        legs = requirements.load(registration.get("travel_legs"))
        travel = (requirements.describe_travel(legs).replace("\n", joiner)
                  or registration.get("travel_note") or "yes")

    return material, travel


def compose(event: dict, registration: dict) -> tuple[str, str]:
    """The subject and body for one new registration."""
    where = ", ".join(p for p in (event["location"], event["country"]) if p) or "not stated"
    material, travel = _asked_for(registration, "\n             ")

    link = event_url(event["id"])
    # The show leads. An inbox is scanned for the thing you recognise, and a
    # phone keeps roughly the first 35 characters — a bracketed tag spends four
    # of them saying what the sender already says.
    subject = f"{event['name']} — {registration['username']} wants to attend"
    body = _TEMPLATE.format(
        who=registration["username"],
        name=event["name"],
        when=_when(event),
        where=where,
        invited="yes" if event["invited"] else "no",
        intent=registration["intent"],
        material=material,
        travel=travel,
        ticket=_money(registration["ticket_cost"], registration["ticket_currency"]),
        decide=_decide_line(event),
        rationale=(event.get("rationale") or "").strip() or "Not stated.",
        link=f"\nApprove or decline it: {link}\n\n" if link else "\n",
    )
    return subject, body


# ── The HTML half ───────────────────────────────────────────────────────────
#
# An email cannot load the design system, so the tokens it needs are written out
# here as literals — the one place in this repo where that is correct, because
# there is no stylesheet to reach and `check-adherence` does not scan Python.
# Every value below is copied from `design-system/tokens.css`; if the palette
# moves, this moves with it.
#
# Built to the studio's position: a white field, soft grey wells, pill geometry,
# and charcoal spent only on the thing you press. Table layout and inline styles
# because that is what mail clients render; Roboto asked for and a real stack
# behind it, since a webfont will not load.

_INK = "#121212"
_INK_SECONDARY = "#5C5A56"
_INK_MUTED = "#706D67"
_INK_ON_INK = "#F9F8F5"
_CHROME = "#1A1A19"
_SUNKEN = "#F4F3F1"
_HAIRLINE = "#ECEBE8"
_DRIFT, _DRIFT_WASH = "#F6A100", "#FEF4E0"
_FAULT, _FAULT_WASH = "#C12D22", "#FBEAE8"

_SANS = "Roboto, 'Helvetica Neue', Helvetica, Arial, sans-serif"
_MONO = "'Kode Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"


def _esc(value) -> str:
    """Everything from the form is escaped. It is somebody's typing, not markup."""
    return html_escaping.escape(str(value or ""), quote=True)


def _pill(text: str, ink: str, wash: str) -> str:
    return (
        f'<span style="display:inline-block;padding:3px 10px;border-radius:999px;'
        f'background:{wash};color:{ink};font:500 12px/1.4 {_SANS};'
        f'white-space:nowrap;">{_esc(text)}</span>'
    )


def _fact_row(label: str, value: str) -> str:
    """One label and its value. A value may run to several lines.

    The break is inserted **after** escaping, so a person typing ``<br>`` into
    the free-text box gets the characters they typed rather than a line break.
    """
    lines = "<br>".join(_esc(part) for part in str(value).split("\n"))
    return (
        '<tr>'
        f'<td style="padding:7px 16px 7px 0;font:400 13px/1.5 {_SANS};color:{_INK_MUTED};'
        f'border-bottom:1px solid {_HAIRLINE};white-space:nowrap;vertical-align:top;">'
        f'{_esc(label)}</td>'
        f'<td style="padding:7px 0;font:400 13px/1.5 {_SANS};color:{_INK};'
        f'border-bottom:1px solid {_HAIRLINE};">{lines}</td>'
        '</tr>'
    )


def compose_html(event: dict, registration: dict) -> str:
    """The same message, drawn.

    Same content as the text part and in the same order — the case first,
    because it is what the decision turns on. A reader comparing the two halves
    should find nothing in one that is missing from the other.
    """
    where = ", ".join(p for p in (event["location"], event["country"]) if p) or "not stated"
    material, travel = _asked_for(registration, "\n")

    days = event.get("days_to_decide")
    decide = ""
    if event.get("decide_by"):
        if days is None:
            days = (date.fromisoformat(event["decide_by"]) - date.today()).days
        overdue = days < 0
        decide = _pill(
            f"decide by {_day(event['decide_by'])} · {_countdown(days)}",
            _FAULT if overdue else _DRIFT,
            _FAULT_WASH if overdue else _DRIFT_WASH,
        )

    facts = "".join([
        _fact_row("When", _when(event)),
        _fact_row("Where", where),
        _fact_row("Going as", registration["intent"]),
        _fact_row("Material", material),
        _fact_row("Travel", travel),
        _fact_row("Ticket", _money(registration["ticket_cost"], registration["ticket_currency"])),
        _fact_row("Invited", "yes" if event["invited"] else "no"),
    ])

    link = event_url(event["id"])
    button = (
        f'<a href="{_esc(link)}" style="display:inline-block;padding:11px 22px;'
        f'border-radius:999px;background:{_CHROME};color:{_INK_ON_INK};'
        f'font:500 14px/1 {_SANS};text-decoration:none;">Open in Cadence</a>'
        if link else ""
    )

    rationale = (event.get("rationale") or "").strip() or "Not stated."

    return f"""<!doctype html>
<html lang="en-GB"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light only">
<title>{_esc(event['name'])}</title></head>
<body style="margin:0;padding:0;background:{_SUNKEN};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background:{_SUNKEN};padding:32px 16px;">
<tr><td align="center">
  <table role="presentation" width="560" cellpadding="0" cellspacing="0"
         style="width:560px;max-width:100%;background:#FFFFFF;border-radius:20px;">
    <tr><td style="padding:32px 32px 28px;">

      <p style="margin:0 0 20px;font:500 11px/1 {_MONO};letter-spacing:0.18em;
                text-transform:uppercase;color:{_INK_MUTED};">Cadence · Events</p>

      <p style="margin:0 0 6px;font:400 14px/1.5 {_SANS};color:{_INK_SECONDARY};">
        <strong style="color:{_INK};font-weight:500;">{_esc(registration['username'])}</strong>
        wants to attend</p>

      <h1 style="margin:0 0 16px;font:700 26px/1.2 {_SANS};letter-spacing:-0.02em;
                 color:{_INK};">{_esc(event['name'])}</h1>

      <p style="margin:0 0 24px;">{_pill('proposed', _DRIFT, _DRIFT_WASH)} {decide}</p>

      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
             style="background:{_SUNKEN};border-radius:14px;margin:0 0 24px;">
        <tr><td style="padding:16px 18px;">
          <p style="margin:0 0 5px;font:400 12px/1.4 {_SANS};color:{_INK_MUTED};">
            Why we should go</p>
          <p style="margin:0;font:400 14px/1.6 {_SANS};color:{_INK};">{_esc(rationale)}</p>
        </td></tr>
      </table>

      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
             style="margin:0 0 28px;">{facts}</table>

      {button}

      <p style="margin:24px 0 0;font:400 13px/1.6 {_SANS};color:{_INK_MUTED};">
        Nothing is ordered and no deadline runs until this is approved.</p>

    </td></tr>
  </table>
  <p style="margin:16px 0 0;font:400 11px/1.5 {_SANS};color:{_INK_MUTED};">
    Sent by Cadence because you approve event registrations.</p>
</td></tr>
</table>
</body></html>"""


def registration_filed(event: dict, username: str) -> str:
    """Tell the admin that ``username`` has registered, and say what happened.

    Returns :data:`SENT`, :data:`UNCONFIGURED` or :data:`FAILED`, so the surface
    can be honest about which. Reporting "not configured" for a send that was
    configured and failed would send somebody to fix the wrong thing.
    """
    registration = next(
        (r for r in event["registrations"] if r["username"] == username), None
    )
    if registration is None:
        return FAILED
    if not is_configured():
        return UNCONFIGURED

    subject, body = compose(event, registration)
    html = compose_html(event, registration)
    return SENT if send_admin_email(subject=subject, body=body, html=html) else FAILED
