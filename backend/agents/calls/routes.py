import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import aiofiles
import anthropic
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents.shared.vault import load_vault_for_context, write_glossary_term, write_learning
from auth import require_admin, require_authed

# ---------------------------------------------------------------------------
# Paths (scoped to the Calls Agent)
# ---------------------------------------------------------------------------
AGENT_DIR = Path(__file__).parent
KNOWLEDGE_DIR = AGENT_DIR / "knowledge"
USER_KNOWLEDGE_DIR = KNOWLEDGE_DIR / "_user"
DATA_DIR = AGENT_DIR / "data"
LEARNINGS_DIR = DATA_DIR / "learnings"
DATA_DIR.mkdir(exist_ok=True)
LEARNINGS_DIR.mkdir(exist_ok=True)
USER_KNOWLEDGE_DIR.mkdir(exist_ok=True)
SESSIONS_FILE = DATA_DIR / "sessions.json"


def user_learnings_json(username: str) -> Path:
    return LEARNINGS_DIR / f"{username}.json"


def user_learnings_md(username: str) -> Path:
    d = USER_KNOWLEDGE_DIR / username
    d.mkdir(parents=True, exist_ok=True)
    return d / "learnings-auto.md"

# Backend root (for locating bin/ with ffmpeg-style helpers)
BACKEND_DIR = AGENT_DIR.parent.parent


# ---------------------------------------------------------------------------
# Static reference data
# ---------------------------------------------------------------------------

GLOSSARY = [
    {"term": "TaaS (Time as a Service)", "definition": "Instead of buying and maintaining their own grandmaster clock and PTP infrastructure, clients subscribe to a managed timing service. TaaS is to timing what AWS is to servers.", "products": ["Clock Sync Software", "vGMC"], "protocol": "PTP / NTP"},
    {"term": "PTP (Precision Time Protocol)", "definition": "Gold standard protocol for synchronising clocks across a network. Achieves sub-microsecond accuracy. Works by having a grandmaster clock distribute precise timestamps down through the network.", "products": ["Clock Quorum", "Open Timecard", "Open Time Server"], "protocol": "PTP"},
    {"term": "Grandmaster Clock (GMC)", "definition": "The single authoritative clock that all other devices in a PTP network sync to. Typically connected to a GNSS antenna or atomic clock. The root time for a PTP network.", "products": ["Clock Quorum", "Open Timecard", "Open Time Server"], "protocol": "PTP"},
    {"term": "vGMC (Virtual Grandmaster Clock)", "definition": "Turns a Linux server or Open Time Server into a virtual grandmaster clock. Enables serving hundreds of isolated PTP timing feeds simultaneously, each with its own configuration and SLA monitoring.", "products": ["Clock Sync Software", "Open Time Server"], "protocol": "PTP"},
    {"term": "Clock Quorum", "definition": "A timing network that cross-checks itself for errors. It's a self-verifying network running a consensus algorithm — Timebeat's key differentiator.", "products": ["Clock Quorum"], "protocol": "PTP / PNT"},
    {"term": "GNSS Antenna", "definition": "Global Navigation Satellite System. Umbrella for GPS (USA), Galileo (EU), GLONASS (Russia) and BeiDou (China). Receives signals from satellites and feeds precise time-of-day into a grandmaster clock.", "products": ["Clock Quorum", "Open Timecard"], "protocol": "PNT"},
    {"term": "White Rabbit", "definition": "Picosecond timing distribution technology. Open-source extension of PTP developed at CERN. Achieves sub-nanosecond accuracy over fibre links up to 100 km. Combines PTP with SyncE and precision hardware timestamping.", "products": ["White Rabbit Ecosystem"], "protocol": "White Rabbit / PTP"},
    {"term": "STL (Satellite Time and Location)", "definition": "Service by Satelles using LEO satellites (~780 km altitude, vs GPS at ~20,000 km). Signal is 1,000x stronger than GPS — far harder to jam or spoof. Critical for defence and finance.", "products": ["Clock Quorum", "Open Timecard"], "protocol": "STL"},
    {"term": "Galileo OSNMA", "definition": "Open Service Navigation Message Authentication. Anti-spoofing security built into Galileo satellites. Lets a GNSS receiver verify that timing signals genuinely came from real Galileo satellites, not tampered or faked.", "products": ["Clock Quorum"], "protocol": "GNSS / Galileo"},
    {"term": "Boundary Clock (BTP)", "definition": "Sits between a grandmaster and end devices, syncing upstream and re-distributing downstream. Like a relay runner — receives the timing baton and hands it off cleanly to the next leg, preventing errors stacking up.", "products": ["Clock Quorum", "Open Time Server"], "protocol": "PTP"},
    {"term": "SyncE (Synchronous Ethernet)", "definition": "Distributes frequency synchronisation at the physical layer — the ethernet hardware locks to the same frequency as the grandmaster. Works alongside PTP.", "products": ["White Rabbit Ecosystem"], "protocol": "SyncE"},
    {"term": "1PPS (One Pulse Per Second)", "definition": "A precise hardware electrical pulse used to discipline local oscillators. Complementary to PTP — provides a frequency reference.", "products": ["Open Timecard", "Open Time Server"], "protocol": "1PPS"},
    {"term": "PNT (Positioning, Navigation and Timing)", "definition": "The three services delivered by GNSS systems. For Timebeat customers, the timing component is most critical — the atomic-clock-accurate signals underpinning 5G, financial trading, and power grids.", "products": ["Clock Quorum", "Open Timecard"], "protocol": "PNT"},
    {"term": "PDP (Picosecond Distribution Protocol)", "definition": "A picosecond is a trillionth of a second (1,000x smaller than a nanosecond). Required by particle physics (CERN), HFT, defence & radar, and quantum computing.", "products": ["White Rabbit Ecosystem"], "protocol": "White Rabbit"},
    {"term": "OEM Models", "definition": "Original Equipment Manufacturer — Timebeat's technology embedded inside another vendor's product under that vendor's brand. OEM deals are typically large-volume and strategically important.", "products": ["White Rabbit Mezzanine"], "protocol": "N/A"},
    {"term": "Consensus Algorithm", "definition": "Timebeat's method of cross-checking multiple time sources against each other to prove accuracy rather than just claim it. The foundation of the Clock Quorum product.", "products": ["Clock Quorum"], "protocol": "Proprietary"},
    {"term": "Baseband Unit (BBU)", "definition": "Handles all digital signal processing for a 5G cell site. Communicates with the Remote Radio Head (RRH / antenna). Requires precise timing from a grandmaster.", "products": ["Clock Quorum", "Open Timecard"], "protocol": "PTP / PNT"},
    {"term": "Self-verifying network", "definition": "A timing infrastructure that continuously proves its own accuracy without relying on a single source. The Clock Quorum achieves this via consensus.", "products": ["Clock Quorum"], "protocol": "Consensus"},
    {"term": "Switch Ecosystem", "definition": "Uses standard PTP-capable Ethernet switches with boundary clock support. Widely compatible, limited to microsecond accuracy. Alternative to the White Rabbit ecosystem.", "products": ["Clock Quorum"], "protocol": "PTP"},
    {"term": "P2P / Terrestrial P2P", "definition": "Peer-to-peer delay measurement in PTP — each link calculates its own delay independently. A terrestrial P2P source is a ground-based timing reference instead of satellite.", "products": ["Open Time Server", "Clock Quorum"], "protocol": "PTP"},
]

PRODUCTS = [
    {
        "name": "Clock Quorum",
        "type": "Hardware — 19\" Rack",
        "tagline": "Best-selling. Self-verifying grandmaster with consensus.",
        "description": "The Open Time Appliance. Does the job of every other 19-inch rackmount grandmaster solution. The consensus algorithm is Timebeat's biggest differentiator — it proves accuracy rather than claiming it.",
        "specs": ["1 Gbps network speed", "GNSS + STL input", "PTP + NTP output", "Consensus algorithm"],
        "ideal_customer": "Data centres, colocation providers, telecoms, enterprises running PTP infrastructure.",
        "use_cases": ["Traditional PNT/PTP deployments", "Data centre timing", "5G backhaul"],
        "competitive_angle": "Competitors sell grandmasters. Timebeat sells a self-verifying timing network. The consensus is the moat.",
    },
    {
        "name": "Open Timecard",
        "type": "Hardware — PCIe Card",
        "tagline": "Grandmaster inside your server. Full flexibility.",
        "description": "A fully fledged grandmaster on a PCIe card. Can be standalone or integrated with the host server. Has its own computational system and network ports. Falls under infrastructure ownership rather than network device.",
        "specs": ["1 Gbps network speed", "PCIe form factor", "GNSS input", "PTP output", "Runs Timebeat software"],
        "ideal_customer": "Defence organisations, consultancy firms, enterprises that want timing embedded in their own infrastructure.",
        "use_cases": ["Defence deployments", "Consultancy integrations", "Infrastructure-owned timing"],
        "competitive_angle": "Goes inside the customer's server — under their ownership and control. Appeals to organisations with strict infrastructure sovereignty requirements.",
    },
    {
        "name": "Open Time Server",
        "type": "Hardware — Server Integration",
        "tagline": "Converts your server into a grandmaster. Hyperscale-ready.",
        "description": "Similar to the Timecard but converts the rest of the host server into the grandmaster. Links to the host's network card for higher network speeds. Designed for customers that want Timebeat certification and larger network throughput.",
        "specs": [">1 Gbps (host NIC speed)", "PCIe card + host integration", "GNSS input", "PTP output", "Timebeat certified"],
        "ideal_customer": "Hyperscale operators, cloud providers, enterprises needing high-speed timing distribution.",
        "use_cases": ["Hyperscale timing", "High-speed trading infrastructure", "Large-scale PTP distribution"],
        "competitive_angle": "Higher network speed than standalone grandmasters by leveraging the host server's NIC. Scales with the host.",
    },
    {
        "name": "Clock Sync Software",
        "type": "Software",
        "tagline": "The richest timing monitoring dashboard in the market.",
        "description": "Comprehensive software by Timebeat. 10–12 monitoring dashboards. Reflects real-world implementation cases. User-first experience. Free 90-day licences — monetised through support packages.",
        "specs": ["10–12 dashboards", "90-day free licence", "Support packages", "Runs on Linux"],
        "ideal_customer": "Any organisation running PTP infrastructure that wants visibility and monitoring.",
        "use_cases": ["Timing infrastructure monitoring", "SLA tracking", "Root cause analysis"],
        "competitive_angle": "Software-first origins means the dashboard experience is significantly richer than hardware-centric competitors who treat software as an afterthought.",
    },
    {
        "name": "White Rabbit Ecosystem",
        "type": "Hardware + Software Suite",
        "tagline": "Picosecond precision. The 2026 priority.",
        "description": "A complete ecosystem for picosecond timing distribution — the ultimate precision tier. Four pillars: Mezzanine (OEM integrations), Open Time Node (frequency distribution), White Rabbit Switch (24-port, 10G/1G), White Rabbit Test Rig (demo & validation environment).",
        "specs": ["Sub-nanosecond accuracy", "Fibre links up to 100 km", "24-port switch (10G/1G)", "Combines PTP + SyncE"],
        "ideal_customer": "High-frequency trading firms, defence & radar, particle physics labs (CERN-style), quantum computing.",
        "use_cases": ["HFT infrastructure", "Defence precision timing", "Scientific research (CERN)", "Quantum computing"],
        "competitive_angle": "Most vendors stop at microseconds. White Rabbit is in picoseconds — a completely different league for industries where nanoseconds matter.",
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_knowledge(_username: str) -> str:
    """Load the shared vault: curated KB + glossary + team-wide empirical learnings."""
    return load_vault_for_context()


def get_system_prompt(user: dict) -> str:
    name = user.get("name") or user.get("username", "the user").split()[0]
    first_name = name.split()[0]
    role = user.get("role") or "Account Executive"
    knowledge = load_knowledge(user["username"])
    return f"""You are Owl — {first_name}'s personal Timebeat knowledge partner. {first_name} is a {role} at Timebeat. You have deep knowledge of Timebeat's products, protocols, terminology, and sales signals, and you grow smarter with every call {first_name} analyses.

Your role:
- Answer questions as a knowledgeable Timebeat colleague would — concise, practical, and sales-aware
- Help {first_name} understand technical concepts in the context of selling them
- Identify buying signals, objections, and product fit in conversations
- When {first_name} asks about a term or product, give a clear definition AND the sales relevance
- Always frame answers in a way that helps {first_name} succeed in sales conversations

The knowledge base below includes the full Timebeat product and protocol KB, a glossary of terms that has grown from real field conversations, and team-wide learnings extracted from every call and campaign run by the whole team. Treat all of this as validated context and reference it when relevant.

Here is the complete Timebeat knowledge base:

{knowledge}"""


def load_sessions() -> list[dict]:
    if not SESSIONS_FILE.exists():
        return []
    try:
        return json.loads(SESSIONS_FILE.read_text())
    except Exception:
        return []


def save_session(session: dict, username: str) -> None:
    session["username"] = username
    sessions = load_sessions()
    sessions.insert(0, session)
    sessions = sessions[:200]  # keep last 200 across all users
    SESSIONS_FILE.write_text(json.dumps(sessions, indent=2))


def load_user_sessions(username: str) -> list[dict]:
    return [s for s in load_sessions() if s.get("username") == username]


def load_learnings(username: str) -> list[dict]:
    path = user_learnings_json(username)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def save_learnings_from_analysis(call_id: str, call_title: str, extracts: list[dict], username: str) -> None:
    if not extracts:
        return
    try:
        learnings = load_learnings(username)
        created_at = datetime.now(timezone.utc).isoformat()
        date_label = datetime.now(timezone.utc).strftime("%d %b %Y")
        new_rows = []
        md_blocks = []
        for item in extracts:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            content = str(item.get("content", "")).strip()
            category = str(item.get("category", "")).strip() or "general"
            if not title or not content:
                continue
            entry_id = uuid.uuid4().hex
            new_rows.append({
                "id": entry_id,
                "title": title,
                "content": content,
                "category": category,
                "source_call_id": call_id,
                "source_call_title": call_title,
                "created_at": created_at,
            })
            md_blocks.append(
                f"## {title} — {date_label} (from: {call_title})\n"
                f"*Category: {category}*\n\n"
                f"{content}\n"
            )
            # Write to vault (shared across all users)
            write_learning(
                title=title,
                content=content,
                category=category,
                agent="calls",
                contributed_by=username,
                source_id=call_id,
                source_title=call_title,
            )
        if not new_rows:
            return
        learnings = new_rows + learnings
        user_learnings_json(username).write_text(json.dumps(learnings, indent=2))

        header = (
            "<!-- Auto-generated by the Calls Agent. Each analysed call appends a section below. -->\n"
            f"# Learnings from {username}'s analysed calls\n\n"
        )
        md_path = user_learnings_md(username)
        existing = ""
        if md_path.exists():
            existing = md_path.read_text(encoding="utf-8")
            if existing.startswith(header):
                existing = existing[len(header):]
        md_path.write_text(header + "\n".join(md_blocks) + "\n" + existing, encoding="utf-8")
    except Exception as e:
        # Persistence failures must not break the analysis response.
        print(f"[calls] failed to persist learnings: {e}")


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api", tags=["calls"])


class ChatRequest(BaseModel):
    messages: list[dict]


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest, user: dict = Depends(require_authed)):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set. Add it to your .env file.")

    client = anthropic.Anthropic(api_key=api_key)

    async def generate():
        full_response = []
        try:
            with client.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=get_system_prompt(user),
                messages=req.messages,
            ) as stream:
                for text in stream.text_stream:
                    full_response.append(text)
                    yield f"data: {json.dumps({'text': text})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            return

        user_msg = req.messages[-1].get("content", "") if req.messages else ""
        preview = user_msg[:60] if isinstance(user_msg, str) else ""
        save_session({
            "id": uuid.uuid4().hex,
            "title": preview or "Chat",
            "type": "chat",
            "timestamp": datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M"),
        }, user["username"])

    return StreamingResponse(generate(), media_type="text/event-stream")


class AnalyzeRequest(BaseModel):
    text: str
    title: str = "Call Analysis"


@router.post("/analyze")
async def analyze_call(req: AnalyzeRequest, user: dict = Depends(require_authed)):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set.")

    client = anthropic.Anthropic(api_key=api_key)
    name = (user.get("name") or user.get("username", "the user")).split()[0]

    prompt = f"""Analyse this call or meeting transcript from a Timebeat sales perspective.

Transcript:
{req.text}

Return ONLY a valid JSON object (no markdown, no explanation) with exactly these keys:
{{
  "buying_signals": ["list of buying signal strings found in the conversation"],
  "product_fit": ["list of Timebeat product names that match the conversation context"],
  "objections": ["list of objections, concerns, or hesitations raised"],
  "talking_points": ["list of suggested talking points or follow-up questions for {name}"],
  "concepts_mentioned": ["list of Timebeat concepts or protocols referenced"],
  "summary": "A 2-sentence summary of the conversation from a sales perspective",
  "product_recommendation": {{
    "primary": "name of the single best-fit Timebeat product",
    "reasoning": "2-3 sentences explaining exactly why this product is the best fit based on what was said in the call",
    "all_fits": [
      {{"product": "product name", "fit": "high/medium/low", "reason": "one sentence why"}}
    ]
  }},
  "knowledge_extracts": [
    {{"title": "short title", "content": "key learning or insight from this call that {name} should remember", "category": "technical/sales/objection/industry"}}
  ],
  "flashcards": [
    {{"type": "flashcard", "question": "question about a concept from this call", "answer": "clear, concise answer"}},
    {{"type": "mcq", "question": "multiple choice question about the call or product", "options": ["option A", "option B", "option C", "option D"], "correct": 0, "explanation": "why this answer is correct"}}
  ],
  "new_terms": [
    {{
      "term": "canonical name of the term",
      "definition": "2-3 sentences: what this term is and how it works technically",
      "timebeat_context": "1-2 sentences: why this term matters to Timebeat — what customer problem it addresses and which Timebeat product or capability is relevant",
      "sales_note": "1 sentence: what it signals in a prospect conversation and how to respond",
      "related_products": ["Timebeat product names that relate to this term"],
      "aliases": ["alternative names, abbreviations, acronyms"],
      "tags": ["relevant topic slugs e.g. 5g, defence, financial, hardware"]
    }}
  ]
}}

Rules:
- knowledge_extracts: extract 3-5 genuinely useful learning points (technical insights, sales patterns, industry context)
- flashcards: create 4-6 items mixing flashcards and multiple choice. Cover product knowledge, protocols mentioned, sales concepts, and objection handling
- new_terms: extract technical terms, protocols, acronyms, or company-specific concepts mentioned in this call that are NOT already in the knowledge base. For each term write a developed, standalone explanation — definition, Timebeat relevance, and a practical sales note — so the entry is useful for recall without any surrounding context. Return empty array if nothing genuinely new. Max 5 entries.
- product_recommendation.all_fits: list ALL products relevant to this call with fit score
- If a category has no entries, return an empty array. Be specific and actionable."""

    import re as _re
    response = None
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8192,
            system=get_system_prompt(user),
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        # Extract JSON from a fenced block first (handles any preamble text)
        fence_match = _re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, _re.DOTALL)
        if fence_match:
            raw = fence_match.group(1)
        else:
            obj_match = _re.search(r"\{.*\}", raw, _re.DOTALL)
            if obj_match:
                raw = obj_match.group(0)
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        raw_text = response.content[0].text if response else ""
        print(f"[calls] JSON parse failed: {e}\nRaw (first 500): {raw_text[:500]}")
        result = {
            "buying_signals": [],
            "product_fit": [],
            "objections": [],
            "talking_points": [],
            "concepts_mentioned": [],
            "summary": raw_text,
            "product_recommendation": {},
            "knowledge_extracts": [],
            "flashcards": [],
            "new_terms": [],
        }

    call_id = uuid.uuid4().hex
    session = {
        "id": call_id,
        "title": req.title,
        "type": "call_analysis",
        "timestamp": datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M"),
        "result": result,
    }
    save_session(session, user["username"])
    save_learnings_from_analysis(call_id, req.title, result.get("knowledge_extracts", []) or [], user["username"])

    # Persist any new terms discovered during this call into the vault glossary
    for term_entry in result.get("new_terms", []) or []:
        if not isinstance(term_entry, dict):
            continue
        term = str(term_entry.get("term", "")).strip()
        definition = str(term_entry.get("definition", "")).strip()
        if not term or not definition:
            continue
        try:
            # Build a structured, developed body from all richer fields Claude extracted
            timebeat_context = str(term_entry.get("timebeat_context", "")).strip()
            sales_note = str(term_entry.get("sales_note", "")).strip()
            related_products = [p for p in (term_entry.get("related_products") or []) if isinstance(p, str) and p.strip()]

            body_parts = [definition]
            if timebeat_context:
                body_parts.append(f"**Timebeat context:** {timebeat_context}")
            if sales_note:
                body_parts.append(f"**Sales note:** {sales_note}")
            if related_products:
                links = ", ".join(f"[[{p.strip()}]]" for p in related_products)
                body_parts.append(f"**Related products:** {links}")

            write_glossary_term(
                term=term,
                definition="\n\n".join(body_parts),
                source_id=call_id,
                contributed_by=user["username"],
                aliases=term_entry.get("aliases") or [],
                tags=term_entry.get("tags") or [],
            )
        except Exception as e:
            print(f"[calls] failed to write glossary term '{term}': {e}")

    return {"id": call_id, **result}


@router.post("/transcribe")
async def transcribe_video(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".mp4"):
        raise HTTPException(status_code=400, detail="Only MP4 files are supported.")

    suffix = ".mp4"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = tmp.name
        content = await file.read()
        tmp.write(content)

    try:
        import shutil
        from faster_whisper import WhisperModel  # lazy import — heavy

        bin_dir = BACKEND_DIR.parent / "bin"
        extra_paths = [
            str(bin_dir),
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "/usr/bin",
        ]
        os.environ["PATH"] = ":".join(extra_paths) + ":" + os.environ.get("PATH", "")

        if not shutil.which("ffmpeg"):
            raise HTTPException(
                status_code=422,
                detail=(
                    "ffmpeg is required for MP4 transcription but was not found. "
                    "To install it:\n\n"
                    "1. Install Homebrew (macOS package manager):\n"
                    '   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"\n\n'
                    "2. Then install ffmpeg:\n"
                    "   brew install ffmpeg\n\n"
                    "After installation, restart the server and try again."
                ),
            )

        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(tmp_path)
        transcript = " ".join(segment.text.strip() for segment in segments)
    except HTTPException:
        raise
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="faster-whisper is not installed. Run: pip3 install faster-whisper",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return {"transcript": transcript, "filename": file.filename}


@router.get("/sessions")
def get_sessions(user: dict = Depends(require_authed)):
    return load_user_sessions(user["username"])


@router.get("/stats")
def get_stats(user: dict = Depends(require_authed)):
    sessions = load_user_sessions(user["username"])
    knowledge_files = [
        f.name for f in KNOWLEDGE_DIR.iterdir()
        if f.suffix.lower() in {".md", ".txt"} and f.is_file()
    ]
    if (USER_KNOWLEDGE_DIR / user["username"] / "learnings-auto.md").is_file():
        knowledge_files.append("learnings-auto.md")
    return {
        "calls_analysed": sum(1 for s in sessions if s.get("type") == "call_analysis"),
        "questions_asked": sum(1 for s in sessions if s.get("type") == "chat"),
        "knowledge_files": len(knowledge_files),
        "sessions_total": len(sessions),
    }


@router.get("/glossary")
def get_glossary():
    return GLOSSARY


@router.get("/products")
def get_products():
    return PRODUCTS


@router.get("/knowledge")
def list_knowledge(user: dict = Depends(require_authed)):
    files = []
    for path in sorted(KNOWLEDGE_DIR.iterdir()):
        if path.suffix.lower() in {".md", ".txt"} and path.is_file():
            stat = path.stat()
            files.append({
                "name": path.name,
                "size_kb": round(stat.st_size / 1024, 1),
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%d %b %Y"),
                "protected": path.name == "timebeat-ivos.md",
                "auto_generated": False,
            })
    user_md = USER_KNOWLEDGE_DIR / user["username"] / "learnings-auto.md"
    if user_md.is_file():
        stat = user_md.stat()
        files.append({
            "name": "learnings-auto.md",
            "size_kb": round(stat.st_size / 1024, 1),
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%d %b %Y"),
            "protected": True,
            "auto_generated": True,
        })
    return files


@router.post("/knowledge/upload", dependencies=[Depends(require_admin)])
async def upload_knowledge(file: UploadFile = File(...)):
    if not file.filename.lower().endswith((".md", ".txt")):
        raise HTTPException(status_code=400, detail="Only .md and .txt files are supported.")

    dest = KNOWLEDGE_DIR / file.filename
    content = await file.read()
    async with aiofiles.open(dest, "wb") as f:
        await f.write(content)

    return {"message": f"Uploaded {file.filename}", "name": file.filename}


@router.get("/calls")
def list_analysed_calls(user: dict = Depends(require_authed)):
    sessions = load_user_sessions(user["username"])
    calls = []
    for s in sessions:
        if s.get("type") != "call_analysis":
            continue
        result = s.get("result") or {}
        calls.append({
            "id": s.get("id"),
            "title": s.get("title"),
            "timestamp": s.get("timestamp"),
            "summary": result.get("summary", "") if isinstance(result, dict) else "",
            "primary_product": (
                result.get("product_recommendation", {}).get("primary", "")
                if isinstance(result, dict) and isinstance(result.get("product_recommendation"), dict)
                else ""
            ),
        })
    return calls


@router.get("/calls/{call_id}")
def get_analysed_call(call_id: str, user: dict = Depends(require_authed)):
    for s in load_sessions():
        if s.get("type") == "call_analysis" and s.get("id") == call_id and s.get("username") == user["username"]:
            return s
    raise HTTPException(status_code=404, detail="Call analysis not found.")


@router.delete("/calls/{call_id}")
def delete_analysed_call(call_id: str, user: dict = Depends(require_authed)):
    sessions = load_sessions()
    new_sessions = [
        s for s in sessions
        if not (
            s.get("type") == "call_analysis"
            and s.get("id") == call_id
            and s.get("username") == user["username"]
        )
    ]
    if len(new_sessions) == len(sessions):
        raise HTTPException(status_code=404, detail="Call analysis not found.")
    SESSIONS_FILE.write_text(json.dumps(new_sessions, indent=2))
    return {"ok": True}


@router.get("/learnings")
def get_learnings(user: dict = Depends(require_authed)):
    return load_learnings(user["username"])


PROTECTED_KNOWLEDGE_FILES = {"timebeat-ivos.md", "learnings-auto.md", "timebeat-campaign-knowledge-base.md"}


@router.delete("/knowledge/{filename}", dependencies=[Depends(require_admin)])
def delete_knowledge(filename: str):
    if filename in PROTECTED_KNOWLEDGE_FILES:
        raise HTTPException(status_code=403, detail="This knowledge file is protected and cannot be deleted.")
    path = KNOWLEDGE_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    path.unlink()
    return {"message": f"Deleted {filename}"}
