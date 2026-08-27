from __future__ import annotations
"""Enrichment capability service — reveal a known person's contact details (Lusha).

**Two-tier reveal (Sam, 2026-07-27):** ``enrich()`` returns the work email
automatically; the phone is revealed only on explicit user request via
``reveal_phone()``, so phone credits are spent deliberately. Enrich only the
human-selected shortlist (post-review-gate) for credit discipline.

Discovery is separate (:mod:`agents.services.web_discovery`); this service only
enriches people already found — by name+company, LinkedIn URL, or email.

Response shape: the single-person ``/v2/person`` envelope was confirmed against
the live API (2026-07-27) — ``{error, isCreditCharged, data: {..., emailAddresses,
phoneNumbers, phones}}``. The parser stays lenient (email/phone arrays read under
``data`` or top-level; dict or string items) and the bulk-response shape is still
handled defensively pending a live multi-contact confirmation.
"""
from dataclasses import dataclass, field
from typing import Iterator, Optional

from integrations.lusha import LushaClient


@dataclass
class EnrichedContact:
    """A person's revealed contact details, normalised from Lusha."""

    emails: list[dict] = field(default_factory=list)   # {email, type, confidence}
    phones: list[dict] = field(default_factory=list)   # {number, type, do_not_call}
    raw: dict = field(default_factory=dict)

    @property
    def primary_email(self) -> Optional[str]:
        return self.emails[0]["email"] if self.emails else None

    @property
    def primary_phone(self) -> Optional[str]:
        return self.phones[0]["number"] if self.phones else None


def _person_to_lusha_contact(person: dict, contact_id: str) -> dict:
    """Map a discovered person row (X-ray shape) to a Lusha contact input."""
    contact: dict = {"contactId": contact_id}
    if person.get("full_name"):
        contact["fullName"] = person["full_name"]
    if person.get("linkedin_url"):
        contact["linkedinUrl"] = person["linkedin_url"]
    if person.get("email"):
        contact["email"] = person["email"]
    company = person.get("company") or person.get("company_name")
    domain = person.get("company_domain")
    if company or domain:
        # Lusha requires isCurrent (boolean) on each company; we only ever pass
        # the person's current employer, so it is always True.
        firm: dict = {"isCurrent": True}
        if company:
            firm["name"] = company
        if domain:
            firm["domain"] = domain
        contact["companies"] = [firm]
    return contact


def _iter_contact_entries(raw: dict) -> Iterator[tuple[Optional[str], dict]]:
    """Yield ``(contact_id, person_object)`` for each person in a Lusha response.

    The id is carried out rather than discarded because it is the only reliable
    way to say *which* of the people we asked about a revealed email belongs to.
    Joining on name instead looks fine until two colleagues share one, or the
    provider returns a name formatted differently from the one we sent.

    Single-person shape confirmed live 2026-07-27: ``{error, isCreditCharged,
    data: {person}}``. The bulk shape is still unconfirmed, so a ``data`` list and
    a ``contacts`` map/list are handled defensively; in the map form the key *is*
    the ``contactId`` we supplied.
    """
    data = raw.get("data")
    if isinstance(data, dict):
        yield (data.get("contactId"), data)
        return
    if isinstance(data, list):
        yield from ((c.get("contactId"), c) for c in data if isinstance(c, dict))
        return
    contacts = raw.get("contacts")
    if isinstance(contacts, dict):
        yield from (
            (str(key), c) for key, c in contacts.items() if isinstance(c, dict)
        )
    elif isinstance(contacts, list):
        yield from ((c.get("contactId"), c) for c in contacts if isinstance(c, dict))


def _normalise_contact(obj: dict) -> EnrichedContact:
    data = obj.get("data") if isinstance(obj.get("data"), dict) else obj
    emails: list[dict] = []
    for e in (data.get("emailAddresses") or data.get("emails") or []):
        if isinstance(e, dict):
            emails.append({
                "email": e.get("email"),
                "type": e.get("emailType"),
                "confidence": e.get("emailConfidence"),
            })
        elif isinstance(e, str) and e:
            emails.append({"email": e, "type": None, "confidence": None})
    phones: list[dict] = []
    for p in (data.get("phoneNumbers") or data.get("phones") or []):
        if isinstance(p, dict):
            phones.append({
                "number": p.get("number"),
                "type": p.get("phoneType"),
                "do_not_call": p.get("doNotCall"),
            })
        elif isinstance(p, str) and p:
            phones.append({"number": p, "type": None, "do_not_call": None})
    return EnrichedContact(emails=emails, phones=phones, raw=obj)


class Enrichment:
    """Reveal contact details for people already discovered."""

    def __init__(self, client: Optional[LushaClient] = None):
        self._client = client or LushaClient()

    def enrich(self, person: dict) -> EnrichedContact:
        """Reveal the person's work email (no phone)."""
        return self._enrich_one(person, reveal_emails=True, reveal_phones=False)

    def reveal_phone(self, person: dict) -> EnrichedContact:
        """On-demand: reveal the person's phone — an explicit user action."""
        return self._enrich_one(person, reveal_emails=False, reveal_phones=True)

    def enrich_shortlist(self, people: list[dict]) -> list[EnrichedContact]:
        """Bulk-enrich the human-selected shortlist for email (one API call).

        Returns **one entry per input person, in input order** — an empty
        ``EnrichedContact`` where the provider had nothing on file. Callers can
        therefore ``zip`` the result against the people they sent, which is the
        whole point: a revealed email is worthless if it lands on the wrong row.

        The join is by the ``contactId`` we supplied (the person's index). If the
        provider echoes no ids at all, we fall back to response order — the best
        available reading, and still better than matching on name.
        """
        contacts = [_person_to_lusha_contact(p, str(i)) for i, p in enumerate(people)]
        raw = self._client.enrich(contacts, reveal_emails=True, reveal_phones=False)

        entries = list(_iter_contact_entries(raw))
        by_id = {cid: obj for cid, obj in entries if cid is not None}

        revealed: list[EnrichedContact] = []
        for index in range(len(people)):
            obj = by_id.get(str(index))
            if obj is None and not by_id and index < len(entries):
                obj = entries[index][1]
            revealed.append(_normalise_contact(obj) if obj is not None else EnrichedContact())
        return revealed

    def _enrich_one(self, person: dict, *, reveal_emails: bool, reveal_phones: bool) -> EnrichedContact:
        contacts = [_person_to_lusha_contact(person, "0")]
        raw = self._client.enrich(contacts, reveal_emails=reveal_emails, reveal_phones=reveal_phones)
        entries = list(_iter_contact_entries(raw))
        return _normalise_contact(entries[0][1]) if entries else EnrichedContact(raw=raw)
