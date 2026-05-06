import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from agents.calls.routes import router as calls_router
from agents.lead.routes import router as lead_router
from agents.owl.routes import router as owl_router
from auth import current_user, public_user, verify_login

load_dotenv()

# Cadence auth config — set in backend/.env:
#   SESSION_SECRET=<long random string>
#   IVAN_PASSWORD=<plaintext, used by seed_users.py>
#   TEST_PASSWORD=<plaintext, used by seed_users.py>
# Users themselves live in backend/agents/users.json (gitignored).
SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-secret-change-me")

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR.parent / "frontend" / "dist"
STATIC_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Cadence — Timebeat")

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
    https_only=False,
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
# Agent routers
# ---------------------------------------------------------------------------

app.include_router(calls_router)
app.include_router(lead_router)
app.include_router(owl_router)


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

    print("🚀  Cadence — Timebeat starting on http://localhost:8000")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
