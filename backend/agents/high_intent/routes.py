from __future__ import annotations
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from agents.high_intent import pipeline, storage
from auth import require_admin

# Admin-only: no regular-user access; sandbox mode is always forced in storage layer
_admin = require_admin

router = APIRouter(prefix="/api/high-intent", tags=["high-intent"], dependencies=[Depends(_admin)])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class IcpConfigSave(BaseModel):
    signal_type: str
    config: dict


class DetectRequest(BaseModel):
    signal_type: str


class ComposeRequest(BaseModel):
    signal_id: str


class SignalPatch(BaseModel):
    status: Optional[str] = None
    timebeat_product_fit: Optional[str] = None
    signal_strength: Optional[str] = None
    notes: Optional[str] = None


class FollowupRequest(BaseModel):
    signal_id: str
    reply_text: str


class MessagePatch(BaseModel):
    status: Optional[str] = None  # "approved" | "sent"
    touches: Optional[list[dict]] = None


# ---------------------------------------------------------------------------
# Meta — signal types + ICP field definitions
# ---------------------------------------------------------------------------

@router.get("/signal-types")
def get_signal_types(_user: dict = Depends(_admin)):
    return {
        "types": storage.SIGNAL_TYPES,
        "labels": storage.SIGNAL_TYPE_LABELS,
        "icp_fields": storage.ICP_FIELDS,
    }


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@router.get("/stats")
def get_stats(request: Request, user: dict = Depends(_admin)):
    return storage.stats(user["username"])


# ---------------------------------------------------------------------------
# ICP configuration
# ---------------------------------------------------------------------------

@router.get("/icp")
def get_all_icp(user: dict = Depends(_admin)):
    return storage.get_user_icp(user["username"])


@router.get("/icp/{signal_type}")
def get_icp(signal_type: str, user: dict = Depends(_admin)):
    if signal_type not in storage.SIGNAL_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown signal type: {signal_type}")
    config = storage.get_signal_icp(user["username"], signal_type)
    complete = storage.is_icp_complete(user["username"], signal_type)
    return {
        "signal_type": signal_type,
        "config": config or {},
        "complete": complete,
        "fields": storage.ICP_FIELDS.get(signal_type, []),
    }


@router.post("/icp")
def save_icp(req: IcpConfigSave, user: dict = Depends(_admin)):
    if req.signal_type not in storage.SIGNAL_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown signal type: {req.signal_type}")
    storage.save_signal_icp(user["username"], req.signal_type, req.config)
    return {"ok": True, "complete": storage.is_icp_complete(user["username"], req.signal_type)}


# ---------------------------------------------------------------------------
# Signal detection
# ---------------------------------------------------------------------------

@router.post("/detect")
def detect(req: DetectRequest, user: dict = Depends(_admin)):
    if req.signal_type not in storage.SIGNAL_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown signal type: {req.signal_type}")

    if not storage.is_icp_complete(user["username"], req.signal_type):
        raise HTTPException(
            status_code=422,
            detail=f"ICP for '{req.signal_type}' is incomplete. Set it up before running detection."
        )

    icp_config = storage.get_signal_icp(user["username"], req.signal_type) or {}
    result = pipeline.run_signal_detection(user["username"], req.signal_type, icp_config)

    if result.get("error") and not result.get("results"):
        raise HTTPException(status_code=500, detail=result["error"])

    saved = []
    for row in result["results"]:
        signal = storage.upsert_signal({
            "id": uuid.uuid4().hex,
            "signal_type": req.signal_type,
            "status": "pending",
            "profile": row,
            "icp_config": icp_config,
            "timebeat_product_fit": row.get("recommended_product", ""),
            "signal_strength": _confidence_to_strength(row.get("confidence", "low")),
        }, username=user["username"])
        saved.append(signal)

    return {
        "detected": len(saved),
        "signals": saved,
        "parse_error": result.get("error"),
    }


def _confidence_to_strength(confidence: str) -> str:
    return {"high": "hot", "medium": "warm", "low": "cold"}.get(confidence, "cold")


# ---------------------------------------------------------------------------
# Signal queue
# ---------------------------------------------------------------------------

@router.get("/queue")
def get_queue(user: dict = Depends(_admin)):
    signals = storage.load_user_signals(user["username"])
    queue = [s for s in signals if s.get("status") not in ("sent", "dismissed")]
    queue.sort(key=lambda s: {"hot": 0, "warm": 1, "cold": 2}.get(s.get("signal_strength", "cold"), 2))
    return queue


@router.get("/signals")
def get_signals(user: dict = Depends(_admin)):
    return storage.load_user_signals(user["username"])


@router.get("/signals/{signal_id}")
def get_signal(signal_id: str, user: dict = Depends(_admin)):
    s = storage.get_signal(signal_id, username=user["username"])
    if not s:
        raise HTTPException(status_code=404, detail="Signal not found")
    return s


@router.patch("/signals/{signal_id}")
def patch_signal(signal_id: str, req: SignalPatch, user: dict = Depends(_admin)):
    patch = {k: v for k, v in req.model_dump().items() if v is not None}
    updated = storage.patch_signal(signal_id, patch, username=user["username"])
    if not updated:
        raise HTTPException(status_code=404, detail="Signal not found")
    return updated


@router.delete("/signals/{signal_id}")
def delete_signal(signal_id: str, user: dict = Depends(_admin)):
    ok = storage.delete_signal(signal_id, username=user["username"])
    if not ok:
        raise HTTPException(status_code=404, detail="Signal not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Message composition
# ---------------------------------------------------------------------------

@router.post("/compose")
def compose(req: ComposeRequest, user: dict = Depends(_admin)):
    signal = storage.get_signal(req.signal_id, username=user["username"])
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")

    storage.patch_signal(req.signal_id, {"status": "composing"}, username=user["username"])

    result = pipeline.compose_message_sequence(user["username"], signal)

    if result.get("error") and not result.get("touches"):
        storage.patch_signal(req.signal_id, {"status": "pending"}, username=user["username"])
        raise HTTPException(status_code=500, detail=result["error"])

    message = storage.upsert_message({
        "signal_id": req.signal_id,
        "touches": result["touches"],
        "status": "draft",
    }, username=user["username"])

    storage.patch_signal(req.signal_id, {"status": "composed"}, username=user["username"])

    return {"message": message, "signal": storage.get_signal(req.signal_id, username=user["username"])}


@router.get("/messages/{signal_id}")
def get_message(signal_id: str, user: dict = Depends(_admin)):
    m = storage.get_message_for_signal(signal_id, username=user["username"])
    if not m:
        raise HTTPException(status_code=404, detail="No message for this signal")
    return m


@router.patch("/messages/{message_id}")
def patch_message(message_id: str, req: MessagePatch, user: dict = Depends(_admin)):
    messages = storage.load_user_messages(user["username"])
    target = next((m for m in messages if m.get("id") == message_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Message not found")
    patch = {k: v for k, v in req.model_dump().items() if v is not None}
    target.update(patch)
    updated = storage.upsert_message(target)
    if req.status == "sent":
        storage.patch_signal(target["signal_id"], {"status": "sent"}, username=user["username"])
    return updated


# ---------------------------------------------------------------------------
# Follow-up generation
# ---------------------------------------------------------------------------

@router.post("/followup")
def generate_followup(req: FollowupRequest, user: dict = Depends(_admin)):
    signal = storage.get_signal(req.signal_id, username=user["username"])
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    text = pipeline.compose_followup(user["username"], signal, req.reply_text)
    if not text:
        raise HTTPException(status_code=500, detail="Follow-up generation failed")
    return {"followup": text}


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

@router.get("/history")
def get_history(user: dict = Depends(_admin)):
    signals = storage.load_user_signals(user["username"])
    sent = [s for s in signals if s.get("status") == "sent"]
    return sent
