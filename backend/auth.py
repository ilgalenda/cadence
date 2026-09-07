import json
from typing import Optional

import bcrypt
from fastapi import HTTPException, Request

from paths import users_credentials_file, users_file


def _load_credentials() -> dict[str, str]:
    """Return {username: password_hash} from the gitignored credentials file."""
    path = users_credentials_file()
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("credentials", {})


def load_users() -> list[dict]:
    """Load user profiles from the committed users.json and merge in
    password hashes from the gitignored users_credentials.json.
    """
    path = users_file()
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    profiles = data.get("users", [])
    credentials = _load_credentials()
    merged = []
    for profile in profiles:
        merged_profile = dict(profile)
        username = merged_profile.get("username")
        if username and username in credentials:
            merged_profile["password_hash"] = credentials[username]
        merged.append(merged_profile)
    return merged


def find_user(username: str) -> Optional[dict]:
    for user in load_users():
        if user.get("username") == username:
            return user
    return None


def verify_login(username: str, password: str) -> Optional[dict]:
    user = find_user(username)
    if not user:
        return None
    stored = user.get("password_hash", "").encode("utf-8")
    if not stored:
        return None
    if not bcrypt.checkpw(password.encode("utf-8"), stored):
        return None
    return user


def public_user(user: dict) -> dict:
    return {
        "username": user["username"],
        "name": user.get("name", user["username"]),
        "role": user.get("role", ""),
        "access": user.get("access", "user"),
        "agents": user.get("agents", []),
    }


def current_user(request: Request) -> Optional[dict]:
    username = request.session.get("user")
    if not username:
        return None
    return find_user(username)


def require_authed(request: Request) -> dict:
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_admin(request: Request) -> dict:
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if user.get("access") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def is_admin(user: dict) -> bool:
    """Whether this person sees everything.

    `require_admin` is for a route that refuses; this is for one that *narrows* —
    the same question asked where the answer changes a query rather than the
    response code. Mirrors `isAdmin` in the frontend's `lib/session.ts`.
    """
    return user.get("access") == "admin"


def is_sandbox(request: Request) -> bool:
    user = current_user(request)
    if not user or user.get("access") != "admin":
        return False
    return bool(request.session.get("sandbox", False))


def require_agent_access(slug: str):
    def _dep(request: Request) -> dict:
        user = current_user(request)
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")
        if slug not in user.get("agents", []):
            raise HTTPException(status_code=403, detail=f"No access to {slug} agent")
        return user
    return _dep
