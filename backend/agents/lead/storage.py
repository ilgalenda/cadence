from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from agents.shared.vault import write_learning

AGENT_DIR = Path(__file__).parent
DATA_DIR = AGENT_DIR / "data"
KNOWLEDGE_DIR = AGENT_DIR / "knowledge"
DATA_DIR.mkdir(exist_ok=True)
KNOWLEDGE_DIR.mkdir(exist_ok=True)

CAMPAIGNS_FILE = DATA_DIR / "campaigns.json"
LEADS_FILE = DATA_DIR / "leads.json"
LEARNINGS_DIR = DATA_DIR / "learnings"
LEARNINGS_DIR.mkdir(exist_ok=True)
USER_KNOWLEDGE_DIR = KNOWLEDGE_DIR / "_user"
USER_KNOWLEDGE_DIR.mkdir(exist_ok=True)


def user_learnings_json(username: str) -> Path:
    return LEARNINGS_DIR / f"{username}.json"


def user_learnings_md(username: str) -> Path:
    d = USER_KNOWLEDGE_DIR / username
    d.mkdir(parents=True, exist_ok=True)
    return d / "learnings-auto.md"

CAMPAIGN_CAP = 200


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2))


def now_label() -> str:
    return datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M")


def new_campaign_id() -> str:
    return uuid.uuid4().hex


def load_campaigns() -> list[dict]:
    return _read_json(CAMPAIGNS_FILE, [])


def load_user_campaigns(username: str) -> list[dict]:
    return [c for c in load_campaigns() if c.get("username") == username]


def get_campaign(campaign_id: str, username: str | None = None) -> dict | None:
    for c in load_campaigns():
        if c.get("id") != campaign_id:
            continue
        if username is not None and c.get("username") != username:
            return None
        return c
    return None


def upsert_campaign(campaign: dict, username: str | None = None) -> dict:
    """Insert or update by id. Newest first. Caps the list."""
    if not campaign.get("id"):
        campaign["id"] = new_campaign_id()
    if not campaign.get("created_at"):
        campaign["created_at"] = now_label()
    campaign["updated_at"] = now_label()
    if username is not None:
        campaign["username"] = username

    campaigns = load_campaigns()
    campaigns = [c for c in campaigns if c.get("id") != campaign["id"]]
    campaigns.insert(0, campaign)
    campaigns = campaigns[:CAMPAIGN_CAP]
    _write_json(CAMPAIGNS_FILE, campaigns)
    return campaign


def patch_campaign(campaign_id: str, patch: dict, username: str | None = None) -> dict | None:
    existing = get_campaign(campaign_id, username=username)
    if not existing:
        return None
    existing.update(patch)
    return upsert_campaign(existing)


def delete_campaign(campaign_id: str, username: str | None = None) -> bool:
    campaigns = load_campaigns()
    new_list = [
        c for c in campaigns
        if not (c.get("id") == campaign_id and (username is None or c.get("username") == username))
    ]
    if len(new_list) == len(campaigns):
        return False
    _write_json(CAMPAIGNS_FILE, new_list)
    return True


def load_leads() -> list[dict]:
    return _read_json(LEADS_FILE, [])


def load_user_leads(username: str) -> list[dict]:
    return [l for l in load_leads() if l.get("username") == username]


def save_lead(lead: dict, username: str | None = None) -> None:
    leads = load_leads()
    record = {**lead, "id": lead.get("id") or uuid.uuid4().hex, "saved_at": now_label()}
    if username is not None:
        record["username"] = username
    leads.insert(0, record)
    _write_json(LEADS_FILE, leads[:500])


def load_learnings(username: str) -> list[dict]:
    return _read_json(user_learnings_json(username), [])


def save_learnings_from_campaign(campaign_id: str, campaign_title: str, extracts: list[dict], username: str) -> None:
    """Persist campaign learnings to JSON, markdown, and shared vault."""
    if not extracts:
        return
    try:
        learnings = load_learnings(username)
        created_at = datetime.now(timezone.utc).isoformat()
        date_label = datetime.now(timezone.utc).strftime("%d %b %Y")
        new_rows = []
        md_blocks = []
        for item in extracts:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            content = str(item.get("content", "")).strip()
            category = str(item.get("category", "")).strip() or "outreach"
            if not title or not content:
                continue
            entry_id = uuid.uuid4().hex
            new_rows.append({
                "id": entry_id,
                "title": title,
                "content": content,
                "category": category,
                "source_campaign_id": campaign_id,
                "source_campaign_title": campaign_title,
                "created_at": created_at,
            })
            md_blocks.append(
                f"## {title} — {date_label} (from campaign: {campaign_title})\n"
                f"*Category: {category}*\n\n"
                f"{content}\n"
            )
            # Write to vault (shared across all users)
            write_learning(
                title=title,
                content=content,
                category=category,
                agent="lead",
                contributed_by=username,
                source_id=campaign_id,
                source_title=campaign_title,
            )
        if not new_rows:
            return
        learnings = new_rows + learnings
        _write_json(user_learnings_json(username), learnings)

        header = (
            "<!-- Auto-generated by the Lead Agent. Each campaign run appends a section below. -->\n"
            f"# Learnings from {username}'s outreach campaigns\n\n"
        )
        md_path = user_learnings_md(username)
        existing = ""
        if md_path.exists():
            existing = md_path.read_text(encoding="utf-8")
            if existing.startswith(header):
                existing = existing[len(header):]
        md_path.write_text(header + "\n".join(md_blocks) + "\n" + existing, encoding="utf-8")
    except Exception as e:
        print(f"[lead] failed to persist learnings: {e}")


def stats(username: str | None = None) -> dict:
    campaigns = load_user_campaigns(username) if username else load_campaigns()
    leads = load_user_leads(username) if username else load_leads()
    sequences = sum(1 for c in campaigns if c.get("email_sequence"))
    synced = sum(1 for c in campaigns if c.get("calendar_events"))
    return {
        "campaigns_total": len(campaigns),
        "sequences_generated": sequences,
        "calendar_synced": synced,
        "leads_analysed": len(leads),
    }