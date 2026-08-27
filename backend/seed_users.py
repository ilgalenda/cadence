"""Seed the gitignored credentials file for Cadence.

Reads one password env var per profile (ADMIN_PASSWORD, USER1_PASSWORD,
USER2_PASSWORD) from backend/.env and writes bcrypt hashes to
${DATA_ROOT}/agents/users_credentials.json.

Profiles (name, role, access, agents) live in the committed
backend/agents/users.json and are NOT touched by this script unless you
pass --rewrite-profiles (rarely needed: profile changes are usually a
manual edit of the committed file).

Adjust _DEFAULT_PROFILES (and the matching *_PASSWORD env vars) for your
own team before first run.

Usage from the backend/ directory:

    python seed_users.py            # writes/overwrites users_credentials.json
    python seed_users.py --rewrite-profiles
                                    # also reseeds users.json profiles for the
                                    # set of users below. Use only for fresh
                                    # installs.
"""
import json
import os
import sys

import bcrypt
from dotenv import load_dotenv


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


_DEFAULT_PROFILES = [
    {
        "username": "admin",
        "name": "Admin User",
        "role": "Administrator",
        "access": "admin",
        "agents": ["calls", "lead", "duty", "onboarding", "forecast"],
    },
    {
        "username": "user1",
        "name": "User One",
        "role": "Sales",
        "access": "user",
        "agents": ["calls", "lead", "duty", "onboarding", "forecast"],
    },
    {
        "username": "user2",
        "name": "User Two",
        "role": "SDR",
        "access": "user",
        "agents": ["calls", "lead", "duty", "onboarding", "forecast"],
    },
]


def main() -> int:
    load_dotenv()

    # Import after load_dotenv so DATA_ROOT in .env is honoured.
    from paths import users_credentials_file, users_file

    rewrite_profiles = "--rewrite-profiles" in sys.argv

    env_keys = [
        ("admin", "ADMIN_PASSWORD"),
        ("user1", "USER1_PASSWORD"),
        ("user2", "USER2_PASSWORD"),
    ]
    passwords = {username: os.getenv(env_var) for username, env_var in env_keys}
    missing = [env_var for username, env_var in env_keys if not passwords[username]]
    if missing:
        print(f"missing env vars: {', '.join(missing)} — set them in backend/.env")
        return 1

    creds_path = users_credentials_file()
    creds_path.parent.mkdir(parents=True, exist_ok=True)
    credentials_payload = {
        "credentials": {
            username: hash_password(passwords[username])
            for username, _ in env_keys
        }
    }
    with creds_path.open("w", encoding="utf-8") as f:
        json.dump(credentials_payload, f, indent=2)
    print(f"wrote {creds_path} with {len(credentials_payload['credentials'])} credentials")

    if rewrite_profiles:
        profiles_path = users_file()
        profiles_path.parent.mkdir(parents=True, exist_ok=True)
        with profiles_path.open("w", encoding="utf-8") as f:
            json.dump({"users": _DEFAULT_PROFILES}, f, indent=2)
        print(f"wrote {profiles_path} with {len(_DEFAULT_PROFILES)} profiles")

    return 0


if __name__ == "__main__":
    sys.exit(main())
