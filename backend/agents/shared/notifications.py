"""Lightweight admin email notifier.

Used by the Added-Knowledge approval flow to ping the admin when a user
submits a correction. Reads SMTP credentials from environment variables.
No-ops with a log line if SMTP is unconfigured so dev environments don't
break.

Required env vars (all optional individually; all required to actually send):
  SMTP_HOST           e.g. smtp.gmail.com
  SMTP_PORT           e.g. 587
  SMTP_USER           SMTP username
  SMTP_PASSWORD       SMTP password / app password
  SMTP_FROM           From: address (defaults to SMTP_USER)
  ADMIN_NOTIFY_EMAIL  Where notifications are sent
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage


def _smtp_config() -> dict | None:
    host = os.environ.get("SMTP_HOST", "").strip()
    port = os.environ.get("SMTP_PORT", "").strip()
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    admin = os.environ.get("ADMIN_NOTIFY_EMAIL", "").strip()
    if not (host and port and user and password and admin):
        return None
    # A non-numeric port is a typo, not a crash. This runs on the request path —
    # `is_configured()` is called while somebody waits — and an uncaught
    # ValueError here would 500 a registration that had already been saved,
    # which is exactly the failure the caller is written to avoid.
    try:
        port_number = int(port)
    except ValueError:
        print(f"[notify] SMTP_PORT is not a number: {port!r} — email is off")
        return None
    return {
        "host": host,
        "port": port_number,
        "user": user,
        "password": password,
        "from": os.environ.get("SMTP_FROM", "").strip() or user,
        "to": admin,
    }


def is_configured() -> bool:
    """Whether email can be sent at all.

    Separate from `send_admin_email`'s return value because a caller needs to
    tell *"nobody has set this up"* apart from *"it was set up and the send
    failed"*. Both come back as False from the sender, and a surface that
    reports the first when the second happened is telling somebody their message
    went nowhere for the wrong reason.

    Mirrors `integrations.google_oauth.is_configured()`.
    """
    return _smtp_config() is not None


def send_admin_email(subject: str, body: str, html: str | None = None) -> bool:
    """Send an email to ADMIN_NOTIFY_EMAIL. Returns True if sent.

    ``html`` is optional and additive: given one, the message goes out as
    multipart/alternative with the plain text first, so a client that cannot or
    will not render HTML still gets a complete message rather than a fallback
    apology. Callers that pass nothing are unchanged.
    """
    cfg = _smtp_config()
    if cfg is None:
        print(f"[notify] SMTP not configured — skipping: {subject}")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["from"]
    msg["To"] = cfg["to"]
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=10) as s:
            s.starttls(context=ctx)
            s.login(cfg["user"], cfg["password"])
            s.send_message(msg)
        print(f"[notify] sent admin email: {subject}")
        return True
    except Exception as e:
        print(f"[notify] failed to send admin email ({subject}): {e}")
        return False
