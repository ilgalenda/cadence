"""Call Analysis's surface — `/api/sales/calls`.

Reading a call, and the library of what has been read. Moved off the bare `/api`
prefix `agents/calls` used, which sat above every other agent's namespace and made
the module look like the platform rather than one agent in it.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from agents.sales.call_analysis import agent
from agents.sales.store import calls as store
from agents.shared import sources, wiki
from auth import is_sandbox, require_authed

router = APIRouter(prefix="/calls", tags=["sales-call-analysis"])


class AnalyseRequest(BaseModel):
    text: str
    title: str = ""


class ProductFitRequest(BaseModel):
    product_name: str = ""


@router.post("/analyse")
def analyse(req: AnalyseRequest, request: Request, user: dict = Depends(require_authed)):
    """Read a pasted transcript, file it, and stage what it taught us."""
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Paste a transcript to analyse.")

    out = agent.analyse(
        user["username"],
        transcript=req.text,
        title=req.title,
        name=user.get("name") or "",
        role=user.get("role") or "",
        sandbox=is_sandbox(request),
    )
    # A failed reading still filed the call, so this is a 502 rather than a silent
    # empty result: the person needs to know the reading did not happen.
    if out["error"] and out["error"] != "no_transcript":
        raise HTTPException(status_code=502, detail=f"Could not read that transcript: {out['error']}")
    return out


def _index_view(result: dict) -> dict:
    """What a library row shows of a reading, without the reading itself.

    The index used to ship the whole nested `result` and the library read
    `call.summary` off the top level, so every row rendered an em dash and the
    search box matched on title while claiming to search summaries. The shape the
    list returns is now the shape the list is read at.
    """
    recommendation = result.get("product_recommendation") or {}
    return {
        "summary": result.get("summary") or "",
        "product": recommendation.get("primary") or "",
        "signals": len(result.get("buying_signals") or []),
        "objections": len(result.get("objections") or []),
        "extracts": len(result.get("knowledge_extracts") or []),
    }


@router.get("")
def list_calls(request: Request, user: dict = Depends(require_authed)):
    """This user's analysed calls, newest first, without their transcripts.

    The transcript is the bulk of a record and the index never shows it, so it is
    dropped here rather than shipped to the browser and ignored. The reading is
    flattened to the handful of fields a row displays, for the same reason.
    """
    sandbox = is_sandbox(request)
    # One index read for the whole list rather than one per row. `extracts`
    # counts what the model proposed; `knowledge` counts what reached the vault,
    # and they differ whenever a term was already known.
    filed = sources.counts_by_call()
    return [
        {
            "id": session.get("id"),
            "title": session.get("title") or "Untitled call",
            "timestamp": session.get("timestamp") or "",
            "knowledge": filed.get(str(session.get("id") or ""), 0),
            **_index_view(session.get("result") or {}),
        }
        for session in store.load_user_sessions(user["username"], sandbox)
        if session.get("type") == "call_analysis"
    ]


@router.get("/{call_id}")
def get_call(call_id: str, request: Request, user: dict = Depends(require_authed)):
    session = store.get_session(call_id, user["username"], sandbox=is_sandbox(request))
    if session is None or session.get("type") != "call_analysis":
        raise HTTPException(status_code=404, detail="That call is no longer here.")
    return {**session, "result": _with_term_pages(session.get("result") or {})}


def _with_term_pages(result: dict) -> dict:
    """The reading, with each new term told which wiki page it can be read on.

    Resolved here rather than slugified in the browser: `write_glossary_term`
    skips a term the company glossary already defines, so the page a term points
    at is frequently one this call did not create. Only the resolver knows which,
    and a term it cannot place gets None rather than a link to nothing.

    A copy, never a mutation — the session on disk records what the model said,
    and where a term ended up is a fact about the vault, not about the reading.
    """
    terms = result.get("new_terms")
    if not isinstance(terms, list):
        return result

    placed = []
    for term in terms:
        if not isinstance(term, dict):
            continue
        name = str(term.get("term") or "").strip()
        placed.append({**term, "page_slug": wiki.resolve_link(name) if name else None})
    return {**result, "new_terms": placed}


@router.get("/{call_id}/knowledge")
def call_knowledge(call_id: str, request: Request, user: dict = Depends(require_authed)):
    """What this call put into the vault — the reverse of a page's sources.

    Two populations in one list: glossary terms, which are wiki pages, and
    learnings, which are not (`dynamic/calls/` sits outside the wiki index by
    design). A learning carries `wiki_slug: null` rather than being hidden — it
    is still something the call taught.
    """
    session = store.get_session(call_id, user["username"], sandbox=is_sandbox(request))
    if session is None or session.get("type") != "call_analysis":
        raise HTTPException(status_code=404, detail="That call is no longer here.")

    pages = sources.pages_from_call(call_id)
    return {
        "call_id": call_id,
        "title": session.get("title") or "Untitled call",
        "pages": [
            {
                "key": page.key,
                "title": page.title,
                "type": page.type,
                "summary": page.summary,
                "wiki_slug": page.wiki_slug,
                "contributed_by": page.contributed_by,
                "captured_at": page.captured_at,
            }
            for page in pages
        ],
        "total": len(pages),
    }


@router.post("/{call_id}/product-fit")
def product_fit(
    call_id: str,
    req: ProductFitRequest,
    request: Request,
    user: dict = Depends(require_authed),
):
    """Best-fit products for an already-analysed call. Opt-in: it costs a turn."""
    try:
        return agent.product_fit(
            user["username"],
            call_id=call_id,
            product_name=req.product_name,
            sandbox=is_sandbox(request),
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="That call is no longer here.")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Product fit failed: {e}")


@router.delete("/{call_id}")
def delete_call(call_id: str, request: Request, user: dict = Depends(require_authed)):
    if not store.delete_session(call_id, user["username"], sandbox=is_sandbox(request)):
        raise HTTPException(status_code=404, detail="That call is no longer here.")
    return {"ok": True}
