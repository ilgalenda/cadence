from __future__ import annotations
"""Onboarding agent — a role-aware, grounded guided chat for new users.

Reuses the platform's streaming-chat shape (same SSE events as Owl, so the
frontend `streamChat` client works unchanged) and the shared knowledge vault for
grounding. A lightweight per-user checklist tracks progress.
"""
import json
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents.onboarding import knowledge, storage
from agents.shared import anthropic_client
from auth import is_sandbox, require_agent_access

_user = require_agent_access("onboarding")
router = APIRouter(prefix="/api/onboarding", tags=["onboarding"], dependencies=[Depends(_user)])


class ChatRequest(BaseModel):
    messages: list[dict]
    conversation_id: Optional[str] = None
    call_id: Optional[str] = None  # accepted for client compatibility; unused


@router.post("/stream")
def stream(req: ChatRequest, request: Request, role: str = Query(default=""), user: dict = Depends(_user)):
    blocks = knowledge.onboarding_system_blocks(user["username"], role or user.get("role", ""))

    def generate():
        client = anthropic_client.get_client()
        try:
            with anthropic_client.slot():
                with client.messages.stream(
                    model=anthropic_client.SONNET,
                    max_tokens=1024,
                    system=blocks,
                    messages=req.messages,
                ) as s:
                    for text in s.text_stream:
                        yield f"data: {json.dumps({'text': text})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            return
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Checklist progress (one record per user, id == username)
# ---------------------------------------------------------------------------

class ProgressUpdate(BaseModel):
    step: str
    done: bool = True


def _progress(user: dict, sandbox: bool) -> dict:
    return storage.progress.get(user["username"], sandbox=sandbox) or {"id": user["username"], "completed": []}


@router.get("/progress")
def get_progress(request: Request, user: dict = Depends(_user)):
    return _progress(user, is_sandbox(request))


@router.post("/progress")
def update_progress(upd: ProgressUpdate, request: Request, user: dict = Depends(_user)):
    sandbox = is_sandbox(request)
    rec = _progress(user, sandbox)
    completed = set(rec.get("completed", []))
    completed.add(upd.step) if upd.done else completed.discard(upd.step)
    rec["completed"] = sorted(completed)
    return storage.progress.upsert(rec, username=user["username"], sandbox=sandbox)


@router.get("/stats")
def stats(request: Request, user: dict = Depends(_user)):
    rec = _progress(user, is_sandbox(request))
    return {"steps_completed": len(rec.get("completed", []))}
