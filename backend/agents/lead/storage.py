from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from agents.shared.vault import write_learning
from paths import lead_data, lead_user_kb

DATA_DIR = lead_data()
DATA_DIR.mkdir(parents=True, exist_ok=True)

CAMPAIGNS_FILE = DATA_DIR / "campaigns.json"
LEADS_FILE = DATA_DIR / "leads.json"
PROSPECTS_FILE = DATA_DIR / "prospects.json"
LEARNINGS_DIR = DATA_DIR / "learnings"
LEARNINGS_DIR.mkdir(exist_ok=True)
USER_KNOWLEDGE_DIR = lead_user_kb()
USER_KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
# KNOWLEDGE_DIR retained for the per-user knowledge tree only — the static
# in-repo knowledge base is read via the vault, not from this path.
KNOWLEDGE_DIR = USER_KNOWLEDGE_DIR.parent


def _campaigns_file(sandbox: bool) -> Path:
    if sandbox:
        p = DATA_DIR / "_sandbox"
        p.mkdir(exist_ok=True)
        return p / "campaigns.json"
    return CAMPAIGNS_FILE


def _leads_file(sandbox: bool) -> Path:
    if sandbox:
        p = DATA_DIR / "_sandbox"
        p.mkdir(exist_ok=True)
        return p / "leads.json"
    return LEADS_FILE


def _prospects_file(sandbox: bool) -> Path:
    if sandbox:
        p = DATA_DIR / "_sandbox"
        p.mkdir(exist_ok=True)
        return p / "prospects.json"
    return PROSPECTS_FILE


def user_learnings_json(username: str, sandbox: bool = False) -> Path:
    base = DATA_DIR / "_sandbox" / "learnings" if sandbox else LEARNINGS_DIR
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{username}.json"


def user_learnings_md(username: str, sandbox: bool = False) -> Path:
    base = KNOWLEDGE_DIR / "_sandbox" if sandbox else USER_KNOWLEDGE_DIR
    d = base / username
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


def load_campaigns(sandbox: bool = False) -> list[dict]:
    return _read_json(_campaigns_file(sandbox), [])


def load_user_campaigns(username: str, sandbox: bool = False) -> list[dict]:
    return [c for c in load_campaigns(sandbox) if c.get("username") == username]


def get_campaign(campaign_id: str, username: str | None = None, sandbox: bool = False) -> dict | None:
    for c in load_campaigns(sandbox):
        if c.get("id") != campaign_id:
            continue
        if username is not None and c.get("username") != username:
            return None
        return c
    return None


def upsert_campaign(campaign: dict, username: str | None = None, sandbox: bool = False) -> dict:
    """Insert or update by id. Newest first. Caps the list."""
    if not campaign.get("id"):
        campaign["id"] = new_campaign_id()
    if not campaign.get("created_at"):
        campaign["created_at"] = now_label()
    campaign["updated_at"] = now_label()
    if username is not None:
        campaign["username"] = username

    campaigns = load_campaigns(sandbox)
    campaigns = [c for c in campaigns if c.get("id") != campaign["id"]]
    campaigns.insert(0, campaign)
    campaigns = campaigns[:CAMPAIGN_CAP]
    _write_json(_campaigns_file(sandbox), campaigns)
    return campaign


def patch_campaign(campaign_id: str, patch: dict, username: str | None = None, sandbox: bool = False) -> dict | None:
    existing = get_campaign(campaign_id, username=username, sandbox=sandbox)
    if not existing:
        return None
    existing.update(patch)
    return upsert_campaign(existing, sandbox=sandbox)


def delete_campaign(campaign_id: str, username: str | None = None, sandbox: bool = False) -> bool:
    campaigns = load_campaigns(sandbox)
    new_list = [
        c for c in campaigns
        if not (c.get("id") == campaign_id and (username is None or c.get("username") == username))
    ]
    if len(new_list) == len(campaigns):
        return False
    _write_json(_campaigns_file(sandbox), new_list)
    return True


def load_leads(sandbox: bool = False) -> list[dict]:
    return _read_json(_leads_file(sandbox), [])


def load_user_leads(username: str, sandbox: bool = False) -> list[dict]:
    return [l for l in load_leads(sandbox) if l.get("username") == username]


def save_lead(lead: dict, username: str | None = None, sandbox: bool = False) -> None:
    leads = load_leads(sandbox)
    record = {**lead, "id": lead.get("id") or uuid.uuid4().hex, "saved_at": now_label()}
    if username is not None:
        record["username"] = username
    leads.insert(0, record)
    _write_json(_leads_file(sandbox), leads[:500])


# ---------------------------------------------------------------------------
# Prospect lists — output of standalone X-Ray prospecting, reusable by campaigns
# ---------------------------------------------------------------------------

PROSPECT_CAP = 200


def new_prospect_id() -> str:
    return uuid.uuid4().hex


def load_prospect_lists(sandbox: bool = False) -> list[dict]:
    return _read_json(_prospects_file(sandbox), [])


def load_user_prospect_lists(username: str, sandbox: bool = False) -> list[dict]:
    return [p for p in load_prospect_lists(sandbox) if p.get("username") == username]


def get_prospect_list(prospect_id: str, username: str | None = None, sandbox: bool = False) -> dict | None:
    for p in load_prospect_lists(sandbox):
        if p.get("id") != prospect_id:
            continue
        if username is not None and p.get("username") != username:
            return None
        return p
    return None


def save_prospect_list(record: dict, username: str | None = None, sandbox: bool = False) -> dict:
    """Insert or update a prospect list by id. Newest first, capped."""
    if not record.get("id"):
        record["id"] = new_prospect_id()
    if not record.get("created_at"):
        record["created_at"] = now_label()
    record["updated_at"] = now_label()
    if username is not None:
        record["username"] = username

    lists = load_prospect_lists(sandbox)
    lists = [p for p in lists if p.get("id") != record["id"]]
    lists.insert(0, record)
    lists = lists[:PROSPECT_CAP]
    _write_json(_prospects_file(sandbox), lists)
    return record


def delete_prospect_list(prospect_id: str, username: str | None = None, sandbox: bool = False) -> bool:
    lists = load_prospect_lists(sandbox)
    new_list = [
        p for p in lists
        if not (p.get("id") == prospect_id and (username is None or p.get("username") == username))
    ]
    if len(new_list) == len(lists):
        return False
    _write_json(_prospects_file(sandbox), new_list)
    return True


def load_learnings(username: str, sandbox: bool = False) -> list[dict]:
    return _read_json(user_learnings_json(username, sandbox), [])


def save_learnings_from_campaign(campaign_id: str, campaign_title: str, extracts: list[dict], username: str, sandbox: bool = False) -> None:
    """Persist campaign learnings to JSON, markdown, and shared vault."""
    if not extracts:
        return
    try:
        learnings = load_learnings(username, sandbox)
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
            description = str(item.get("description", "")).strip()
            if not title or not content:
                continue
            if not description:
                first = content.split(".")[0].strip()
                description = (first[:200] + ("…" if len(first) > 200 else "")) or title
            entry_id = uuid.uuid4().hex
            new_rows.append({
                "id": entry_id,
                "title": title,
                "description": description,
                "content": content,
                "category": category,
                "source_campaign_id": campaign_id,
                "source_campaign_title": campaign_title,
                "created_at": created_at,
            })
            md_blocks.append(
                f"## {title} — {date_label} (from campaign: {campaign_title})\n"
                f"*{description}*\n"
                f"*Category: {category}*\n\n"
                f"{content}\n"
            )
            if not sandbox:
                # Write to shared vault only in live mode
                write_learning(
                    title=title,
                    description=description,
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
        _write_json(user_learnings_json(username, sandbox), learnings)

        header = (
            "<!-- Auto-generated by the Lead Agent. Each campaign run appends a section below. -->\n"
            f"# Learnings from {username}'s outreach campaigns\n\n"
        )
        md_path = user_learnings_md(username, sandbox)
        existing = ""
        if md_path.exists():
            existing = md_path.read_text(encoding="utf-8")
            if existing.startswith(header):
                existing = existing[len(header):]
        md_path.write_text(header + "\n".join(md_blocks) + "\n" + existing, encoding="utf-8")
    except Exception as e:
        print(f"[lead] failed to persist learnings: {e}")


def stats(username: str | None = None, sandbox: bool = False) -> dict:
    campaigns = load_user_campaigns(username, sandbox) if username else load_campaigns(sandbox)
    leads = load_user_leads(username, sandbox) if username else load_leads(sandbox)
    sequences = sum(1 for c in campaigns if c.get("email_sequence"))
    synced = sum(1 for c in campaigns if c.get("calendar_events"))
    return {
        "campaigns_total": len(campaigns),
        "sequences_generated": sequences,
        "calendar_synced": synced,
        "leads_analysed": len(leads),
    }