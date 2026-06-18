from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from paths import high_intent_data

DATA_DIR = high_intent_data() / "_sandbox"  # always sandbox — never touches production
DATA_DIR.mkdir(parents=True, exist_ok=True)

SIGNALS_FILE = DATA_DIR / "signals.json"
MESSAGES_FILE = DATA_DIR / "messages.json"
ICP_CONFIGS_FILE = DATA_DIR / "icp_configs.json"

SIGNAL_CAP = 500

SIGNAL_TYPES = [
    "competitor_engagement",
    "influencer_engagement",
    "job_change",
    "funding",
    "top_icp",
    "company_engagement",
]

SIGNAL_TYPE_LABELS = {
    "competitor_engagement": "Competitor Engagement",
    "influencer_engagement": "Influencer Engagement",
    "job_change": "Recently Changed Roles",
    "funding": "Recently Funded",
    "top_icp": "Top 5% ICP Activity",
    "company_engagement": "Engaged with Timebeat",
}

ICP_FIELDS = {
    "competitor_engagement": [
        {"key": "competitors", "label": "Competitor names to monitor", "type": "list", "placeholder": "e.g. Meinberg, Microsemi, Orolia"},
        {"key": "target_titles", "label": "Target job titles", "type": "list", "placeholder": "e.g. VP Infrastructure, Head of Network Engineering"},
        {"key": "exclude_seniority", "label": "Exclude seniority levels", "type": "list", "placeholder": "e.g. Junior, Intern (optional)"},
    ],
    "influencer_engagement": [
        {"key": "influencer_profiles", "label": "LinkedIn influencer profiles or names", "type": "list", "placeholder": "e.g. John Doe (PTP expert), IEEE 1588 Working Group"},
        {"key": "hashtags", "label": "LinkedIn hashtags to track", "type": "list", "placeholder": "e.g. PTP, IEEE1588, timesync, 5G"},
        {"key": "target_industries", "label": "Target industries", "type": "list", "placeholder": "e.g. Capital Markets, Telecoms, Broadcast"},
        {"key": "company_size", "label": "Company size range", "type": "text", "placeholder": "e.g. 500-10000 employees"},
    ],
    "job_change": [
        {"key": "target_titles", "label": "Target new role titles", "type": "list", "placeholder": "e.g. VP Infrastructure, CTO, Head of Network"},
        {"key": "seniority_levels", "label": "Seniority levels", "type": "list", "placeholder": "e.g. VP, Director, Head, C-Suite"},
        {"key": "industries", "label": "Target industries", "type": "list", "placeholder": "e.g. Capital Markets, Telecoms, Defence"},
        {"key": "recency_days", "label": "Recency window (days)", "type": "select", "options": ["30", "60", "90"], "default": "30"},
    ],
    "funding": [
        {"key": "funding_stages", "label": "Funding stages", "type": "list", "placeholder": "e.g. Seed, Series A, Series B"},
        {"key": "target_industries", "label": "Target industries", "type": "list", "placeholder": "e.g. Fintech, HFT, Telecoms"},
        {"key": "company_size_post_funding", "label": "Post-funding company size", "type": "text", "placeholder": "e.g. 50-500 employees"},
        {"key": "target_roles", "label": "Decision-maker roles to target", "type": "list", "placeholder": "e.g. CTO, Head of Infrastructure, VP Technology"},
    ],
    "top_icp": [
        {"key": "target_titles", "label": "Target job titles", "type": "list", "placeholder": "e.g. Head of Network, VP Infrastructure"},
        {"key": "target_industries", "label": "Target industries", "type": "list", "placeholder": "e.g. Capital Markets, Telecoms, Broadcast"},
        {"key": "geography", "label": "Target geographies", "type": "list", "placeholder": "e.g. UK, Germany, US, Singapore"},
    ],
    "company_engagement": [
        {"key": "seniority_filter", "label": "Seniority filter (optional)", "type": "list", "placeholder": "e.g. VP, Director, C-Suite (leave blank for all)"},
    ],
}


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


def new_id() -> str:
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# ICP configs
# ---------------------------------------------------------------------------

def load_icp_configs() -> dict:
    return _read_json(ICP_CONFIGS_FILE, {})


def get_user_icp(username: str) -> dict:
    return load_icp_configs().get(username, {})


def get_signal_icp(username: str, signal_type: str) -> dict | None:
    return get_user_icp(username).get(signal_type)


def save_signal_icp(username: str, signal_type: str, config: dict) -> None:
    configs = load_icp_configs()
    if username not in configs:
        configs[username] = {}
    configs[username][signal_type] = config
    _write_json(ICP_CONFIGS_FILE, configs)


def is_icp_complete(username: str, signal_type: str) -> bool:
    config = get_signal_icp(username, signal_type)
    if not config:
        return False
    fields = ICP_FIELDS.get(signal_type, [])
    for f in fields:
        if f.get("type") == "list":
            val = config.get(f["key"])
            if not val or (isinstance(val, list) and len(val) == 0):
                # Only check required fields (those without "optional" in label)
                if "optional" not in f.get("label", "").lower():
                    return False
    return True


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

def load_signals() -> list[dict]:
    return _read_json(SIGNALS_FILE, [])


def load_user_signals(username: str) -> list[dict]:
    return [s for s in load_signals() if s.get("username") == username]


def get_signal(signal_id: str, username: str | None = None) -> dict | None:
    for s in load_signals():
        if s.get("id") != signal_id:
            continue
        if username is not None and s.get("username") != username:
            return None
        return s
    return None


def upsert_signal(signal: dict, username: str | None = None) -> dict:
    if not signal.get("id"):
        signal["id"] = new_id()
    if not signal.get("detected_at"):
        signal["detected_at"] = now_label()
    signal["updated_at"] = now_label()
    if username is not None:
        signal["username"] = username

    signals = load_signals()
    signals = [s for s in signals if s.get("id") != signal["id"]]
    signals.insert(0, signal)
    signals = signals[:SIGNAL_CAP]
    _write_json(SIGNALS_FILE, signals)
    return signal


def patch_signal(signal_id: str, patch: dict, username: str | None = None) -> dict | None:
    existing = get_signal(signal_id, username=username)
    if not existing:
        return None
    existing.update(patch)
    return upsert_signal(existing)


def delete_signal(signal_id: str, username: str | None = None) -> bool:
    signals = load_signals()
    new_list = [
        s for s in signals
        if not (s.get("id") == signal_id and (username is None or s.get("username") == username))
    ]
    if len(new_list) == len(signals):
        return False
    _write_json(SIGNALS_FILE, new_list)
    return True


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

def load_messages() -> list[dict]:
    return _read_json(MESSAGES_FILE, [])


def load_user_messages(username: str) -> list[dict]:
    return [m for m in load_messages() if m.get("username") == username]


def get_message_for_signal(signal_id: str, username: str | None = None) -> dict | None:
    for m in load_messages():
        if m.get("signal_id") != signal_id:
            continue
        if username is not None and m.get("username") != username:
            return None
        return m
    return None


def upsert_message(message: dict, username: str | None = None) -> dict:
    if not message.get("id"):
        message["id"] = new_id()
    if not message.get("composed_at"):
        message["composed_at"] = now_label()
    message["updated_at"] = now_label()
    if username is not None:
        message["username"] = username

    messages = load_messages()
    messages = [m for m in messages if m.get("id") != message["id"]]
    messages.insert(0, message)
    _write_json(MESSAGES_FILE, messages[:500])
    return message


def stats(username: str) -> dict:
    signals = load_user_signals(username)
    messages = load_user_messages(username)
    queue = [s for s in signals if s.get("status") in ("pending", "composing", "composed")]
    sent = [m for m in messages if m.get("status") == "sent"]
    by_type = {}
    for s in signals:
        t = s.get("signal_type", "unknown")
        by_type[t] = by_type.get(t, 0) + 1
    return {
        "signals_total": len(signals),
        "queue_depth": len(queue),
        "messages_sent": len(sent),
        "by_type": by_type,
    }
