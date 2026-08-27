from __future__ import annotations

import json
import os
import uuid
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents.mind.blocks import owl_identity_tail, owl_system_blocks
from agents.mind.contributions_block import render_own_contributions_block
from agents.mind import core as mind
from agents.mind import memory, memory_seed, persona
from agents.shared.vault import load_vault_for_analysis
from agents.owl.routing import HAIKU_MODEL, SONNET_MODEL, select_model
from agents.owl import projects, storage
from agents.owl.routes_organisation import router as organisation_router
from agents.owl.topics import extract_topics
from agents.sales import tools as sales_tools
from agents.shared import vault as vault_mod
from agents.shared.notifications import send_admin_email
from auth import require_authed

router = APIRouter(prefix="/api/owl", tags=["owl"])

CORRECTION_CLASSIFIER_PROMPT = """You are a classifier. Given the user's last message and Owl's previous answer, decide whether the user is correcting Owl (telling Owl that something it said was wrong or incomplete).

Return ONLY a JSON object — no prose, no markdown — with these keys:
  is_correction (bool): true only if the user is contradicting or correcting Owl's previous answer
  topic (string): short topic label (3-8 words) if is_correction, else ""
  what_owl_said (string): one-sentence quote/paraphrase of the part of Owl's reply being corrected, else ""
  user_correction (string): one-sentence summary of what the user is teaching, else ""
  title (string): a short title for this correction (5-10 words), else ""
  description (string): one-sentence summary suitable as a file description, else ""

Be conservative — only mark is_correction=true when the user is clearly disagreeing with Owl, not just adding context or asking a follow-up."""


TITLE_PROMPT = """You name a conversation, the way a person would name a note.

Return ONLY the title — no quotes, no prose, no markdown, no trailing full stop.

Rules:
  - Between three and seven words.
  - Name the subject, not the act: "Case study for a tier-one bank", never
    "User asks about a case study".
  - Sentence case. Keep product and protocol names as they are written.
  - British English."""

TITLE_MAX_WORDS = 10


def _generate_title(user_msg: str, owl_reply: str) -> str:
    """Name a conversation from its opening exchange.

    Returns "" on any failure, which leaves the provisional title the row was
    created with — a truncation of the opening message. Naming is a nicety, so
    it must never be able to cost the conversation itself.
    """
    if not user_msg.strip():
        return ""
    try:
        result = mind.classify(
            system=TITLE_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Question:\n{user_msg[:1000]}\n\nAnswer:\n{owl_reply[:1000]}",
            }],
            max_tokens=40,
        )
        # A model that ignores "no prose" tends to do it across several lines, so
        # only the first is trusted, and an over-long one is treated as a refusal
        # rather than truncated into a worse title than we already have.
        title = result.text.strip().splitlines()[0].strip().strip('"').rstrip(".")
        if not title or len(title.split()) > TITLE_MAX_WORDS:
            return ""
        return title[:80]
    except Exception as e:
        print(f"[owl] title generation failed: {e}")
        return ""


def _classify_correction(owl_reply: str, user_msg: str) -> Optional[dict]:
    """Run a small Haiku classifier to detect correction intent. Returns the proposed correction dict if detected, else None."""
    if not owl_reply.strip() or not user_msg.strip():
        return None
    try:
        result = mind.classify(
            system=CORRECTION_CLASSIFIER_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Owl's previous answer:\n{owl_reply[:2000]}\n\nUser's reply:\n{user_msg[:1000]}",
            }],
            max_tokens=400,
        )
        raw = result.text
        # Find the JSON object in the response
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1:
            return None
        parsed = json.loads(raw[start:end + 1])
        if not parsed.get("is_correction"):
            return None
        return {
            "topic": str(parsed.get("topic", "")).strip(),
            "what_owl_said": str(parsed.get("what_owl_said", "")).strip(),
            "user_correction": str(parsed.get("user_correction", "")).strip(),
            "title": str(parsed.get("title", "")).strip(),
            "description": str(parsed.get("description", "")).strip(),
        }
    except Exception as e:
        print(f"[owl] correction classifier failed: {e}")
        return None


class ChatRequest(BaseModel):
    messages: list[dict]
    conversation_id: Optional[str] = None
    # When set, Owl is grounded in this analysed call: the vault is scoped to the
    # call, its analysis is injected as default context, and the verbatim
    # transcript is available only via the fetch_transcript tool (deep-dive).
    call_id: Optional[str] = None
    # The project a NEW conversation should be filed under. Ignored when
    # continuing an existing conversation, which already knows its project.
    project_id: Optional[str] = None


def _project_instructions_block(project_id: Optional[str], username: str) -> str:
    """A project's standing instructions, framed for the system tail."""
    instructions = projects.project_instructions(project_id, username)
    if not instructions:
        return ""
    return (
        "Standing instructions for the project this conversation belongs to. "
        "They shape how you answer here, but never override Company Truth or "
        "the knowledge-governance rules above:\n\n" + instructions
    )


# Tool that exposes the stored transcript on demand. Owl answers from the
# injected analysis by default and calls this only for verbatim detail, so the
# transcript's tokens enter context only when a question actually needs them.
FETCH_TRANSCRIPT_TOOL = {
    "name": "fetch_transcript",
    "description": (
        "Retrieve the verbatim transcript of the call under discussion, or the "
        "excerpts matching a query. Prefer answering from the call analysis "
        "already provided; call this ONLY when you need the exact wording of what "
        "was said and the analysis doesn't capture it."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Optional keyword or phrase to locate relevant excerpts. Omit to fetch the full transcript.",
            }
        },
    },
}

_TRANSCRIPT_FULL_CHAR_CAP = 48000  # ~12k tokens — bound the worst case


def _load_call_session(call_id: str, username: str) -> Optional[dict]:
    """Find an analysed call owned by this user (live sessions only)."""
    from agents.sales.store import calls as calls_store  # lazy: avoid import cycle

    session = calls_store.get_session(call_id, username, sandbox=False)
    # The store answers for any session; only an analysed call can ground a chat.
    if session is not None and session.get("type") == "call_analysis":
        return session
    return None


def _call_context_md(result: dict) -> str:
    """Format the stored analysis as the call's default ('contained') context."""
    if not isinstance(result, dict):
        return ""

    def block(label: str, key: str) -> str:
        items = [str(x).strip() for x in (result.get(key) or []) if str(x).strip()]
        if not items:
            return ""
        return f"\n{label}:\n" + "\n".join(f"- {x}" for x in items)

    parts = [
        "# Current Call — Analysis (your primary grounding)",
        "",
        "Answer from this analysis first. Use the fetch_transcript tool only when "
        "the user needs verbatim detail this analysis doesn't capture.",
        "",
        f"Summary: {result.get('summary', '') or '—'}",
        block("Buying signals", "buying_signals"),
        block("Objections", "objections"),
        block("Concepts mentioned", "concepts_mentioned"),
        block("Talking points", "talking_points"),
    ]
    return "\n".join(p for p in parts if p)


def _owl_call_system_blocks(username: str, call_session: dict) -> list[dict]:
    """Owl system blocks grounded in one call: persona + scoped vault + analysis.

    Byte-stable for a given call, so it stays cacheable across the conversation's
    turns (cache_control kept). The transcript is NOT included — it arrives only
    through the fetch_transcript tool.
    """
    transcript = call_session.get("transcript", "") or ""
    result = call_session.get("result", {}) or {}
    scoped_vault = load_vault_for_analysis(transcript)
    context = _call_context_md(result)
    return persona.system_blocks(
        role_overlay=persona.CHAT_STANCE,
        extra_overlay=context,
        vault_knowledge=scoped_vault,
        tail=owl_identity_tail(username),
        memory_block=memory.render_memory_block(username),
        cache=True,
    )


def _transcript_response(transcript: str, query: Optional[str]) -> str:
    """Full transcript (capped) or excerpts around a query — the tool's payload."""
    if not transcript.strip():
        return "No transcript is stored for this call."
    if not query or not query.strip():
        text = transcript[:_TRANSCRIPT_FULL_CHAR_CAP]
        if len(transcript) > _TRANSCRIPT_FULL_CHAR_CAP:
            text += "\n\n[transcript truncated]"
        return text
    q = query.strip().lower()
    paras = [p.strip() for p in transcript.split("\n") if p.strip()]
    hits = [p for p in paras if q in p.lower()]
    if not hits:
        return f"No transcript lines match '{query}'. Full transcript starts:\n\n" + transcript[:4000]
    out, total = [], 0
    for h in hits[:20]:
        out.append(h)
        total += len(h)
        if total > 16000:
            break
    return f"Transcript excerpts matching '{query}':\n\n" + "\n\n".join(out)


class RenameRequest(BaseModel):
    title: str


class CorrectionSubmitRequest(BaseModel):
    session_id: str
    title: str
    description: str
    topic: str
    what_owl_said: str
    user_correction: str
    suggested_source: Optional[str] = ""


@router.post("/stream")
async def owl_stream(req: ChatRequest, user: dict = Depends(require_authed)):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set.")

    username = user["username"]
    memory_seed.seed_if_empty(username)  # one-time backfill of accounts from existing stores

    last_user_msg = ""
    for m in reversed(req.messages):
        if m.get("role") == "user":
            last_user_msg = m.get("content", "") if isinstance(m.get("content"), str) else ""
            break

    # Find Owl's previous reply (the assistant turn just before this user message)
    prev_owl_reply = ""
    seen_last_user = False
    for m in reversed(req.messages):
        if not seen_last_user:
            if m.get("role") == "user":
                seen_last_user = True
            continue
        if m.get("role") == "assistant":
            prev_owl_reply = m.get("content", "") if isinstance(m.get("content"), str) else ""
            break

    # Resolve a stable conversation id: continue the one the client sent (if the
    # user owns it), otherwise start a fresh conversation.
    # A continuing conversation already knows its project; a new one takes the
    # project the client started it in, if the user owns that project.
    if req.conversation_id and storage.conversation_exists(req.conversation_id, username):
        session_id = req.conversation_id
        project_id = storage.project_of(session_id, username)
    else:
        session_id = uuid.uuid4().hex
        project_id = req.project_id if projects.get_project(req.project_id or "", username) else None

    # Lock the model to the conversation: the first turn decides, later turns
    # reuse it so the voice/quality doesn't flip-flop mid-conversation.
    locked = storage.model_locked_for(session_id, username)
    if locked:
        model = SONNET_MODEL if locked == "sonnet" else HAIKU_MODEL
    else:
        model = select_model(last_user_msg)
    model_label = "haiku" if "haiku" in model else "sonnet"

    # Call-aware grounding: if the client passed a call_id the user owns, scope
    # the vault to that call, inject its analysis, and expose the transcript via
    # a tool. Otherwise fall back to general Owl chat (full cached vault).
    call_session = _load_call_session(req.call_id, username) if req.call_id else None
    if call_session is not None:
        system = _owl_call_system_blocks(username, call_session)
        tools = [FETCH_TRANSCRIPT_TOOL]
        call_transcript = call_session.get("transcript", "") or ""
    else:
        system = owl_system_blocks(
            username,
            role_overlay=persona.CHAT_STANCE,
            memory_block=memory.render_memory_block(username),
            project_block=_project_instructions_block(project_id, username),
            # Presentation only — the vault this reads from is the same one every
            # user gets. It tells Owl which of the shared knowledge is this
            # person's own, so they can keep building on it.
            contributions_block=render_own_contributions_block(
                username, user.get("name", "") if isinstance(user, dict) else "",
            ),
        )
        # The sales agents, as tools. Owl can therefore run any of them from the
        # conversation — the same agents their dedicated pages drive. Empty until
        # the first agent registers, in which case this stays None and the turn
        # is an ordinary chat.
        tools = sales_tools.specs() or None
        call_transcript = ""

    # Read before the row is created: a generated title is only ever given to a
    # conversation that is opening, never imposed on one already named.
    opens_conversation = not storage.conversation_exists(session_id, username)

    # Persist the conversation row + user message BEFORE streaming, so the id we
    # hand the client is always backed by a real row and the user's message is
    # never lost if generation errors or returns empty.
    storage.append_user_turn(
        session_id,
        username,
        last_user_msg,
        title=(last_user_msg[:80] or "Chat"),
        model_used=model_label,
        topics=extract_topics(last_user_msg),
        project_id=project_id,
    )

    async def generate():
        # Tell the client which conversation this turn belongs to, so it can
        # persist the id and send it back on the next turn.
        yield f"data: {json.dumps({'conversation_id': session_id})}\n\n"
        full_response: list[str] = []

        def _dispatch(name: str, tool_input: dict) -> str:
            # Grounded call turns expose the transcript; every other turn exposes
            # the sales agents. One dispatcher, so a tool can never be offered
            # without something able to run it.
            if name == "fetch_transcript":
                q = tool_input.get("query") if isinstance(tool_input, dict) else None
                return _transcript_response(call_transcript, q)
            return sales_tools.dispatch(username, name, tool_input or {})

        try:
            # Owl Core chat_stream: dynamic model (locked/router), the bounded
            # fetch_transcript tool loop, and the max_tokens continuation so long
            # answers stream to completion instead of truncating.
            for event in mind.chat_stream(
                system=system,
                messages=list(req.messages),
                model=model,
                tools=tools,
                tool_dispatch=_dispatch if tools else None,
            ):
                if event["type"] == "text":
                    full_response.append(event["text"])
                    yield f"data: {json.dumps({'text': event['text']})}\n\n"
            yield f"data: {json.dumps({'model': model})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            return

        full_text = "".join(full_response)

        # A conversation earns its name from the exchange, not from the first 80
        # characters of the question. Done after the answer has streamed, so
        # naming never delays a single token of it.
        if opens_conversation and full_text.strip():
            title = _generate_title(last_user_msg, full_text)
            if title:
                storage.rename_conversation(session_id, username, title)
                yield f"data: {json.dumps({'title': title})}\n\n"

        # Run correction classifier — only if there's a previous Owl reply to correct
        proposed_correction = None
        if prev_owl_reply.strip():
            proposed_correction = _classify_correction(prev_owl_reply, last_user_msg)
        if proposed_correction:
            payload = {
                "session_id": session_id,
                **proposed_correction,
            }
            yield f"data: {json.dumps({'proposed_correction': payload})}\n\n"

        yield "data: [DONE]\n\n"

        if not full_text.strip():
            # Nothing usable generated. The user turn was already persisted at
            # stream start, so the conversation and the user's message survive;
            # we just skip appending an empty assistant reply.
            return

        storage.append_assistant_turn(
            session_id,
            username,
            full_text,
            model_used=model_label,
            topics=extract_topics(last_user_msg),
            pending_correction_draft=proposed_correction,
        )

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/sessions")
def get_owl_sessions(
    q: Optional[str] = None,
    project_id: Optional[str] = None,
    folder_id: Optional[str] = None,
    unfiled: bool = False,
    include_archived: bool = False,
    user: dict = Depends(require_authed),
):
    """List the user's conversations — pinned first, then newest, no message bodies.

    Filters compose: ``?q=`` searches titles and message bodies; ``project_id``
    and ``folder_id`` scope to a branch of the tree; ``unfiled=true`` asks for
    the conversations that belong to no project, which is a real query rather
    than the absence of a filter.
    """
    placement = {}
    if unfiled:
        placement = {"project_id": None, "folder_id": None}
    else:
        if project_id is not None:
            placement["project_id"] = project_id
        if folder_id is not None:
            placement["folder_id"] = folder_id
    return storage.list_conversations(
        user["username"], query=q, include_archived=include_archived, **placement,
    )


@router.get("/sessions/{session_id}")
def get_owl_session(session_id: str, user: dict = Depends(require_authed)):
    session = storage.get_conversation(session_id, user["username"])
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return session


@router.patch("/sessions/{session_id}")
def rename_owl_session(session_id: str, req: RenameRequest, user: dict = Depends(require_authed)):
    title = req.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    if not storage.rename_conversation(session_id, user["username"], title):
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"ok": True, "title": title}


@router.delete("/sessions")
def delete_all_owl_sessions(user: dict = Depends(require_authed)):
    """Delete every conversation this user has, archived ones included.

    Declared before the `/sessions/{session_id}` route below only for reading
    order — the paths are distinct, so no shadowing is at stake. Irreversible by
    design: transcripts are destroyed, and the UI gates it behind a counted
    confirmation rather than this endpoint doing so.
    """
    deleted = storage.delete_all_conversations(user["username"])
    return {"ok": True, "deleted": deleted}


@router.delete("/sessions/{session_id}")
def delete_owl_session(session_id: str, user: dict = Depends(require_authed)):
    if not storage.delete_conversation(session_id, user["username"]):
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"ok": True}


@router.post("/corrections/submit")
def submit_correction(req: CorrectionSubmitRequest, user: dict = Depends(require_authed)):
    """User confirms a proposed correction. Writes to vault/added/pending and notifies admin."""
    title = req.title.strip()
    description = req.description.strip()
    user_correction = req.user_correction.strip()
    if not title or not description or not user_correction:
        raise HTTPException(status_code=400, detail="title, description, and user_correction are required")

    body_parts = [
        f"**Topic:** {req.topic.strip()}" if req.topic.strip() else "",
        f"**What Owl said:** {req.what_owl_said.strip()}" if req.what_owl_said.strip() else "",
        f"**User correction:** {user_correction}",
    ]
    if (req.suggested_source or "").strip():
        body_parts.append(f"**Suggested source:** {req.suggested_source.strip()}")
    body = "\n\n".join(p for p in body_parts if p)

    path = vault_mod.write_added_knowledge(
        title=title,
        description=description,
        content=body,
        topic=req.topic.strip(),
        what_owl_said=req.what_owl_said.strip(),
        user_correction=user_correction,
        submitted_by=user["username"],
        session_id=req.session_id,
        suggested_source=(req.suggested_source or "").strip(),
    )

    send_admin_email(
        subject="[Cadence] New Owl correction pending review",
        body=(
            f"User {user['username']} submitted a correction:\n\n"
            f"Title: {title}\n"
            f"Description: {description}\n"
            f"Topic: {req.topic}\n\n"
            f"What Owl said: {req.what_owl_said}\n\n"
            f"User correction: {user_correction}\n\n"
            f"Review at /admin (Pending Approvals tab)."
        ),
    )

    return {"ok": True, "filename": path.name}


# Organisation (projects, folders, placement, search) shares the /api/owl prefix
# but is a separate job from chat, so it lives in its own module.
router.include_router(organisation_router)
