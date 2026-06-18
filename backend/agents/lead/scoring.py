from __future__ import annotations
"""Deterministic behavioural lead scoring from Leadinfo page-visit data.

No LLM. Given the pasted Leadinfo block (and any structured company size),
parse the "Page views" section, classify each visited page, and compute a
score that reflects buying intent:

  * more pages visited                        -> higher
  * time spent on product/solution pages      -> higher (weighted up)
  * time spent on blog posts                   -> lower  (weighted down)
  * visiting the "Global timing zone" article  -> penalty (low-intent SEO page)
  * a homepage visit under 10s                 -> penalty (bounce)
  * the larger the company                     -> slight penalty (harder to
    locate the relevant buyer inside a big org)

Every weight lives in the config block below so it can be tuned in one place.
"""
import json
import re
from urllib.parse import urlparse

from paths import lead_data

# ---------------------------------------------------------------------------
# Tunable configuration
# ---------------------------------------------------------------------------

# Page taxonomy. Each visited URL is classified into exactly one bucket by
# matching its path against these substring patterns, in order. The first
# bucket whose patterns match wins, so more specific buckets come first.
#
# Patterns reconciled against the live timebeat.app sitemap (pages-sitemap.xml
# + blog-posts-sitemap.xml) on 2026-06-08. If the site adds new product/
# solution sections, extend the "product" tuple here.
PAGE_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    # The "Global timing zone" world-clock article (/post/global-time-zones) —
    # a generic SEO post that signals low purchase intent. Must come BEFORE the
    # blog rule because it lives under /post/.
    ("timing_zone", ("global-time-zone", "global-timing-zone", "global-time-zones")),
    # Contact / demo / quote — the strongest explicit buying signal. Checked
    # early so it wins over any product-page substring.
    ("contact", (
        "contact-us", "/contact", "request-a-demo", "book-a-demo", "request-demo",
        "get-in-touch", "request-a-quote",
    )),
    ("pricing", ("pricing", "/store", "buy", "/quote")),
    # Product / solution / hardware / software / industry / download pages —
    # high intent. Substrings chosen to cover the real site paths.
    ("product", (
        "timebeat-hardware", "white-rabbit", "ocp-tap", "timecard", "appliance",
        "timebeat-software", "timebeat-cloud", "cloud-service",
        "/solutions", "/industries", "/products", "private-5g",
        "open-time-server", "advisory", "sync-insight",
        "/downloads", "download",
    )),
    ("blog", ("/post/", "/blog", "/news", "/learn")),
]

# Per-page-type weights: a flat base awarded for the visit, plus points per
# second of dwell time (capped), so a long product read scores well above a
# quick blog skim.
PAGE_WEIGHTS: dict[str, dict[str, float]] = {
    "contact":     {"base": 15.0, "per_sec": 0.40, "cap_sec": 180},
    "product":     {"base": 10.0, "per_sec": 0.40, "cap_sec": 180},
    "pricing":     {"base": 12.0, "per_sec": 0.40, "cap_sec": 180},
    "homepage":    {"base": 2.0,  "per_sec": 0.10, "cap_sec": 120},
    "blog":        {"base": 3.0,  "per_sec": 0.08, "cap_sec": 120},
    "timing_zone": {"base": -8.0, "per_sec": 0.0,  "cap_sec": 0},
    "other":       {"base": 3.0,  "per_sec": 0.10, "cap_sec": 120},
}

# Extra rule: a homepage visit shorter than this many seconds is a bounce.
HOMEPAGE_BOUNCE_SECONDS = 10
HOMEPAGE_BOUNCE_PENALTY = -5.0

# Company-size penalty. The bigger the company, the harder it is to find the
# relevant buyer, so we shave a few points. Bands are matched against an
# approximate employee count; unknown size applies no penalty.
COMPANY_SIZE_BANDS: list[tuple[int, float]] = [
    (50, 0.0),       # <= 50 employees: no penalty
    (200, -1.0),     # 51 - 200
    (1000, -3.0),    # 201 - 1000
    (5000, -5.0),    # 1001 - 5000
]
COMPANY_SIZE_PENALTY_MAX = -8.0  # 5000+ employees

# Grade thresholds (inclusive lower bounds).
GRADE_THRESHOLDS = [("A", 40.0), ("B", 20.0), ("C", float("-inf"))]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_DWELL_MIN = re.compile(r"(\d+)\s*m", re.IGNORECASE)
_DWELL_SEC = re.compile(r"(\d+)\s*s", re.IGNORECASE)


def _parse_dwell(token: str) -> int:
    """Translate a Leadinfo dwell token ('1m', '45s', '1m 30s') into seconds."""
    token = (token or "").strip()
    seconds = 0
    m = _DWELL_MIN.search(token)
    if m:
        seconds += int(m.group(1)) * 60
    s = _DWELL_SEC.search(token)
    if s:
        seconds += int(s.group(1))
    # Bare number with no unit -> treat as seconds.
    if seconds == 0 and token.isdigit():
        seconds = int(token)
    return seconds


def parse_page_views(text: str | None) -> list[dict]:
    """Extract page views from a pasted Leadinfo block.

    Each visit line looks like:  ``21:52\\thttps://www.timebeat.app/...\\t1m``
    Returns a list of ``{"url": str, "seconds": int}`` in visit order.
    """
    if not text:
        return []
    views: list[dict] = []
    for line in text.splitlines():
        parts = [p.strip() for p in line.split("\t")]
        url = next((p for p in parts if p.startswith("http")), "")
        if not url:
            continue
        idx = parts.index(url)
        dwell = parts[idx + 1] if idx + 1 < len(parts) else ""
        views.append({"url": url, "seconds": _parse_dwell(dwell)})
    return views


def _normalise_path(url: str) -> str:
    path = (urlparse(url).path or "").lower().rstrip("/")
    return path or "/"


def _classify_builtin(url: str) -> str:
    """Classify a URL using the built-in prefix/substring families (no I/O)."""
    path = (urlparse(url).path or "").lower()
    if path in ("", "/"):
        return "homepage"
    for bucket, patterns in PAGE_PATTERNS:
        if any(pat in path for pat in patterns):
            return bucket
    return "other"


# Page-map cache: an explicit {path: category} override written from the live
# sitemap (see sitemap.py). Reloaded when the file's mtime changes. Absent file
# is fine — we simply fall back to the built-in families.
_PAGE_MAP_FILE = lead_data() / "page_map.json"
_page_map_cache: dict = {"mtime": None, "lookup": {}}


def _load_page_map_lookup() -> dict:
    try:
        mtime = _PAGE_MAP_FILE.stat().st_mtime
    except OSError:
        _page_map_cache["mtime"] = None
        _page_map_cache["lookup"] = {}
        return {}
    if mtime != _page_map_cache["mtime"]:
        try:
            data = json.loads(_PAGE_MAP_FILE.read_text())
            raw = data.get("map", {}) if isinstance(data, dict) else {}
            _page_map_cache["lookup"] = {k.rstrip("/") or "/": v for k, v in raw.items()}
            _page_map_cache["mtime"] = mtime
        except Exception:
            _page_map_cache["lookup"] = {}
    return _page_map_cache["lookup"]


def classify_url(url: str) -> str:
    """Classify a visited URL into a page-taxonomy bucket.

    Exact-path overrides from the synced sitemap map win; otherwise fall back to
    the built-in prefix families so scoring works with no cache and no network.
    """
    overrides = _load_page_map_lookup()
    hit = overrides.get(_normalise_path(url))
    if hit:
        return hit
    return _classify_builtin(url)


# ---------------------------------------------------------------------------
# Company size
# ---------------------------------------------------------------------------

def _approx_headcount(company_size: str | None) -> int | None:
    """Best-effort employee count from a free-form size string.

    Accepts bands like '51-200', '1001-5000', '5,000+', '10000', 'Enterprise'.
    Returns None when nothing numeric can be read.
    """
    if not company_size:
        return None
    s = str(company_size).replace(",", "")
    nums = [int(n) for n in re.findall(r"\d+", s)]
    if nums:
        # For a band like '51-200' use the upper bound; for '5000+' use 5000.
        return max(nums)
    label = s.lower()
    if "enterprise" in label:
        return 5000
    if "mid" in label:
        return 500
    if any(w in label for w in ("smb", "small", "startup")):
        return 50
    return None


def _company_size_penalty(company_size: str | None) -> tuple[float, int | None]:
    headcount = _approx_headcount(company_size)
    if headcount is None:
        return 0.0, None
    for upper, penalty in COMPANY_SIZE_BANDS:
        if headcount <= upper:
            return penalty, headcount
    return COMPANY_SIZE_PENALTY_MAX, headcount


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _grade_for(score: float) -> str:
    for grade, lower in GRADE_THRESHOLDS:
        if score >= lower:
            return grade
    return "C"


def score_lead(text: str | None, structured: dict | None = None, analysis: dict | None = None) -> dict:
    """Compute a behavioural lead score.

    Returns:
      {
        "score": int,
        "grade": "A" | "B" | "C",
        "breakdown": [{"label", "points", "detail"}],
        "signals": [str],            # short human-readable flags
        "page_views": [{"url", "seconds", "type"}],
      }
    """
    structured = structured or {}
    analysis = analysis or {}

    views = parse_page_views(text)
    breakdown: list[dict] = []
    signals: list[str] = []
    total = 0.0

    for v in views:
        ptype = classify_url(v["url"])
        v["type"] = ptype
        w = PAGE_WEIGHTS.get(ptype, PAGE_WEIGHTS["other"])
        dwell = min(v["seconds"], int(w["cap_sec"])) if w["cap_sec"] else 0
        pts = w["base"] + dwell * w["per_sec"]
        total += pts
        breakdown.append({
            "label": f"{ptype} page",
            "points": round(pts, 1),
            "detail": f"{v['url']} · {v['seconds']}s",
        })
        if ptype == "contact":
            signals.append("Reached a contact/demo page — explicit buying signal")
        if ptype == "timing_zone":
            signals.append("Visited the Global Timing Zone article (low-intent)")
        if ptype == "homepage" and v["seconds"] < HOMEPAGE_BOUNCE_SECONDS:
            total += HOMEPAGE_BOUNCE_PENALTY
            breakdown.append({
                "label": "homepage bounce",
                "points": round(HOMEPAGE_BOUNCE_PENALTY, 1),
                "detail": f"homepage visit under {HOMEPAGE_BOUNCE_SECONDS}s",
            })
            signals.append(f"Bounced off the homepage in under {HOMEPAGE_BOUNCE_SECONDS}s")

    if views:
        pages_pts = float(len(views))  # +1 per page visited (engagement breadth)
        total += pages_pts
        breakdown.append({
            "label": "pages visited",
            "points": round(pages_pts, 1),
            "detail": f"{len(views)} page(s)",
        })

    company_size = structured.get("company_size") or analysis.get("company_size")
    size_penalty, headcount = _company_size_penalty(company_size)
    if size_penalty:
        total += size_penalty
        breakdown.append({
            "label": "company size",
            "points": round(size_penalty, 1),
            "detail": f"~{headcount} employees — larger org, buyer harder to reach",
        })
        signals.append("Large company — harder to find the right buyer")

    score = int(round(total))
    return {
        "score": score,
        "grade": _grade_for(total),
        "breakdown": breakdown,
        "signals": signals,
        "page_views": views,
    }
