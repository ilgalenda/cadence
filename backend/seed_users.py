"""One-shot seeder for backend/agents/users.json.

Reads IVAN_PASSWORD and TEST_PASSWORD from backend/.env and writes a users.json
file with bcrypt-hashed passwords. Run from the backend/ directory:

    python seed_users.py            # refuses if users.json already exists
    python seed_users.py --force    # overwrite
"""
import json
import os
import sys
from pathlib import Path

import bcrypt
from dotenv import load_dotenv

USERS_FILE = Path(__file__).parent / "agents" / "users.json"


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def main() -> int:
    load_dotenv()

    force = "--force" in sys.argv
    if USERS_FILE.exists() and not force:
        print(f"refusing to overwrite {USERS_FILE} (pass --force to overwrite)")
        return 1

    ivan_pw = os.getenv("IVAN_PASSWORD")
    test_pw = os.getenv("TEST_PASSWORD")
    jakub_pw = os.getenv("JAKUB_PASSWORD")
    missing = [
        name for name, val in [
            ("IVAN_PASSWORD", ivan_pw),
            ("TEST_PASSWORD", test_pw),
            ("JAKUB_PASSWORD", jakub_pw),
        ] if not val
    ]
    if missing:
        print(f"missing env vars: {', '.join(missing)} — set them in backend/.env")
        return 1

    payload = {
        "users": [
            {
                "username": "ivan",
                "password_hash": hash_password(ivan_pw),
                "name": "Ivan Galenda",
                "role": "GTM Account Executive",
                "access": "admin",
                "agents": ["calls", "lead"],
            },
            {
                "username": "test",
                "password_hash": hash_password(test_pw),
                "name": "Test User",
                "role": "Account Executive",
                "access": "user",
                "agents": ["calls", "lead"],
            },
            {
                "username": "jakub",
                "password_hash": hash_password(jakub_pw),
                "name": "Jakub",
                "role": "SDR",
                "access": "user",
                "agents": ["calls", "lead"],
            },
        ]
    }

    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with USERS_FILE.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"wrote {USERS_FILE} with {len(payload['users'])} users")
    return 0


if __name__ == "__main__":
    sys.exit(main())
