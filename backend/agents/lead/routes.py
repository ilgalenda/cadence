from __future__ import annotations
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from agents.lead import google_calendar as gc
from agents.lead import pipeline, storage
from agents.lead.owl import OwlRefiner
from auth import require_admin, require_agent_access

_lead_user = require_agent_access("lead")
_lead_admin = require_admin

router = APIRouter(prefix="/api/lead", tags=["lead"], dependencies=[Depends(_lead_user)])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    text: Optional[str] = None
    structured: Optional[dict] = None
    image_b64: Optional[str] = None
    image_media_type: Optional[str] = None


class CampaignCreate(BaseModel):
    id: Optional[str] = None
    title: Optional[str] = None
    lead_input: Optional[dict] = None
    signal_analysis: Optional[dict] = None
    campaign_type: Optional[str] = None  # "email" | "linkedin" | "abm"
    email_config: Optional[dict] = None
    linkedin_config: Optional[dict] = None
    abm_config: Optional[dict] = None
    abm_identification: Optional[dict] = None
    abm_matrix: Optional[dict] = None
    email_sequence: Optional[list[dict]] = None
    boolean_search: Optional[dict] = None
    current_step: Optional[int] = None
    status: Optional[str] = None
    source: Optional[str] = None  # e.g. "calls-handoff"


class CampaignPatch(BaseModel):
    title: Optional[str] = None
    lead_input: Optional[dict] = None
    signal_analysis: Optional[dict] = None
    campaign_type: Optional[str] = None
    email_config: Optional[dict] = None
    linkedin_config: Optional[dict] = None
    abm_config: Optional[dict] = None
    abm_identification: Optional[dict] = None
    abm_matrix: Optional[dict] = None
    email_sequence: Optional[list[dict]] = None
    boolean_search: Optional[dict] = None
    current_step: Optional[int] = None
    status: Optional[str] = None


class SequenceRequest(BaseModel):
    config: dict
    # Each recipient: { name, role, linkedin_url? }. id is assigned server-side.
    recipients: Optional[list[dict]] = None


class BooleanRequest(BaseModel):
    config: dict


class AbmIdentifyRequest(BaseModel):
    config: dict


class AbmSequenceRequest(BaseModel):
    config: dict
    contacts: Optional[list[dict]] = None  # [{ id?, name, role, linkedin_url?, email? }]


class TouchRegenRequest(BaseModel):
    recipient_id: Optional[str] = None


class OwlFillRequest(BaseModel):
    field: str
    instruction: Optional[str] = ""
    current_state: Optional[dict] = None


class CalendarSyncRequest(BaseModel):
    touch: int
    recipient_id: Optional[str] = None
    timezone: Optional[str] = None  # IANA tz name from browser, e.g. "Europe/London"


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@router.get("/stats")
def get_stats(user: dict = Depends(_lead_user)):
    return storage.stats(user["username"])


# ---------------------------------------------------------------------------
# Step 1 — signal analysis
# ---------------------------------------------------------------------------

@router.post("/analyze")
def analyze(req: AnalyzeRequest, user: dict = Depends(_lead_user)):
    if not (req.text or req.structured or req.image_b64):
        raise HTTPException(status_code=400, detail="Provide text, structured fields, or an image.")
    try:
        result = pipeline.generate_signal(
            user["username"],
            text=req.text,
            structured=req.structured,
            image_b64=req.image_b64,
            image_media_type=req.image_media_type,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Signal analysis failed: {e}")

    final = result["final"]
    title = (final.get("contact_name") or "Lead") + (
        f" — {final['company']}" if final.get("company") else ""
    )

    campaign = storage.upsert_campaign({
        "id": storage.new_campaign_id(),
        "title": title,
        "current_step": 1,
        "status": "draft",
        "lead_input": {
            "text": req.text,
            "structured": req.structured,
            "has_image": bool(req.image_b64),
        },
        "signal_analysis": final,
    }, username=user["username"])
    storage.save_lead({"campaign_id": campaign["id"], "analysis": final}, username=user["username"])
    return {
        "campaign_id": campaign["id"],
        "campaign": campaign,
        "final": final,
        "claude_raw": result["claude_raw"],
        "owl_applied": result["owl_applied"],
    }


# ---------------------------------------------------------------------------
# Campaign CRUD
# ---------------------------------------------------------------------------

@router.get("/campaigns")
def list_campaigns(user: dict = Depends(_lead_user)):
    return [
        {k: v for k, v in c.items() if k not in ("lead_input",)}
        for c in storage.load_user_campaigns(user["username"])
    ]


@router.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: str, user: dict = Depends(_lead_user)):
    c = storage.get_campaign(campaign_id, username=user["username"])
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    return c


@router.post("/campaigns")
def create_campaign(req: CampaignCreate, user: dict = Depends(_lead_user)):
    payload = req.model_dump(exclude_none=True)
    payload.setdefault("id", storage.new_campaign_id())
    payload.setdefault("status", "draft")
    payload.setdefault("current_step", 0)
    if not payload.get("title"):
        payload["title"] = (
            (payload.get("signal_analysis") or {}).get("contact_name")
            or (payload.get("lead_input") or {}).get("text", "")[:60]
            or "Untitled campaign"
        )
    return storage.upsert_campaign(payload, username=user["username"])


@router.patch("/campaigns/{campaign_id}")
def update_campaign(campaign_id: str, req: CampaignPatch, user: dict = Depends(_lead_user)):
    patch = req.model_dump(exclude_none=True)
    updated = storage.patch_campaign(campaign_id, patch, username=user["username"])
    if not updated:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    return updated


@router.delete("/campaigns/{campaign_id}")
def remove_campaign(campaign_id: str, user: dict = Depends(_lead_user)):
    if not storage.delete_campaign(campaign_id, username=user["username"]):
        raise HTTPException(status_code=404, detail="Campaign not found.")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Step 1.5 — X-Ray sub-agent (web_search-backed prospect discovery)
# ---------------------------------------------------------------------------

class XRayContactsFromXrayRequest(BaseModel):
    selected: list[dict]  # [{full_name, job_title, linkedin_url, recommended_path?, ...}]
    target: Optional[str] = "recipients"  # "recipients" (email/linkedin) | "contacts" (ABM)


@router.post("/campaigns/{campaign_id}/xray")
def run_xray(campaign_id: str, user: dict = Depends(_lead_user)):
    campaign = storage.get_campaign(campaign_id, username=user["username"])
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    signal_final = campaign.get("signal_analysis") or {}
    structured = (campaign.get("lead_input") or {}).get("structured") or {}
    result = pipeline.generate_xray(user["username"], signal_final, structured)

    storage.patch_campaign(campaign_id, {
        "xray_results": result["grouped"],
        "xray_error": result.get("error"),
    }, username=user["username"])

    return {
        "campaign_id": campaign_id,
        "xray_results": result["grouped"],
        "results_flat": result["results"],
        "error": result.get("error"),
    }


@router.post("/campaigns/{campaign_id}/contacts/from-xray")
def contacts_from_xray(campaign_id: str, req: XRayContactsFromXrayRequest, user: dict = Depends(_lead_user)):
    campaign = storage.get_campaign(campaign_id, username=user["username"])
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    converted = []
    for row in req.selected or []:
        name = (row.get("full_name") or row.get("name") or "").strip()
        if not name:
            continue
        converted.append({
            "id": uuid.uuid4().hex[:12],
            "name": name,
            "role": (row.get("job_title") or row.get("role") or "").strip(),
            "linkedin_url": (row.get("linkedin_url") or "").strip(),
            "email": (row.get("email") or "").strip(),
        })

    if not converted:
        raise HTTPException(status_code=400, detail="No valid contacts in selection.")

    target = (req.target or "recipients").lower()
    patch: dict = {}
    if target == "contacts":
        patch["contacts"] = converted
    else:
        patch["recipients"] = converted
    # Auto-advance to step 2 (campaign type selection) so the user lands with contacts pre-loaded.
    if (campaign.get("current_step") or 0) < 2:
        patch["current_step"] = 2
    updated = storage.patch_campaign(campaign_id, patch, username=user["username"])
    return {"campaign": updated, "added": len(converted), "target": target}


# ---------------------------------------------------------------------------
# Step 4A — email sequence
# ---------------------------------------------------------------------------

def _ensure_recipients(req_recipients: Optional[list[dict]], analysis: dict) -> list[dict]:
    """Normalise recipients: assign ids; default to single recipient from analysis."""
    if not req_recipients:
        req_recipients = [{
            "name": analysis.get("contact_name", ""),
            "role": analysis.get("role", ""),
            "linkedin_url": "",
        }]
    out = []
    for r in req_recipients:
        out.append({
            "id": r.get("id") or uuid.uuid4().hex[:12],
            "name": (r.get("name") or "").strip(),
            "role": (r.get("role") or "").strip(),
            "linkedin_url": (r.get("linkedin_url") or "").strip(),
        })
    return out


@router.post("/campaigns/{campaign_id}/sequence")
def generate_sequence(campaign_id: str, req: SequenceRequest, user: dict = Depends(_lead_user)):
    campaign = storage.get_campaign(campaign_id, username=user["username"])
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    analysis = campaign.get("signal_analysis") or {}
    recipients = _ensure_recipients(req.recipients, analysis)
    try:
        result = pipeline.generate_sequences(user["username"], analysis, req.config, recipients)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Sequence generation failed: {e}")

    out_recipients = result["recipients"]
    storage.patch_campaign(campaign_id, {
        "email_config": req.config,
        "recipients": out_recipients,
        # Keep email_sequence pointing at the first recipient for backwards-compat readers.
        "email_sequence": (out_recipients[0]["sequence"] if out_recipients else []),
        "current_step": 4,
        "status": "ready",
    }, username=user["username"])
    total_touches = sum(len(r["sequence"]) for r in out_recipients)
    company = analysis.get("company") or "unknown company"
    signal_strength = analysis.get("signal_strength") or "unknown"
    signal_type = analysis.get("signal_type") or "general"
    role = analysis.get("role") or ""
    signal_reasoning = analysis.get("signal_strength_reasoning") or ""
    product_fit = analysis.get("product_fit") or ""
    campaign_reasoning = analysis.get("suggested_campaign_reasoning") or ""
    source = analysis.get("source") or ""

    content_parts = [
        f"**Company:** {company}",
        f"**Signal:** {signal_strength} — {signal_type}",
    ]
    if role:
        content_parts.append(f"**Contact role:** {role}")
    if signal_reasoning:
        content_parts.append(f"**Signal reasoning:** {signal_reasoning}")
    if product_fit:
        content_parts.append(f"**Product fit:** {product_fit}")
    if campaign_reasoning:
        content_parts.append(f"**Campaign approach:** {req.config.get('suggested_campaign_type', 'email')} — {campaign_reasoning}")
    if source:
        content_parts.append(f"**Lead source:** {source}")
    content_parts.append(
        f"**Sequence:** {len(out_recipients)} recipient(s), {total_touches} touches total, "
        f"tone={req.config.get('tone')}, focus={req.config.get('focus')}"
    )
    extracts = [
        {
            "title": f"{company} — {signal_strength} {signal_type} outreach",
            "content": "\n".join(content_parts),
            "category": "outreach",
        }
    ]
    storage.save_learnings_from_campaign(campaign_id, campaign.get("title", ""), extracts, user["username"])
    return {
        "recipients": out_recipients,
        "owl_applied": result["owl_applied"],
    }


@router.post("/campaigns/{campaign_id}/sequence/touch/{n}/regenerate")
def regenerate_touch(campaign_id: str, n: int, req: TouchRegenRequest = TouchRegenRequest(), user: dict = Depends(_lead_user)):
    campaign = storage.get_campaign(campaign_id, username=user["username"])
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    analysis = campaign.get("signal_analysis") or {}
    config = campaign.get("email_config") or {}
    recipients = campaign.get("recipients") or []

    # Resolve the recipient (default to first if not provided)
    target = None
    for r in recipients:
        if r.get("id") == req.recipient_id:
            target = r
            break
    if target is None and recipients:
        target = recipients[0]
    if target is None:
        raise HTTPException(status_code=400, detail="No recipients on this campaign.")

    sequence = target.get("sequence") or []
    try:
        result = pipeline.regenerate_touch(user["username"], analysis, config, sequence, n, recipient=target)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Regeneration failed: {e}")

    new_touch = result["final"]
    new_sequence = []
    replaced = False
    for t in sequence:
        if t.get("touch") == n:
            new_sequence.append(new_touch)
            replaced = True
        else:
            new_sequence.append(t)
    if not replaced:
        new_sequence.append(new_touch)

    target["sequence"] = new_sequence
    storage.patch_campaign(campaign_id, {
        "recipients": recipients,
        # Keep email_sequence in sync with the first recipient.
        "email_sequence": (recipients[0].get("sequence") if recipients else []),
    }, username=user["username"])
    return {
        "recipient_id": target["id"],
        "sequence": new_sequence,
        "owl_applied": result["owl_applied"],
    }


# ---------------------------------------------------------------------------
# Step 4B — LinkedIn boolean
# ---------------------------------------------------------------------------

@router.post("/campaigns/{campaign_id}/boolean")
def generate_boolean(campaign_id: str, req: BooleanRequest, user: dict = Depends(_lead_user)):
    campaign = storage.get_campaign(campaign_id, username=user["username"])
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    analysis = campaign.get("signal_analysis") or {}
    try:
        result = pipeline.generate_boolean(user["username"], analysis, req.config)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Boolean generation failed: {e}")

    storage.patch_campaign(campaign_id, {
        "linkedin_config": req.config,
        "boolean_search": result["final"],
        "campaign_type": "linkedin",
        "current_step": 4,
        "status": "ready",
    }, username=user["username"])
    return result


# ---------------------------------------------------------------------------
# Step 3.5C / 4C — ABM (Multi-Channel Account Push)
# ---------------------------------------------------------------------------

@router.post("/campaigns/{campaign_id}/abm/identify")
def abm_identify(campaign_id: str, req: AbmIdentifyRequest, user: dict = Depends(_lead_user)):
    campaign = storage.get_campaign(campaign_id, username=user["username"])
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    analysis = campaign.get("signal_analysis") or {}
    try:
        result = pipeline.generate_abm_identification(user["username"], analysis, req.config)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"ABM identification failed: {e}")

    storage.patch_campaign(campaign_id, {
        "abm_config": req.config,
        "abm_identification": result["final"],
        "campaign_type": "abm",
        "current_step": 3,
        "status": "draft",
    }, username=user["username"])
    return result


@router.post("/campaigns/{campaign_id}/abm/sequence")
def abm_sequence(campaign_id: str, req: AbmSequenceRequest, user: dict = Depends(_lead_user)):
    campaign = storage.get_campaign(campaign_id, username=user["username"])
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    analysis = campaign.get("signal_analysis") or {}

    # Normalise contacts: assign ids.
    contacts = []
    for c in (req.contacts or []):
        contacts.append({
            "id": c.get("id") or uuid.uuid4().hex[:12],
            "name": (c.get("name") or "").strip(),
            "role": (c.get("role") or "").strip(),
            "linkedin_url": (c.get("linkedin_url") or "").strip(),
            "email": (c.get("email") or "").strip(),
        })

    try:
        result = pipeline.generate_abm_sequence(user["username"], analysis, req.config, contacts)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"ABM sequence generation failed: {e}")

    storage.patch_campaign(campaign_id, {
        "abm_config": {**req.config, "contacts": contacts},
        "abm_matrix": result["final"],
        "campaign_type": "abm",
        "current_step": 4,
        "status": "ready",
    }, username=user["username"])
    return {**result, "contacts": contacts}


# ---------------------------------------------------------------------------
# Inline Owl
# ---------------------------------------------------------------------------

@router.post("/owl/fill")
def owl_fill(req: OwlFillRequest, user: dict = Depends(_lead_user)):
    try:
        value = OwlRefiner(user["username"]).fill(req.field, req.current_state or {}, req.instruction or "")
        return {"value": value}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Owl fill failed: {e}")


# ---------------------------------------------------------------------------
# Google Calendar OAuth
# ---------------------------------------------------------------------------

@router.get("/google/status")
def google_status(request: Request, user: dict = Depends(_lead_user)):
    creds = gc.get_creds(user["username"])
    request_host = (request.url.hostname or "").lower()
    redirect_host = gc.redirect_host()
    available = bool(redirect_host) and (request_host == redirect_host)
    return {
        "configured": gc.is_configured(),
        "available": available,
        "connected": bool(creds),
        "email": (creds or {}).get("email", ""),
    }


@router.get("/google/connect")
def google_connect(request: Request, user: dict = Depends(_lead_user)):
    if not gc.is_configured():
        raise HTTPException(status_code=500, detail="Google OAuth not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.")
    state = secrets.token_urlsafe(24)
    request.session["google_oauth_state"] = state
    request.session["google_oauth_user"] = user["username"]
    return RedirectResponse(gc.build_authorize_url(state))


@router.get("/google/callback")
async def google_callback(request: Request, code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    if error:
        return RedirectResponse(f"/agents/lead/oauth/callback?error={error}")
    saved_state = request.session.pop("google_oauth_state", None)
    saved_user = request.session.pop("google_oauth_user", None)
    if not code or not state or state != saved_state or not saved_user:
        return RedirectResponse("/agents/lead/oauth/callback?error=invalid_state")
    if request.session.get("user") != saved_user:
        return RedirectResponse("/agents/lead/oauth/callback?error=user_mismatch")
    try:
        creds = await gc.exchange_code(code)
        gc.set_creds(saved_user, creds)
    except Exception as e:
        return RedirectResponse(f"/agents/lead/oauth/callback?error={str(e)[:120]}")
    return RedirectResponse("/agents/lead/oauth/callback?ok=1")


@router.post("/google/disconnect")
def google_disconnect(user: dict = Depends(_lead_user)):
    gc.clear_creds(user["username"])
    return {"ok": True}


# ---------------------------------------------------------------------------
# Calendar sync (per-touch, called sequentially from the frontend)
# ---------------------------------------------------------------------------

def _send_time_to_dt(start_date: str, day_offset_str: str, send_time: str) -> tuple[str, str]:
    """Translate "Day 4" + "Tuesday 9am" into ISO start/end (15-min event).

    Pragmatic approach: parse 'Day N' for offset, ignore the suggested weekday,
    parse 'Xam'/'Ypm' for hour. Falls back to 9am if unparseable.
    """
    try:
        offset = int("".join(ch for ch in (day_offset_str or "Day 1") if ch.isdigit()) or 1) - 1
    except ValueError:
        offset = 0
    base = datetime.fromisoformat(start_date)
    when = base + timedelta(days=max(offset, 0))

    hour = 9
    minute = 0
    s = (send_time or "").lower()
    try:
        digits = "".join(ch for ch in s.split()[-1] if ch.isdigit())
        if digits:
            hour = int(digits)
            if "pm" in s and hour < 12:
                hour += 12
            if "am" in s and hour == 12:
                hour = 0
    except Exception:
        pass

    start = when.replace(hour=hour, minute=minute, second=0, microsecond=0)
    end = start + timedelta(minutes=15)
    return start.isoformat(), end.isoformat()


@router.post("/campaigns/{campaign_id}/calendar/sync")
async def sync_event(campaign_id: str, req: CalendarSyncRequest, user: dict = Depends(_lead_user)):
    campaign = storage.get_campaign(campaign_id, username=user["username"])
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    if not gc.get_creds(user["username"]):
        raise HTTPException(status_code=409, detail="calendar_not_connected")

    recipients = campaign.get("recipients") or []
    target = None
    for r in recipients:
        if r.get("id") == req.recipient_id:
            target = r
            break
    if target is None and recipients:
        target = recipients[0]

    sequence = (target or {}).get("sequence") or campaign.get("email_sequence") or []
    touch = next((t for t in sequence if int(t.get("touch", 0)) == req.touch), None)
    if not touch:
        raise HTTPException(status_code=404, detail=f"Touch {req.touch} not found.")

    config = campaign.get("email_config") or {}
    start_date = config.get("start_date") or datetime.now(timezone.utc).date().isoformat()
    start_iso, end_iso = _send_time_to_dt(start_date, touch.get("suggested_day", "Day 1"), touch.get("send_time", "9am"))

    analysis = campaign.get("signal_analysis") or {}
    recipient_name = (target or {}).get("name") or analysis.get("contact_name", "Lead")
    recipient_role = (target or {}).get("role") or analysis.get("role", "")
    title = f"Timebeat outreach — {recipient_name} — Touch {req.touch}"
    description = (
        f"Subject: {touch.get('subject','')}\n"
        "---\n"
        f"{touch.get('body','')}\n"
        "---\n"
        f"Angle: {touch.get('angle','')}\n"
        f"Company: {analysis.get('company','')}\n"
        f"Role: {recipient_role}\n"
    )

    try:
        event = await gc.create_event(
            user["username"],
            summary=title,
            description=description,
            start_iso=start_iso,
            end_iso=end_iso,
            touch=req.touch,
            timezone=req.timezone or "UTC",
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Calendar sync failed: {e}")

    rid = (target or {}).get("id")
    events = campaign.get("calendar_events") or []
    events = [
        e for e in events
        if not (e.get("touch") == req.touch and e.get("recipient_id") == rid)
    ]
    events.append({**event, "touch": req.touch, "recipient_id": rid, "status": "synced"})
    storage.patch_campaign(campaign_id, {"calendar_events": events, "status": "synced"}, username=user["username"])
    return {**event, "touch": req.touch, "recipient_id": rid}