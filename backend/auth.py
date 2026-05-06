import json
from pathlib import Path
from typing import Optional

import bcrypt
from fastapi import HTTPException, Request

USERS_FILE = Path(__file__).parent / "agents" / "users.json"


def load_users() -> list[dict]:
    if not USERS_FILE.exists():
        return []
    with USERS_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("users", [])


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


def require_agent_access(slug: str):
    def _dep(request: Request) -> dict:
        user = current_user(request)
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")
        if slug not in user.get("agents", []):
            raise HTTPException(status_code=403, detail=f"No access to {slug} agent")
        return user
    return _dep
