"""The vault, readable — `/api/wiki`.

Serves the company's knowledge to a human instead of to a prompt. The reading
itself lives in `agents/shared/wiki.py`; this module is transport only.

Responses are shaped explicitly rather than dumped from the dataclasses, so the
API surface changes on purpose and never by a field being added upstream.

Naming: `/api/wiki` is the vault — the compiled knowledge anyone can read.
`/api/knowledge` remains the *files* Owl is given to read, which is a different
job with a different audience (admins).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from agents.sales.store import calls as call_store
from agents.shared import sources, wiki
from auth import is_sandbox, require_authed

router = APIRouter(prefix="/api/wiki", tags=["wiki"], dependencies=[Depends(require_authed)])


def _node_json(node: wiki.Node, viewer: str = "") -> dict:
    """One node for the API.

    `mine` says the viewer contributed this page. It is presentation, not
    permission: the corpus is readable by everyone regardless, and this only lets
    a contributor find their own work in it — the same shape as the viewer-aware
    status in `agents/shared/sources.py`.
    """
    return {
        "slug": node.slug,
        "title": node.title,
        "type": node.type,
        "pillar": node.pillar,
        "tags": list(node.tags),
        "aliases": list(node.aliases),
        "tagline": node.tagline,
        "contributed_by": node.contributed_by,
        "mine": bool(viewer) and node.contributed_by.casefold() == viewer.casefold(),
    }


@router.get("/index")
def get_index(
    mine: bool = Query(False, description="Only pages the viewer contributed"),
    user: dict = Depends(require_authed),
):
    """Every knowledge page, with the type and tag vocabularies the UI filters on.

    `mine=true` narrows to the viewer's own contributions. It is a convenience for
    someone who has just imported a body of work and wants to see it, never a
    boundary — the unfiltered index is the default and shows the whole corpus.
    """
    viewer = user["username"]
    nodes = wiki.index()
    # `mine_total` counts before the filter, so the UI can offer the toggle only
    # to people who have contributed something.
    mine_total = sum(1 for n in nodes if n.contributed_by.casefold() == viewer.casefold())
    if mine:
        nodes = [n for n in nodes if n.contributed_by.casefold() == viewer.casefold()]
    tags = sorted({tag for node in nodes for tag in node.tags})
    return {
        "nodes": [_node_json(n, viewer) for n in nodes],
        "types": [t for t in wiki.KNOWN_TYPES if any(n.type == t for n in nodes)],
        "tags": tags,
        "total": len(nodes),
        "mine_total": mine_total,
    }


@router.get("/search")
def get_search(q: str = Query("", description="Title, alias, tag or body text"),
               limit: int = Query(50, ge=1, le=200),
               mine: bool = Query(False, description="Only pages the viewer contributed"),
               user: dict = Depends(require_authed)):
    """Ranked results. `matched_on` is returned so the UI can say why a hit is here.

    `mine=true` narrows to the viewer's own contributions, as on the index. Ranking
    is unchanged — the filter is applied to the results, not to the search.
    """
    viewer = user["username"]
    hits = wiki.search(q, limit=limit)
    if mine:
        hits = [h for h in hits if h.node.contributed_by.casefold() == viewer.casefold()]
    return {
        "query": q,
        "hits": [
            {"node": _node_json(h.node, viewer), "rank": h.rank, "matched_on": h.matched_on}
            for h in hits
        ],
        "total": len(hits),
    }


@router.get("/page/{slug:path}")
def get_page(slug: str, request: Request, user: dict = Depends(require_authed)):
    """One page as blocks, with its links out, its links back, and its sources.

    `unresolved` lists `[[targets]]` the corpus has no page for. They are reported
    rather than hidden: the renderer shows them as plain text, and the list is
    what makes the gap fixable.

    `sources` is where the page's knowledge came from — empty for company-tier
    pages, which cite nothing because they are the company's own truth. A source
    carries a status rather than a link: the vault is shared but transcripts are
    not, and a call can be gone entirely. The frontend owns its own URLs, so the
    call id travels and the href does not.
    """
    page = wiki.page(slug)
    if page is None:
        raise HTTPException(status_code=404, detail=f"No wiki page for '{slug}'.")

    records = sources.call_records(call_store.load_sessions(is_sandbox(request)))
    cited = sources.sources_for(page, records, user["username"])

    return {
        **_node_json(page.node, user["username"]),
        "blocks": [dict(block) for block in page.blocks],
        "links": [{"target": link.target, "slug": link.slug} for link in page.links],
        "backlinks": [_node_json(n, user["username"]) for n in page.backlinks],
        "unresolved": list(page.unresolved),
        "sources": [
            {
                "call_id": source.call_id,
                "title": source.title,
                "contributed_by": source.contributed_by,
                "captured_at": source.captured_at,
                "status": source.status,
            }
            for source in cited
        ],
    }
