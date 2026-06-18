"""One-time migration of legacy Owl sessions.json into the SQLite store.

Each legacy record already holds the full message list, so we import it as a
single conversation with ordered messages. Idempotent — skips ids already
present. Does NOT delete sessions.json.

Run:  python3 backend/migrate_owl_sqlite.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).parent
sys.path.insert(0, str(BACKEND_DIR))

from agents.owl.db import DB_PATH, connect, init_db  # noqa: E402
from paths import owl_data  # noqa: E402

LEGACY_FILE = owl_data() / "sessions.json"
_LEGACY_FMT = "%d %b %Y, %H:%M"


def _to_iso(legacy_ts: str) -> str:
    try:
        dt = datetime.strptime(legacy_ts, _LEGACY_FMT).replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> None:
    init_db()
    if not LEGACY_FILE.exists():
        print(f"No legacy file at {LEGACY_FILE} — nothing to migrate.")
        return

    try:
        records = json.loads(LEGACY_FILE.read_text())
    except Exception as e:
        print(f"Could not read {LEGACY_FILE}: {e}")
        return

    imported = skipped = 0
    with connect() as conn:
        for rec in records:
            conv_id = rec.get("id")
            username = rec.get("username")
            if not conv_id or not username:
                skipped += 1
                continue
            exists = conn.execute(
                "SELECT 1 FROM conversations WHERE id = ?", (conv_id,)
            ).fetchone()
            if exists:
                skipped += 1
                continue

            iso = _to_iso(rec.get("timestamp", ""))
            topics = rec.get("topics") or []
            draft = rec.get("pending_correction_draft")
            conn.execute(
                """INSERT INTO conversations
                   (id, username, title, model_used, topics, pending_correction_draft, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (conv_id, username, rec.get("title") or "Chat",
                 rec.get("model_used"), json.dumps(topics),
                 json.dumps(draft) if draft else None, iso, iso),
            )
            for seq, m in enumerate(rec.get("messages", [])):
                conn.execute(
                    """INSERT INTO messages (conversation_id, role, content, seq, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (conv_id, m.get("role", "user"), m.get("content", ""), seq, iso),
                )
            imported += 1

    print(f"Migration complete → {DB_PATH}")
    print(f"  imported: {imported}")
    print(f"  skipped:  {skipped}")


if __name__ == "__main__":
    main()
