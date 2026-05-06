import json
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
SESSIONS_FILE = DATA_DIR / "sessions.json"

SESSION_CAP = 200


def load_sessions() -> list[dict]:
    if not SESSIONS_FILE.exists():
        return []
    try:
        return json.loads(SESSIONS_FILE.read_text())
    except Exception:
        return []


def save_owl_session(session: dict, username: str) -> None:
    session["username"] = username
    sessions = load_sessions()
    sessions.insert(0, session)
    sessions = sessions[:SESSION_CAP]
    SESSIONS_FILE.write_text(json.dumps(sessions, indent=2))


def load_user_owl_sessions(username: str) -> list[dict]:
    return [s for s in load_sessions() if s.get("username") == username]


def format_timestamp() -> str:
    return datetime.utcnow().strftime("%d %b %Y, %H:%M")
