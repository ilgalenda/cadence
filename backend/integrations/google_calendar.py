from __future__ import annotations
"""Google Calendar — event creation.

A thin client over the shared grant in ``google_oauth.py``. It owned that grant
until Phase 4a, when Gmail became a second consumer and the OAuth concern moved
somewhere neither client is named after.

**`create_event` still has no caller.** Its only one was the campaign builder's
per-touch calendar sync, retired in Stage 3.3. The grant is live and the tokens are
real; scheduling is what will give this work again. Kept rather than deleted because
the capability is canon's (Calendar is a named integration) and the code is correct —
but nobody should read its presence as a working feature.
"""
from typing import Any

from integrations.google_oauth import authorised_request

CALENDAR_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"

#: Touch number → Google Calendar colourId, so a sequence reads as one campaign in
#: the month view rather than five unrelated events.
TOUCH_COLOURS = {1: "2", 2: "10", 3: "7", 4: "9", 5: "3"}


def create_event(
    username: str,
    *,
    summary: str,
    description: str,
    start_iso: str,
    end_iso: str,
    touch: int,
    timezone: str = "UTC",
) -> dict[str, Any]:
    """Put one event on this user's primary calendar."""
    data = authorised_request(
        username,
        "POST",
        CALENDAR_EVENTS_URL,
        json_body={
            "summary": summary,
            "description": description,
            "start": {"dateTime": start_iso, "timeZone": timezone},
            "end": {"dateTime": end_iso, "timeZone": timezone},
            "colorId": TOUCH_COLOURS.get(touch, "1"),
        },
    )
    return {"event_id": data.get("id"), "html_link": data.get("htmlLink")}
