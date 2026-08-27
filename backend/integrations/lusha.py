from __future__ import annotations
"""Lusha API client — Person Enrichment (v2).

Thin transport over Lusha's Person Enrichment endpoint. Given identifiers we
already have for a person (name + company, LinkedIn URL, or email), Lusha returns
their work email and, on request, phone. Auth is the ``api_key`` request header
(``LUSHA_API_KEY``). Enrichment spends credits, so callers enrich only people a
human has selected, and reveal phones only on explicit request.

Docs: https://docs.lusha.com/apis/openapi/person-enrichment (Person API V2).
Rate limit: 25 req/s per endpoint; up to 100 contacts per bulk call.

This client owns the request contract (well documented) and error handling. The
*response* envelope is parsed leniently by the Enrichment service, because the
live response shape could not be fetched from Lusha's JS-rendered docs at build
time — see agents.services.enrichment and the live smoke test.
"""
import os
from typing import Optional

import httpx

LUSHA_BASE_URL = "https://api.lusha.com"
PERSON_ENDPOINT = "/v2/person"
MAX_BULK = 100


class LushaError(Exception):
    """Base Lusha client error."""


class LushaAuthError(LushaError):
    """Missing or rejected API key."""


class LushaRateLimitError(LushaError):
    """HTTP 429 — exceeded the 25 req/s limit."""


class LushaClient:
    """Transport for the Lusha Person Enrichment endpoint.

    Inject ``http`` (anything with a ``post(url, json, headers, timeout)`` that
    returns an object exposing ``status_code``, ``.json()`` and ``.text``) to
    test without real network; otherwise a short-lived httpx client is used.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: str = LUSHA_BASE_URL,
        timeout: float = 20.0,
        http=None,
    ):
        self._api_key = api_key or os.getenv("LUSHA_API_KEY")
        if not self._api_key:
            raise LushaAuthError("LUSHA_API_KEY is not set")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._http = http

    def _headers(self) -> dict:
        return {"api_key": self._api_key, "Content-Type": "application/json"}

    def enrich(
        self,
        contacts: list[dict],
        *,
        reveal_emails: bool = True,
        reveal_phones: bool = False,
    ) -> dict:
        """POST /v2/person for up to 100 contacts; return the raw parsed JSON.

        Each contact is ``{contactId, fullName?, email?, linkedinUrl?, companies?}``.
        ``revealEmails`` / ``revealPhones`` control which details are returned (and
        which credits are spent).
        """
        if not contacts:
            return {"contacts": {}}
        if len(contacts) > MAX_BULK:
            raise LushaError(
                f"Lusha enrich accepts at most {MAX_BULK} contacts per call; got {len(contacts)}"
            )
        body = {
            "contacts": contacts,
            "metadata": {"revealEmails": reveal_emails, "revealPhones": reveal_phones},
        }
        return self._post(PERSON_ENDPOINT, body)

    def _post(self, path: str, body: dict) -> dict:
        url = f"{self._base_url}{path}"
        try:
            if self._http is not None:
                resp = self._http.post(url, json=body, headers=self._headers(), timeout=self._timeout)
            else:
                with httpx.Client(timeout=self._timeout) as client:
                    resp = client.post(url, json=body, headers=self._headers())
        except httpx.HTTPError as e:
            raise LushaError(f"Lusha request failed: {e}") from e
        return self._handle(resp)

    @staticmethod
    def _handle(resp) -> dict:
        status = resp.status_code
        if status == 401:
            raise LushaAuthError("Lusha rejected the API key (401)")
        if status == 429:
            raise LushaRateLimitError("Lusha rate limit exceeded (429)")
        if status >= 400:
            raise LushaError(f"Lusha error {status}: {getattr(resp, 'text', '')[:300]}")
        try:
            return resp.json()
        except Exception as e:
            raise LushaError(f"Lusha returned a non-JSON response: {e}") from e
