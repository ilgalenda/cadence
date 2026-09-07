import os
from pathlib import Path

from dotenv import load_dotenv

# Load env vars BEFORE importing anything that resolves data paths — so
# DATA_ROOT is in os.environ when paths.py resolves storage locations. The
# agent router imports below transitively import paths.py.
load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from agents.admin.routes import router as admin_router
from agents.events.routes import router as events_router
from agents.outbound.routes import router as outbound_router
from agents.learn.routes import router as learn_router
from agents.owl.routes import router as owl_router
from agents.sales.routes import router as sales_router
from agents.wiki.routes import router as wiki_router
from integrations.google_routes import router as google_router
from auth import current_user, is_sandbox, public_user, require_admin, verify_login

# Cadence auth config — set in backend/.env:
#   SESSION_SECRET=<long random string>
#   <USER>_PASSWORD, one per person, — plaintext, used by seed_users.py to
#     write the gitignored ${DATA_ROOT}/agents/users_credentials.json.
# User profiles (name, role, access, agents) live in backend/agents/users.json
# and ARE committed; credentials live in users_credentials.json and are NOT.
SESSION_SECRET = os.getenv("SESSION_SECRET")
if not SESSION_SECRET:
    raise RuntimeError("SESSION_SECRET is not set. Add it to backend/.env before starting.")

DEBUG = os.getenv("DEBUG", "").lower() in ("1", "true", "yes")

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR.parent / "frontend" / "dist"
STATIC_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Cadence")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

AUTH_EXEMPT_PATHS = {"/api/login", "/api/logout", "/api/auth/status"}


@app.middleware("http")
async def require_api_auth(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and path not in AUTH_EXEMPT_PATHS:
        if not request.session.get("user"):
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    return await call_next(request)


# SessionMiddleware must be added AFTER the auth middleware so it sits
# outermost and populates request.session before auth runs.
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="cadence_session",
    https_only=not DEBUG,
    same_site="lax",
)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/login")
def login(req: LoginRequest, request: Request):
    user = verify_login(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    request.session["user"] = user["username"]
    return {"ok": True, **public_user(user)}


@app.post("/api/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/auth/status")
def auth_status(request: Request):
    user = current_user(request)
    if not user:
        return {"authed": False}
    return {"authed": True, **public_user(user)}


# ---------------------------------------------------------------------------
# Admin sandbox
# ---------------------------------------------------------------------------

@app.get("/api/admin/sandbox/status")
def sandbox_status(request: Request):
    return {"sandbox": is_sandbox(request)}


@app.post("/api/admin/sandbox/enable")
def sandbox_enable(request: Request, _user: dict = None):
    require_admin(request)
    request.session["sandbox"] = True
    return {"sandbox": True}


@app.post("/api/admin/sandbox/disable")
def sandbox_disable(request: Request, _user: dict = None):
    require_admin(request)
    request.session["sandbox"] = False
    return {"sandbox": False}


# ---------------------------------------------------------------------------
# Agent routers
# ---------------------------------------------------------------------------

app.include_router(admin_router)
app.include_router(owl_router)
app.include_router(sales_router)
app.include_router(learn_router)
app.include_router(wiki_router)

# Not a sales agent — trade-show readiness, no LLM call, not an Owl tool.
app.include_router(events_router)

# Not an agent either — the ABM tracker. GTM fills one; the record and its counters
# call no model and are not an Owl tool.
app.include_router(outbound_router)

# Not an agent — a shared connection agents borrow. Gmail joins it at Phase 4.
app.include_router(google_router)


# ---------------------------------------------------------------------------
# Static files (must be last — catches everything not matched above)
# ---------------------------------------------------------------------------

if STATIC_DIR.exists() and any(STATIC_DIR.iterdir()):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("\n⚠️  ANTHROPIC_API_KEY is not set!")
        print("   Create a .env file with: ANTHROPIC_API_KEY=sk-ant-...")
        print("   Get your key at: https://console.anthropic.com\n")

    print("🚀  Cadence starting on http://localhost:8000")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=DEBUG)
