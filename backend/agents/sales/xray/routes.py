"""X-ray's endpoints — find people, then enrich only the ones a human picked.

The two-step shape is the point. Discovery is free and broad; enrichment costs
Lusha credit, so it never happens automatically and never to the whole result
set. And within enrichment, email comes back with the record while the **phone
is a separate, explicit action** — a deliberate second decision rather than a
default that quietly spends more.

There is no signal sweep here any more. `/detect` and `/signal-types` moved to
Signals (Sam, 2026-08-24), where a signal is already the subject. X-ray answers
one question — *given an account and why it matters, who are the people* — and a
sweep with no account had no "why" to work from.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from agents.sales.store import prospects as storage
from agents.sales.xray import agent
from agents.services.enrichment import Enrichment
from auth import is_sandbox, require_authed

router = APIRouter(prefix="/xray", tags=["sales"])

class SearchRequest(BaseModel):
    company: Optional[str] = None
    #: Narrow discovery to these personas. Chosen from the configured list, plus
    #: anything the person added. Empty means no narrowing, which is not the same
    #: as no personas: `Persona.md` is authoritative in the prompt regardless.
    personas: Optional[list[str]] = None
    #: A grounding the person corrected by hand. Given, it is used as-is and the
    #: classification pass is skipped — a human who has fixed the vertical should
    #: not have the model overrule them on the next run.
    industry: Optional[str] = None
    product_fit: Optional[str] = None
    # The scored verdict a search can be grounded in, when it follows on from
    # Lead scoring rather than starting from a name.
    signal_analysis: Optional[dict] = None
    # A lead pasted straight onto X-ray. Scored here, through the same
    # `scoring.analyse` Lead scoring runs, and the verdict becomes the grounding.
    lead_text: Optional[str] = None


class EnrichRequest(BaseModel):
    """The shortlist a human selected — never the whole result set."""
    people: list[dict]


class PersonRequest(BaseModel):
    person: dict


@router.get("/personas")
def personas(_user: dict = Depends(require_authed)):
    """The configured target personas, for the focus selector.

    Parsed from the team's own `Persona.md` rather than typed from memory into a
    free-text box — which is what this replaced, and why the parser that produces
    it had sat unused since it was written.
    """
    from agents.mind import blocks

    return blocks.persona_focus_options()


@router.post("/search")
def search(req: SearchRequest, user: dict = Depends(require_authed)):
    """Company-scoped: the ranked shortlist of ICP-match people at one company."""
    if not (req.company or req.signal_analysis or req.lead_text):
        raise HTTPException(status_code=400, detail="Name a company, or paste a lead.")

    # Three ways in, one mechanism. They differ only in how the grounding is
    # acquired: pasted and scored here, handed over already scored, or derived
    # from the name because nothing else was given.
    if req.lead_text:
        result = agent.from_lead(user["username"], text=req.lead_text, personas=req.personas)
    elif req.signal_analysis:
        result = agent.shortlist(user["username"], req.signal_analysis, None, req.personas)
    else:
        corrected = (
            {"industry": req.industry or "", "product_fit": req.product_fit or "", "note": ""}
            if (req.industry or req.product_fit) else None
        )
        result = agent.from_company(
            user["username"], req.company or "", req.personas, grounding=corrected,
        )

    # A search that found nobody is an outcome, not a failure — only a genuine
    # fault (no providers, no company, an unusable lead) is an error the caller
    # must handle.
    if result["error"] in {"missing_company", "no_enabled_sources", "missing_lead"}:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/enrich")
def enrich(req: EnrichRequest, _user: dict = Depends(require_authed)):
    """Reveal emails for the selected shortlist. One bulk call; phones excluded.

    Identity comes from the person the caller sent, not from the provider's
    record — the provider is asked for contact details and answers with contact
    details, so it is the only side of this that knows who was asked about.
    `index` is returned so the page can place each email on the right row
    without matching on a name, which breaks on duplicates and on the
    abbreviated names discovery sometimes yields.
    """
    if not req.people:
        raise HTTPException(status_code=400, detail="Select at least one person to enrich.")
    try:
        revealed = Enrichment().enrich_shortlist(req.people)
        return [
            {
                "index": index,
                "full_name": person.get("full_name") or "",
                "company": person.get("company") or "",
                "job_title": person.get("job_title") or "",
                "email": contact.primary_email,
            }
            for index, (person, contact) in enumerate(zip(req.people, revealed))
        ]
    except Exception as e:  # noqa: BLE001 — surface the provider's reason to the user
        raise HTTPException(status_code=502, detail=f"Enrichment failed: {e}")


@router.post("/reveal-phone")
def reveal_phone(req: PersonRequest, _user: dict = Depends(require_authed)):
    """Reveal one phone number. Separate on purpose: phone credit is spent
    deliberately, one person at a time, never as a side effect of enrichment."""
    try:
        contact = Enrichment().reveal_phone(req.person)
        return {
            "full_name": req.person.get("full_name") or "",
            "phone": contact.primary_phone,
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Could not reveal a phone number: {e}")


# ── Shortlists ──────────────────────────────────────────────────────────────
# A search you cannot keep is a scratchpad. Saving a shortlist is what turns
# X-ray into somewhere you work: the people you picked, the enrichment you paid
# for, and the search that produced them, still there tomorrow.


class ShortlistSave(BaseModel):
    name: str
    people: list[dict]
    #: What produced this — the company searched, or the signal swept for.
    source: str = ""
    id: Optional[str] = None


# Shortlists saved by the retired `lead` X-ray used `title`/`rows`; the sales
# agent uses `name`/`people`. Both are read here so a shortlist saved before the
# migration still opens with its people, rather than appearing empty.
def _shortlist_people(record: dict) -> list:
    return record.get("people") or record.get("rows") or []


def _shortlist_name(record: dict) -> str:
    return record.get("name") or record.get("title") or "Untitled"


def _shortlist_source(record: dict) -> str:
    return record.get("source") or record.get("company") or record.get("signal") or ""


@router.get("/shortlists")
def list_shortlists(request: Request, user: dict = Depends(require_authed)):
    """Saved shortlists, newest first, without their people — a browsable index."""
    saved = storage.load_user_prospect_lists(user["username"], sandbox=is_sandbox(request))
    return [
        {
            "id": s.get("id"),
            "name": _shortlist_name(s),
            "source": _shortlist_source(s),
            "count": len(_shortlist_people(s)),
            "updated_at": s.get("updated_at") or s.get("created_at") or "",
        }
        for s in saved
    ]


@router.get("/shortlists/{shortlist_id}")
def get_shortlist(shortlist_id: str, request: Request, user: dict = Depends(require_authed)):
    saved = storage.get_prospect_list(shortlist_id, user["username"], sandbox=is_sandbox(request))
    if saved is None:
        raise HTTPException(status_code=404, detail="That shortlist no longer exists.")
    # Normalised on the way out, so the page never has to know which era it came from.
    return {
        "id": saved.get("id"),
        "name": _shortlist_name(saved),
        "source": _shortlist_source(saved),
        "people": _shortlist_people(saved),
        "updated_at": saved.get("updated_at") or saved.get("created_at") or "",
    }


@router.post("/shortlists", status_code=201)
def save_shortlist(req: ShortlistSave, request: Request, user: dict = Depends(require_authed)):
    """Keep a shortlist, including any emails already revealed on it."""
    if not req.people:
        raise HTTPException(status_code=400, detail="There is nobody to save.")
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Give the shortlist a name.")

    record = storage.save_prospect_list(
        {
            "id": req.id,
            "name": req.name.strip(),
            "source": req.source,
            "people": req.people,
        },
        username=user["username"],
        sandbox=is_sandbox(request),
    )
    if record is None:
        # Somebody else's id. Answered the same way as an id that never existed,
        # and in the same words as `get_shortlist`, so a saved shortlist cannot be
        # probed for by watching which ids come back differently.
        raise HTTPException(status_code=404, detail="That shortlist no longer exists.")
    return {"id": record["id"], "name": record["name"], "count": len(req.people)}


@router.delete("/shortlists/{shortlist_id}")
def delete_shortlist(shortlist_id: str, request: Request, user: dict = Depends(require_authed)):
    if not storage.delete_prospect_list(shortlist_id, user["username"], sandbox=is_sandbox(request)):
        raise HTTPException(status_code=404, detail="That shortlist no longer exists.")
    return {"ok": True}
