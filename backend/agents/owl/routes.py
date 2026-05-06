import json
import os
import uuid

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents.lead.knowledge import owl_system_prompt
from agents.owl.routing import select_model
from agents.owl.storage import format_timestamp, load_user_owl_sessions, save_owl_session
from agents.owl.topics import extract_topics
from auth import require_authed

router = APIRouter(prefix="/api/owl", tags=["owl"])


class ChatRequest(BaseModel):
    messages: list[dict]


@router.post("/stream")
async def owl_stream(req: ChatRequest, user: dict = Depends(require_authed)):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set.")

    client = anthropic.Anthropic(api_key=api_key)
    username = user["username"]

    last_user_msg = ""
    for m in reversed(req.messages):
        if m.get("role") == "user":
            last_user_msg = m.get("content", "") if isinstance(m.get("content"), str) else ""
            break

    model = select_model(last_user_msg)
    system = owl_system_prompt(username)
    session_id = uuid.uuid4().hex  # fixed before streaming so GET can reference it

    async def generate():
        full_response: list[str] = []
        try:
            with client.messages.stream(
                model=model,
                max_tokens=1024,
                system=system,
                messages=req.messages,
            ) as stream:
                for text in stream.text_stream:
                    full_response.append(text)
                    yield f"data: {json.dumps({'text': text})}\n\n"
            yield f"data: {json.dumps({'model': model})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            return

        full_text = "".join(full_response)
        all_messages = list(req.messages) + [{"role": "assistant", "content": full_text}]
        preview = last_user_msg[:80] or "Chat"
        topics = extract_topics(last_user_msg)
        model_label = "haiku" if "haiku" in model else "sonnet"
        save_owl_session(
            {
                "id": session_id,
                "title": preview,
                "type": "chat",
                "timestamp": format_timestamp(),
                "model_used": model_label,
                "topics": topics,
                "messages": all_messages,
            },
            username,
        )

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/sessions")
def get_owl_sessions(user: dict = Depends(require_authed)):
    # Strip messages from list view to keep payload small
    sessions = load_user_owl_sessions(user["username"])
    return [{k: v for k, v in s.items() if k != "messages"} for s in sessions]


@router.get("/sessions/{session_id}")
def get_owl_session(session_id: str, user: dict = Depends(require_authed)):
    for s in load_user_owl_sessions(user["username"]):
        if s.get("id") == session_id:
            return s
    raise HTTPException(status_code=404, detail="Session not found.")
