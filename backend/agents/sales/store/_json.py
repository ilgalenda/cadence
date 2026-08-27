"""JSON-file primitives shared by every sales store.

`lead/storage.py` and `high_intent/storage.py` each carried byte-identical copies
of these four functions. They are owned here once, so the sales stores that
replace them — and anything else that persists a JSON record — cannot drift on
how a corrupt file is handled or how a timestamp is formatted.

Deliberately forgiving on read and strict on write: a truncated or hand-edited
file yields the caller's default rather than taking down a page, because losing
one record must never mean losing the surface that would let you fix it.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

#: The display format the frontend's legacy time parsers still accept.
DISPLAY_FORMAT = "%d %b %Y, %H:%M"


def read_json(path: Path, default: Any) -> Any:
    """The file's contents, or ``default`` when it is absent or unreadable."""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError, ValueError):
        return default


def write_json(path: Path, data: Any) -> None:
    """Write a record set, creating the directory if it does not yet exist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def now_label() -> str:
    """The current time, UTC, in the store's display format."""
    return datetime.now(timezone.utc).strftime(DISPLAY_FORMAT)


def new_id() -> str:
    """A fresh opaque record id."""
    return uuid.uuid4().hex
