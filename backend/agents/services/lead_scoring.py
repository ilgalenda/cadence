from __future__ import annotations
"""Lead Scoring capability service — deterministic behavioural lead scoring
from Leadinfo page-visit data. No LLM.

Extracted from ``agents.lead.scoring`` in Phase 2 behind a shim; that shim and the
whole ``agents.lead`` package were deleted in Stage 3.3. The page-taxonomy map it
reads (``page_map.json``) is produced by ``agents.services.sitemap``, which moved
here in the same slice to sit beside its only consumer. The file still lives in the
``lead/`` data directory: the package moved, the snapshot did not (see ``paths.py``).

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

from paths import sales_data

# ---------------------------------------------------------------------------
# Tunable configuration
# ---------------------------------------------------------------------------

# Page taxonomy. Each visited URL is classified into exactly one bucket by
# matching its path against these substring patterns, in order. The first
# bucket whose patterns match wins, so more specific buckets come first.
#
# Patterns reconciled against the rebuilt live acme.example sitemap on
# 2026-07-27 (the site was restructured: blog moved /post/* -> /blog/*, clean
# /hardware//software//solutions paths, and new /case-studies, /learn,
# /community and /tools sections). Legacy Wix-era substrings are retained so
# historical Leadinfo blocks (which still carry old URLs) keep classifying.
#
# Order matters — first matching bucket wins, so the more specific / higher-
# intent buckets come first, and /community (docs) sits before /product because
# doc paths embed product names (e.g. /community/open-time-appliance).
PAGE_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    # The "Global timing zone" world-clock article — a generic SEO post that
    # signals low purchase intent. Lives under /blog/ now (was /post/); must
    # come BEFORE the blog rule either way.
    ("timing_zone", ("global-time-zone", "global-timing-zone", "global-time-zones")),
    # Contact / demo / quote / book-a-call — the strongest explicit buying
    # signal. Checked early so it wins over any product-page substring.
    ("contact", (
        "book-a-call", "contact-us", "/contact", "request-a-demo", "book-a-demo",
        "request-demo", "get-in-touch", "request-a-quote",
    )),
    # Pricing / ROI tooling — the cost-of-drift calculator is a strong intent
    # signal, on a par with a pricing page.
    ("pricing", ("pricing", "/store", "/quote", "cost-of-drift", "/tools/")),
    # Case studies — proof content read mid-funnel while evaluating.
    ("case_studies", ("/case-studies", "/case-study")),
    # Community / platform documentation — existing-customer support browsing,
    # near-zero buying intent. BEFORE product: doc paths embed product names.
    ("docs", ("/community",)),
    # Product / solution / hardware / software / industry / download pages —
    # high intent. Substrings cover the rebuilt paths plus legacy Wix ones.
    ("product", (
        "/hardware", "/software", "/solutions", "/industries", "/products",
        "fleet-insight", "acme-agent", "ptp-feed", "white-rabbit",
        "open-time", "timecard", "appliance", "ocp-tap", "private-5g", "advisory",
        "/downloads", "download",
        # legacy Wix-era paths still present in historical Leadinfo data
        "acme-hardware", "acme-software", "acme-cloud", "cloud-service",
    )),
    # Learn — product-adjacent education, a notch above the blog.
    ("learn", ("/learn",)),
    ("blog", ("/blog", "/post/", "/news")),
]

# ── The four components ─────────────────────────────────────────────────────
# The score is out of 100 by construction: four independently capped components
# that sum to it. That is a deliberate choice over mapping an unbounded running
# total onto 0-100 with a curve — a curve spreads the range just as well, but the
# breakdown would no longer add up to the headline, and this scorer exists to be
# inspectable. A number you can audit is worth more than a number that is smooth.
#
# The previous model was an open-ended sum dominated by dwell time: three minutes
# on one page was worth 72 points, more than any page's own value, so a long
# skim outscored reaching the pricing page and grade A covered everything from 42
# to 350-odd. Every component below is bounded for that reason.

SCORE_MAX = 100.0

# Intent — what they reached (0-45). Set by the single highest-intent page
# touched rather than accumulated: reaching the contact page is a step change in
# what a visitor is telling you, not an increment on top of reading two more.
INTENT_CEILING = 45.0
INTENT_BY_TYPE: dict[str, float] = {
    "contact":      45.0,
    "pricing":      38.0,
    "product":      28.0,
    "case_studies": 20.0,
    "learn":        10.0,
    "blog":          4.0,
    "other":         4.0,
    "docs":          2.0,   # existing-customer support browsing
    "homepage":      2.0,
    "timing_zone":   0.0,   # the generic SEO world-clock article
}

# Depth — time spent on the pages that matter (0-30). Saturating, so dwell can
# never again outweigh what was actually visited: 150s earns half the ceiling,
# 600s earns four fifths, and no session earns all of it.
DEPTH_CEILING = 30.0
DEPTH_HALF_AT_SECONDS = 150.0

#: The page types depth and breadth count. Reading the blog for an hour is not
#: engagement with the product.
QUALIFIED_TYPES = ("contact", "pricing", "product", "case_studies")

# Breadth — how much of the product they explored (0-15).
BREADTH_CEILING = 15.0
BREADTH_PER_PAGE = 5.0

# Friction — what argues against the lead (floored at -15, so no single session
# can be penalised into meaninglessness).
FRICTION_FLOOR = -15.0

# A homepage visit shorter than this many seconds is a bounce.
HOMEPAGE_BOUNCE_SECONDS = 10
HOMEPAGE_BOUNCE_PENALTY = -5.0

# The "Global timing zone" world-clock article: read on its own it is a signal
# the visitor wanted a clock, not a grandmaster.
TIMING_ZONE_PENALTY = -10.0

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

# Grade thresholds (inclusive lower bounds), against the 0-100 scale.
#
# Calibrated 2026-08-20 against every real Leadinfo block held at the time — the
# five production fixtures in `tests/test_scoring.py` and four blocks in
# `campaigns.json`. Nine sessions, and **not one had ever reached pricing or
# contact**, so a threshold gating A behind explicit buying intent would never
# have fired. A at 55 is reachable on product interest alone when the dwell and
# the breadth are genuinely there (28 + 15 + 15 = 58) and out of reach for a
# skim. Nine sessions is a small sample and these numbers are provisional; every
# score is now persisted (`agents.sales.store.scores`) so the next pass can be
# fitted to a distribution rather than argued.
#
# Three grades, deliberately, so the computed grade lines up one-to-one with the
# model's own Hot/Warm/Cold read. When the two disagree, that is worth seeing.
GRADE_THRESHOLDS = [("A", 55.0), ("B", 30.0), ("C", float("-inf"))]


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

    Each visit line looks like:  ``21:52\\thttps://www.acme.example/...\\t1m``
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
_PAGE_MAP_FILE = sales_data() / "page_map.json"
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


def thresholds() -> list[dict]:
    """The grade bands, for a surface that would otherwise hard-code them.

    A score with no stated scale is a number nobody can act on, and a frontend
    carrying its own copy of 55 and 30 is a silent drift waiting to happen.
    """
    return [
        {"grade": grade, "min": None if lower == float("-inf") else lower}
        for grade, lower in GRADE_THRESHOLDS
    ]


#: What each component is looking for, in the words a surface can show. Kept
#: beside the ceilings rather than in the page, so a surface explaining the model
#: and a surface showing a result cannot describe two different models.
COMPONENT_DESCRIPTIONS: list[tuple[str, float, str]] = [
    ("Intent", INTENT_CEILING, "the highest-intent page they reached"),
    ("Depth", DEPTH_CEILING, "time spent on the pages that matter"),
    ("Breadth", BREADTH_CEILING, "how much of the product they explored"),
    ("Friction", FRICTION_FLOOR, "company size, a bounce, a low-intent read"),
]


def scale() -> dict:
    """The shape of the model: what it measures, out of what, and where a grade begins.

    Exists so a surface can explain the scoring before anyone has scored anything,
    without carrying its own copy of the ceilings — the duplication that made the
    old thresholds impossible to change in one place.
    """
    return {
        "max_score": int(SCORE_MAX),
        "components": [
            {"label": label, "max": ceiling, "detail": detail}
            for label, ceiling, detail in COMPONENT_DESCRIPTIONS
        ],
        "thresholds": thresholds(),
    }


def _intent(views: list[dict]) -> tuple[float, str]:
    """The highest intent any single visited page implies, and which page it was."""
    best_points, best_type = 0.0, ""
    for view in views:
        points = INTENT_BY_TYPE.get(view["type"], INTENT_BY_TYPE["other"])
        if points > best_points:
            best_points, best_type = points, view["type"]
    return best_points, best_type


def _depth(views: list[dict]) -> tuple[float, int]:
    """Time spent on pages that matter, saturating towards the ceiling."""
    seconds = sum(v["seconds"] for v in views if v["type"] in QUALIFIED_TYPES)
    if not seconds:
        return 0.0, 0
    return DEPTH_CEILING * seconds / (seconds + DEPTH_HALF_AT_SECONDS), seconds


def _breadth(views: list[dict]) -> tuple[float, int]:
    """How many distinct pages that matter were opened."""
    pages = len({v["url"] for v in views if v["type"] in QUALIFIED_TYPES})
    return min(BREADTH_CEILING, BREADTH_PER_PAGE * pages), pages


def _friction(views: list[dict], company_size: str | None) -> tuple[float, list[str], list[str]]:
    """What argues against the lead: its points, the reasons, and the signals raised."""
    points, reasons, signals = 0.0, [], []

    penalty, headcount = _company_size_penalty(company_size)
    if penalty:
        points += penalty
        reasons.append(f"~{headcount} employees")
        signals.append("Large company — harder to find the right buyer")

    for view in views:
        if view["type"] == "homepage" and view["seconds"] < HOMEPAGE_BOUNCE_SECONDS:
            points += HOMEPAGE_BOUNCE_PENALTY
            reasons.append(f"homepage bounce under {HOMEPAGE_BOUNCE_SECONDS}s")
            signals.append(f"Bounced off the homepage in under {HOMEPAGE_BOUNCE_SECONDS}s")
        if view["type"] == "timing_zone":
            points += TIMING_ZONE_PENALTY
            reasons.append("read the world-clock article")
            signals.append("Visited the Global Timing Zone article (low-intent)")

    return max(FRICTION_FLOOR, points), reasons, signals


#: What reaching each page type is worth saying out loud. Only the types that
#: carry a real message; the rest are visible in the breakdown.
_INTENT_SIGNALS: dict[str, str] = {
    "contact": "Reached a contact/demo page — explicit buying signal",
    "pricing": "Used pricing / the cost-of-drift ROI tool — strong buying signal",
    "case_studies": "Read a case study — mid-funnel evaluation",
}


def score_lead(text: str | None, structured: dict | None = None, analysis: dict | None = None) -> dict:
    """Compute a behavioural lead score, out of 100.

    Four capped components — what they reached, how long they stayed on what
    matters, how much they explored, and what argues against them — summing to a
    score the breakdown genuinely adds up to.

    Returns:
      {
        "score": int,                # 0-100
        "max_score": 100,
        "grade": "A" | "B" | "C",
        "thresholds": [{"grade", "min"}],
        "breakdown": [{"label", "points", "max", "detail"}],
        "signals": [str],            # short human-readable flags
        "page_views": [{"url", "seconds", "type"}],
      }
    """
    structured = structured or {}
    analysis = analysis or {}

    views = parse_page_views(text)
    for view in views:
        view["type"] = classify_url(view["url"])

    intent, intent_type = _intent(views)
    depth, qualified_seconds = _depth(views)
    breadth, qualified_pages = _breadth(views)
    friction, friction_reasons, signals = _friction(
        views, structured.get("company_size") or analysis.get("company_size"))

    if intent_type in _INTENT_SIGNALS:
        signals.insert(0, _INTENT_SIGNALS[intent_type])

    breakdown = [
        {
            "label": "Intent",
            "points": round(intent, 1),
            "max": INTENT_CEILING,
            "detail": (f"reached a {intent_type.replace('_', ' ')} page" if intent_type
                       else "no recognisable page visits"),
        },
        {
            "label": "Depth",
            "points": round(depth, 1),
            "max": DEPTH_CEILING,
            "detail": f"{qualified_seconds}s on pages that matter",
        },
        {
            "label": "Breadth",
            "points": round(breadth, 1),
            "max": BREADTH_CEILING,
            "detail": f"{qualified_pages} page(s) of real interest",
        },
    ]
    # Friction only earns a row when there is some — a nil penalty stated every
    # time trains you to stop reading the column.
    if friction:
        breakdown.append({
            "label": "Friction",
            "points": round(friction, 1),
            "max": FRICTION_FLOOR,
            "detail": " · ".join(friction_reasons),
        })

    total = max(0.0, min(SCORE_MAX, intent + depth + breadth + friction))
    return {
        "score": int(round(total)),
        "max_score": int(SCORE_MAX),
        "grade": _grade_for(total),
        "thresholds": thresholds(),
        "breakdown": breakdown,
        "signals": signals,
        "page_views": views,
    }
