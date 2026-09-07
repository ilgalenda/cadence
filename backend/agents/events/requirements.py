"""What a person asks for when they register: material, and travel.

Until this existed, Cadence **inferred** what somebody needed. Everybody
confirmed for a show got a business-card line and a clothing line whether they
had cards already or not, and travel was a single yes/no with a sentence beside
it that Operations had to interpret. Sam set the change: the person asks, in
their own words where the list does not cover it, and what they ask for is what
gets raised.

Two vocabularies live here, and they are the only place either is written down —
the form's options, the sheet's columns, the checklist's per-person lines and the
tests all derive from these lists.

**Material** is a set of choices. Each one either raises its own line for that
person or is already covered by a line the show raises once, which is the
difference between *cards* — ordered per person, to a name — and *lanyards*,
which are bought in a box. `OTHER` carries free text and always raises a line,
because nothing else in the system knows what it is.

**Travel** is a list of legs rather than a flag. A leg has a mode, a from, a to
and a number of nights, and each mode raises the booking line it needs. One
person's trip is a flight out and a car at the other end; the shape has to allow
that without a note somebody has to read.
"""
from __future__ import annotations

import json
from typing import NamedTuple, Optional


class Material(NamedTuple):
    key: str
    label: str
    #: Help shown beneath the option, where the label alone leaves a real question.
    hint: str = ""
    #: The checklist line this raises for the person who asked. Empty where the
    #: show already raises the line once for everybody — asking for a lanyard
    #: does not create a second box of lanyards.
    raises: str = ""


MATERIAL: list[Material] = [
    Material("cards", "Business cards",
             "Ordered to your name, so they need 14 days.",
             "Business cards ordered"),
    Material("clothing", "Hoodie or quarter-zip",
             "Tell us your size in the box below.",
             "Hoodie or quarter-zip ordered"),
    Material("collateral", "Printed collateral to hand out"),
    Material("lanyard", "Lanyard"),
    Material("giveaways", "Giveaways for the stand"),
    Material("banner", "Pull-up banner"),
    Material("demo", "Demo hardware to take with you",
             "", "Demo hardware prepared"),
]

OTHER = "other"

#: Every value the form may send, `other` included.
MATERIAL_KEYS = tuple(m.key for m in MATERIAL) + (OTHER,)

_BY_KEY = {m.key: m for m in MATERIAL}


class Mode(NamedTuple):
    key: str
    label: str
    #: The booking line this leg raises, owned by Operations.
    raises: str
    #: Whether the leg is a journey between two places. A car hire is not.
    routed: bool = True


MODES: list[Mode] = [
    Mode("flight", "Flight", "Flights booked"),
    Mode("train", "Train", "Train booked"),
    Mode("car", "Car hire", "Car hire booked", routed=False),
    Mode("other", "Something else", "Travel booked"),
]

MODE_KEYS = tuple(m.key for m in MODES)
_BY_MODE = {m.key: m for m in MODES}

#: Raised once for a person with any overnight leg, however many legs there are.
ACCOMMODATION = "Accommodation booked"

#: A trip nobody would book. Beyond it, somebody has fat-fingered the field.
MAX_NIGHTS = 60
MAX_LEGS = 8


def material_label(key: str) -> str:
    """The human name for a stored key, and the key itself if it is unknown.

    Unknown rather than an error: a key that was retired after somebody chose it
    should still read as what they asked for, not vanish from their request.
    """
    material = _BY_KEY.get(key)
    return material.label if material else key


def mode_label(key: str) -> str:
    mode = _BY_MODE.get(key)
    return mode.label if mode else key


def clean_material(raw: object) -> list[str]:
    """The chosen keys, in the list's own order, deduplicated.

    The form's order rather than the order they were clicked, so two people who
    asked for the same things produce the same row.
    """
    if not isinstance(raw, (list, tuple)):
        return []
    chosen = {str(k).strip().lower() for k in raw}
    return [k for k in MATERIAL_KEYS if k in chosen]


def clean_legs(raw: object) -> list[dict]:
    """The travel legs, validated.

    Anything without a mode is dropped rather than refused: the form adds an
    empty leg the moment somebody presses *Add*, and refusing to submit because
    one is still blank would be punishing them for the interface.
    """
    if not isinstance(raw, (list, tuple)):
        return []

    legs: list[dict] = []
    for entry in raw[:MAX_LEGS]:
        if not isinstance(entry, dict):
            continue
        mode = str(entry.get("mode", "")).strip().lower()
        if mode not in MODE_KEYS:
            continue

        nights = entry.get("nights")
        try:
            nights = max(0, int(nights or 0))
        except (TypeError, ValueError):
            raise ValueError("Nights must be a whole number.")
        if nights > MAX_NIGHTS:
            raise ValueError(f"Nights cannot be more than {MAX_NIGHTS}.")

        legs.append({
            "mode": mode,
            "from": str(entry.get("from", "")).strip()[:120],
            "to": str(entry.get("to", "")).strip()[:120],
            "nights": nights,
        })
    return legs


def describe_leg(leg: dict) -> str:
    """One leg as a line somebody in Operations can act on."""
    parts = [mode_label(leg["mode"])]
    route = " → ".join(p for p in (leg.get("from"), leg.get("to")) if p)
    if route:
        parts.append(route)
    if leg.get("nights"):
        nights = leg["nights"]
        parts.append(f"{nights} night{'s' if nights != 1 else ''}")
    return ", ".join(parts)


def describe_travel(legs: list[dict]) -> str:
    """Every leg, one per line. Empty when there is nothing to book."""
    return "\n".join(describe_leg(leg) for leg in legs)


def describe_material(keys: list[str], note: str = "") -> str:
    """The chosen material as a readable list, with the free text on the end."""
    labels = [material_label(k) for k in keys if k != OTHER]
    if OTHER in keys and note:
        labels.append(note)
    elif OTHER in keys:
        labels.append("Something else — not specified")
    return "\n".join(labels)


def nights(legs: list[dict]) -> int:
    """The most nights any single leg asks for.

    The maximum rather than the sum: two legs of a trip both describe the same
    nights away from home, and adding them would book the hotel twice.
    """
    return max((leg.get("nights", 0) for leg in legs), default=0)


def dump(value: object) -> str:
    """Store a list as JSON. Empty stores as an empty string, not ``"[]"``."""
    return json.dumps(value) if value else ""


def load(raw: Optional[str]) -> list:
    """Read one back, tolerating anything that is not a list.

    A row written before this column existed, or by hand in the database, must
    not take the page down.
    """
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []
