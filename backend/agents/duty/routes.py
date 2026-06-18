from __future__ import annotations
"""Duty & Tax agent — autonomous shipment duty/tax estimation.

Two ways in:
  * POST /api/duty/quote   — structured input → deterministic landed-cost breakdown.
  * POST /api/duty/assist  — natural-language shipment → the agent classifies the
                             HS code, looks up rates, and computes the breakdown
                             via tool-use, streaming its reasoning (SSE).
The maths and the rates are always deterministic local functions; the model only
orchestrates and explains.
"""
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents.duty import calc, storage
from agents.duty.prompts import DUTY_SYSTEM
from agents.duty.rates import get_provider
from agents.shared import anthropic_client
from auth import is_sandbox, require_agent_access

_user = require_agent_access("duty")
router = APIRouter(prefix="/api/duty", tags=["duty"], dependencies=[Depends(_user)])


# ---------------------------------------------------------------------------
# Structured (deterministic) quote
# ---------------------------------------------------------------------------

class QuoteRequest(BaseModel):
    destination: str
    goods_value: float
    hs_code: str
    freight: float = 0.0
    insurance: float = 0.0
    other_fees: float = 0.0
    currency: str = "USD"
    origin: str = ""
    goods_description: str = ""


@router.post("/quote")
def create_quote(req: QuoteRequest, request: Request, user: dict = Depends(_user)):
    if not req.destination.strip() or not req.hs_code.strip():
        raise HTTPException(status_code=400, detail="destination and hs_code are required (use /assist for free-text).")
    rate = get_provider().lookup(destination=req.destination, hs_code=req.hs_code)
    try:
        breakdown = calc.compute_landed_cost(
            goods_value=req.goods_value,
            freight=req.freight,
            insurance=req.insurance,
            other_fees=req.other_fees,
            duty_rate=rate["duty_rate"],
            vat_rate=rate["vat_rate"],
            valuation_basis=rate["valuation_basis"],
            currency=req.currency,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    record = {
        "type": "quote",
        "mode": "structured",
        "destination": req.destination,
        "origin": req.origin,
        "hs_code": req.hs_code,
        "goods_description": req.goods_description,
        "rate": dict(rate),
        "breakdown": breakdown,
    }
    saved = storage.quotes.upsert(record, username=user["username"], sandbox=is_sandbox(request))
    return {"id": saved["id"], "rate": dict(rate), "breakdown": breakdown}


@router.get("/quotes")
def list_quotes(request: Request, user: dict = Depends(_user)):
    return storage.quotes.load_user(user["username"], sandbox=is_sandbox(request))


@router.get("/stats")
def stats(request: Request, user: dict = Depends(_user)):
    items = storage.quotes.load_user(user["username"], sandbox=is_sandbox(request))
    return {"quotes_total": len(items)}


# ---------------------------------------------------------------------------
# Autonomous (tool-use) assist — streaming
# ---------------------------------------------------------------------------

LOOKUP_TOOL = {
    "name": "lookup_duty_rate",
    "description": "Look up the duty rate, VAT/GST rate, and customs valuation basis for a destination country and HS code. Always use this to get rates — never invent them.",
    "input_schema": {
        "type": "object",
        "properties": {
            "destination": {"type": "string", "description": "Destination country ISO-2 code, e.g. GB, DE, US."},
            "hs_code": {"type": "string", "description": "HS code (at least the 2-digit chapter), e.g. 8517 or 85."},
        },
        "required": ["destination", "hs_code"],
    },
}

COMPUTE_TOOL = {
    "name": "compute_landed_cost",
    "description": "Compute the itemised landed cost (duty, VAT/GST, totals) from values and rates. Always use this for the maths.",
    "input_schema": {
        "type": "object",
        "properties": {
            "goods_value": {"type": "number"},
            "freight": {"type": "number"},
            "insurance": {"type": "number"},
            "other_fees": {"type": "number"},
            "duty_rate": {"type": "number", "description": "Fraction, e.g. 0.05 for 5%."},
            "vat_rate": {"type": "number", "description": "Fraction, e.g. 0.20 for 20%."},
            "valuation_basis": {"type": "string", "enum": ["CIF", "FOB"]},
            "currency": {"type": "string"},
        },
        "required": ["goods_value", "duty_rate", "vat_rate"],
    },
}

DUTY_TOOLS = [LOOKUP_TOOL, COMPUTE_TOOL]


def _run_tool(name: str, tool_input: dict) -> tuple[str, dict | None]:
    """Execute a tool call. Returns (content_for_model, breakdown_if_any)."""
    try:
        if name == "lookup_duty_rate":
            rate = get_provider().lookup(
                destination=str(tool_input.get("destination", "")),
                hs_code=str(tool_input.get("hs_code", "")),
            )
            return json.dumps(dict(rate)), None
        if name == "compute_landed_cost":
            breakdown = calc.compute_landed_cost(
                goods_value=float(tool_input.get("goods_value", 0) or 0),
                freight=float(tool_input.get("freight", 0) or 0),
                insurance=float(tool_input.get("insurance", 0) or 0),
                other_fees=float(tool_input.get("other_fees", 0) or 0),
                duty_rate=float(tool_input["duty_rate"]),
                vat_rate=float(tool_input["vat_rate"]),
                valuation_basis=tool_input.get("valuation_basis", "CIF"),
                currency=tool_input.get("currency", "USD"),
            )
            return json.dumps(breakdown), breakdown
    except (ValueError, KeyError, TypeError) as e:
        return json.dumps({"error": str(e)}), None
    return json.dumps({"error": f"unknown tool {name}"}), None


class AssistRequest(BaseModel):
    messages: list[dict]


@router.post("/assist")
def assist(req: AssistRequest, request: Request, user: dict = Depends(_user)):
    username = user["username"]
    sandbox = is_sandbox(request)
    last_user_msg = ""
    for m in reversed(req.messages):
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            last_user_msg = m["content"]
            break

    def generate():
        client = anthropic_client.get_client()
        convo = list(req.messages)
        full: list[str] = []
        last_breakdown: dict | None = None
        try:
            for _ in range(6):  # bound the tool-use loop
                with anthropic_client.slot():
                    with client.messages.stream(
                        model=anthropic_client.SONNET,
                        max_tokens=1500,
                        system=DUTY_SYSTEM,
                        messages=convo,
                        tools=DUTY_TOOLS,
                    ) as stream:
                        for text in stream.text_stream:
                            full.append(text)
                            yield f"data: {json.dumps({'text': text})}\n\n"
                        final = stream.get_final_message()
                if final.stop_reason != "tool_use":
                    break
                tool_results = []
                for blk in final.content:
                    if getattr(blk, "type", None) == "tool_use":
                        content, breakdown = _run_tool(blk.name, blk.input if isinstance(blk.input, dict) else {})
                        if breakdown is not None:
                            last_breakdown = breakdown
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": blk.id,
                            "content": content,
                        })
                convo.append({"role": "assistant", "content": final.content})
                convo.append({"role": "user", "content": tool_results})
        except Exception as e:  # surface, don't crash the stream
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            return

        yield "data: [DONE]\n\n"

        answer = "".join(full).strip()
        if answer:
            storage.quotes.upsert(
                {"type": "quote", "mode": "assist", "request": last_user_msg,
                 "answer": answer, "breakdown": last_breakdown},
                username=username, sandbox=sandbox,
            )

    return StreamingResponse(generate(), media_type="text/event-stream")
