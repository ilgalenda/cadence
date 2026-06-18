import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from auth import require_authed
from paths import calls_transcripts

TRANSCRIPTS_DIR = calls_transcripts()
TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

router = APIRouter(prefix="/api/meet", tags=["meet"])

_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


class SaveTranscriptRequest(BaseModel):
    transcript: str
    session_id: str = ""
    title: str = "Google Meet"


@router.post("/submit")
def save_meet_transcript(req: SaveTranscriptRequest, _user: dict = Depends(require_authed)):
    """Saves the raw Meet transcript text for later download. Analysis is handled by /api/analyze."""
    if not req.transcript.strip():
        raise HTTPException(status_code=400, detail="Transcript is empty.")

    session_id = req.session_id if req.session_id and _SESSION_ID_RE.match(req.session_id) else uuid.uuid4().hex
    transcript_path = TRANSCRIPTS_DIR / f"{session_id}.txt"
    transcript_path.write_text(req.transcript, encoding="utf-8")
    return {"transcript_id": session_id}


@router.get("/transcript/{session_id}")
def get_transcript(session_id: str, _user: dict = Depends(require_authed)):
    if not _SESSION_ID_RE.match(session_id):
        raise HTTPException(status_code=400, detail="Invalid session ID.")
    path = TRANSCRIPTS_DIR / f"{session_id}.txt"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Transcript not found.")
    return FileResponse(
        path,
        media_type="text/plain",
        filename=f"transcript-{session_id}.txt",
        headers={"Content-Disposition": f'attachment; filename="transcript-{session_id}.txt"'},
    )
