import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile

from auth import load_users, public_user, require_admin
from agents.shared import vault as vault_mod
from paths import calls_data, calls_user_kb, sales_data

CALLS_DATA = calls_data() / "sessions.json"

#: A **frozen archive.** The campaign builder that wrote this file was retired in
#: Stage 3.3, so nothing appends to it any more; what is here is history. It is
#: still read because those campaigns happened and the record of who worked what is
#: worth keeping visible. The counts it feeds will not grow — that is the file, not
#: a bug in the panel.
CAMPAIGNS  = sales_data() / "campaigns.json"

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _load(path: Path) -> list:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _parse_ts(ts: str) -> datetime:
    try:
        return datetime.strptime(ts, "%d %b %Y, %H:%M")
    except Exception:
        return datetime.min


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

@router.get("/overview")
def admin_overview():
    sessions   = _load(CALLS_DATA)
    campaigns  = _load(CAMPAIGNS)
    calls      = [s for s in sessions if s.get("type") == "call_analysis"]
    users      = load_users()

    today_str = datetime.now().strftime("%d %b %Y")
    active_usernames: set[str] = set()
    for s in sessions:
        if today_str in s.get("timestamp", ""):
            active_usernames.add(s.get("username", ""))
    for c in campaigns:
        ts = c.get("updated_at") or c.get("created_at", "")
        if today_str in ts:
            active_usernames.add(c.get("username", ""))

    calls_by_user     = dict(Counter(s.get("username", "") for s in calls))
    campaigns_by_user = dict(Counter(c.get("username", "") for c in campaigns))

    # Recent activity: merge calls + campaign creates, sort by timestamp desc
    activity = []
    for s in calls:
        result = s.get("result") or {}
        rec    = result.get("product_recommendation") or {}
        activity.append({
            "type":      "call_analysis",
            "username":  s.get("username", ""),
            "title":     s.get("title", "Untitled"),
            "timestamp": s.get("timestamp", ""),
            "meta":      rec.get("primary", ""),
        })
    for c in campaigns:
        activity.append({
            "type":      "campaign",
            "username":  c.get("username", ""),
            "title":     c.get("title", "Untitled"),
            "timestamp": c.get("updated_at") or c.get("created_at", ""),
            "meta":      c.get("status", ""),
        })

    activity.sort(key=lambda x: _parse_ts(x["timestamp"]), reverse=True)

    pending_added = vault_mod.list_added("pending")

    return {
        "total_users":         len(users),
        "total_calls":         len(calls),
        "total_campaigns":     len(campaigns),
        "active_today":        len(active_usernames),
        "calls_by_user":       calls_by_user,
        "campaigns_by_user":   campaigns_by_user,
        "recent_activity":     activity[:20],
        "pending_added_count": len(pending_added),
    }


# ---------------------------------------------------------------------------
# Added Knowledge — approval queue (Pillar 3)
# ---------------------------------------------------------------------------

@router.get("/added/pending")
def admin_added_pending():
    """List pending user-submitted corrections awaiting admin review."""
    return vault_mod.list_added("pending")


@router.get("/added/approved")
def admin_added_approved():
    return vault_mod.list_added("approved")


@router.get("/added/rejected")
def admin_added_rejected():
    return vault_mod.list_added("rejected")


@router.post("/added/{entry_id}/approve")
def admin_added_approve(
    entry_id: str,
    payload: dict = Body(default_factory=dict),
    admin=Depends(require_admin),
):
    notes = str(payload.get("notes", "")).strip()
    reviewer = admin.get("username") if isinstance(admin, dict) else "admin"
    try:
        path = vault_mod.approve_added(entry_id, reviewed_by=reviewer, review_notes=notes)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Pending entry not found")
    return {"ok": True, "approved_filename": path.name}


@router.post("/added/{entry_id}/reject")
def admin_added_reject(
    entry_id: str,
    payload: dict = Body(default_factory=dict),
    admin=Depends(require_admin),
):
    notes = str(payload.get("notes", "")).strip()
    reviewer = admin.get("username") if isinstance(admin, dict) else "admin"
    try:
        path = vault_mod.reject_added(entry_id, reviewed_by=reviewer, review_notes=notes)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Pending entry not found")
    return {"ok": True, "rejected_filename": path.name}


# ---------------------------------------------------------------------------
# Calls
# ---------------------------------------------------------------------------

@router.get("/calls")
def admin_calls():
    sessions = _load(CALLS_DATA)
    calls    = [s for s in sessions if s.get("type") == "call_analysis"]
    out = []
    for s in calls:
        result = s.get("result") or {}
        rec    = result.get("product_recommendation") or {}
        out.append({
            "id":              s.get("id", ""),
            "username":        s.get("username", ""),
            "title":           s.get("title", "Untitled"),
            "timestamp":       s.get("timestamp", ""),
            "summary":         result.get("summary", ""),
            "product_fit":     result.get("product_fit", []),
            "primary_product": rec.get("primary", ""),
        })
    return out


@router.get("/calls/{call_id}")
def admin_call_detail(call_id: str):
    sessions = _load(CALLS_DATA)
    for s in sessions:
        if s.get("id") == call_id and s.get("type") == "call_analysis":
            return s
    raise HTTPException(status_code=404, detail="Call not found")


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------

@router.get("/campaigns")
def admin_campaigns():
    campaigns = _load(CAMPAIGNS)
    out = []
    for c in campaigns:
        sig = c.get("signal_analysis") or {}
        out.append({
            "id":             c.get("id", ""),
            "username":       c.get("username", ""),
            "title":          c.get("title", "Untitled"),
            "status":         c.get("status", "draft"),
            "current_step":   c.get("current_step", 0),
            "created_at":     c.get("created_at", ""),
            "updated_at":     c.get("updated_at", ""),
            "company":        sig.get("company", ""),
            "signal_strength": sig.get("signal_strength", ""),
        })
    out.sort(key=lambda x: _parse_ts(x["updated_at"] or x["created_at"]), reverse=True)
    return out


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

@router.get("/users")
def admin_users():
    users     = load_users()
    sessions  = _load(CALLS_DATA)
    campaigns = _load(CAMPAIGNS)

    calls_count     = Counter(s.get("username", "") for s in sessions if s.get("type") == "call_analysis")
    campaigns_count = Counter(c.get("username", "") for c in campaigns)

    def last_active(username: str) -> str:
        timestamps = []
        for s in sessions:
            if s.get("username") == username and s.get("timestamp"):
                timestamps.append(_parse_ts(s["timestamp"]))
        for c in campaigns:
            if c.get("username") == username:
                ts_str = c.get("updated_at") or c.get("created_at", "")
                if ts_str:
                    timestamps.append(_parse_ts(ts_str))
        if not timestamps:
            return ""
        best = max(timestamps)
        return best.strftime("%d %b %Y, %H:%M") if best != datetime.min else ""

    out = []
    for u in users:
        base = public_user(u)
        base["call_count"]     = calls_count.get(u["username"], 0)
        base["campaign_count"] = campaigns_count.get(u["username"], 0)
        base["last_active"]    = last_active(u["username"])
        out.append(base)

    out.sort(key=lambda x: x.get("name", x.get("username", "")).lower())
    return out


# ---------------------------------------------------------------------------
# Knowledge files
#
# The static markdown Owl reads alongside the vault. Moved here from
# `agents/calls` in Stage 4: managing these files is administration, the whole
# router is already `require_admin`, and `/admin` was the only surface calling
# them. They were never a calls concern — they lived there because that is where
# the directory happened to sit.
# ---------------------------------------------------------------------------

#: Files that may never be deleted through the API. Two are hand-maintained sources
#: of truth; the third is regenerated from analysed calls and deleting it would
#: silently drop a user's own accumulated learnings.
PROTECTED_KNOWLEDGE_FILES = {
    "company-overview.md",
    "learnings-auto.md",
    "campaign-knowledge-base.md",
}

_KNOWLEDGE_SUFFIXES = {".md", ".txt"}


def _knowledge_dir() -> Path:
    return calls_user_kb().parent


def _file_row(path: Path, *, protected: bool, auto_generated: bool) -> dict:
    stat = path.stat()
    return {
        "name": path.name,
        "size_kb": round(stat.st_size / 1024, 1),
        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%d %b %Y"),
        "protected": protected,
        "auto_generated": auto_generated,
    }


@router.get("/knowledge")
def list_knowledge(admin: dict = Depends(require_admin)):
    """The shared knowledge files, plus this admin's own generated learnings."""
    directory = _knowledge_dir()
    files = [
        _file_row(path, protected=path.name in PROTECTED_KNOWLEDGE_FILES, auto_generated=False)
        for path in sorted(directory.iterdir())
        if path.is_file() and path.suffix.lower() in _KNOWLEDGE_SUFFIXES
    ] if directory.exists() else []

    own = calls_user_kb() / admin["username"] / "learnings-auto.md"
    if own.is_file():
        files.append(_file_row(own, protected=True, auto_generated=True))
    return files


@router.post("/knowledge/upload")
async def upload_knowledge(file: UploadFile = File(...)):
    """Add a knowledge file. Markdown and plain text only — Owl reads it as prose."""
    name = Path(file.filename or "").name
    if not name or not name.lower().endswith(tuple(_KNOWLEDGE_SUFFIXES)):
        raise HTTPException(status_code=400, detail="Only .md and .txt files are supported.")

    directory = _knowledge_dir()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_bytes(await file.read())
    return {"message": f"Uploaded {name}", "name": name}


@router.delete("/knowledge/{filename}")
def delete_knowledge(filename: str):
    name = Path(filename).name
    if name in PROTECTED_KNOWLEDGE_FILES:
        raise HTTPException(status_code=403, detail="That knowledge file is protected.")

    path = _knowledge_dir() / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    path.unlink()
    return {"ok": True}
