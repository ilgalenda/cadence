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
    return {
        "host": host,
        "port": int(port),
        "user": user,
        "password": password,
        "from": os.environ.get("SMTP_FROM", "").strip() or user,
        "to": admin,
    }


def send_admin_email(subject: str, body: str) -> bool:
    """Send an email to ADMIN_NOTIFY_EMAIL. Returns True if sent."""
    cfg = _smtp_config()
    if cfg is None:
        print(f"[notify] SMTP not configured — skipping: {subject}")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["from"]
    msg["To"] = cfg["to"]
    msg.set_content(body)

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
