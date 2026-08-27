from __future__ import annotations
"""Keep the lead-scoring website map in step with the live acme.example site.

`lead_scoring.py` grades a visitor's page path against a map of the acme.example
site. This module fetches the live sitemap, pre-classifies every real path with the
built-in families, and writes an explicit {path: category} override to
``page_map.json`` so brand-new pages are picked up automatically.

Scoring itself never touches the network — it only reads ``page_map.json`` if
present. Refreshing is done here, triggered lazily (TTL) or on request.

Moved here from ``agents/lead`` in Stage 3.3, when that package was retired. It
belongs beside ``lead_scoring``, its only consumer: the two are one capability
split across a network half and an offline half.
"""
import json
import re
import threading
import time
from datetime import datetime, timezone

import httpx

from agents.services import lead_scoring as scoring
from paths import sales_data

SITEMAP_INDEX_URL = "https://www.acme.example/sitemap.xml"
PAGE_MAP_FILE = sales_data() / "page_map.json"
REFRESH_TTL_SECONDS = 24 * 60 * 60  # 24h

# Live "other"-classified paths that are expected company/legal/utility pages —
# excluded from the unmapped review list to keep the signal high.
_EXPECTED_OTHER = (
    "about", "partner", "authors", "team", "research", "community-guidelines",
    "conditions-of-sale", "terms", "privacy", "cookie", "careers", "press",
    "legal", "blank", "/test",
)

_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)
_refresh_lock = threading.Lock()


def _fetch_text(client: httpx.Client, url: str) -> str:
    resp = client.get(url, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


def _extract_locs(xml_text: str) -> list[str]:
    return [m.strip() for m in _LOC_RE.findall(xml_text or "")]


def _collect_page_urls(client: httpx.Client) -> list[str]:
    """Walk the sitemap index → sub-sitemaps → page URLs."""
    index_text = _fetch_text(client, SITEMAP_INDEX_URL)
    locs = _extract_locs(index_text)
    sub_sitemaps = [u for u in locs if u.lower().endswith(".xml")]
    if not sub_sitemaps:
        # Not an index — it was already a flat sitemap of page URLs.
        return locs
    urls: list[str] = []
    for sm in sub_sitemaps:
        try:
            urls.extend(_extract_locs(_fetch_text(client, sm)))
        except Exception as e:
            print(f"[services.sitemap] sub-sitemap fetch failed {sm}: {e}")
    return urls


def refresh_page_map() -> dict:
    """Fetch the live sitemap, rebuild page_map.json. Returns a summary dict.

    Serialised by a lock so concurrent triggers don't stampede the site.
    """
    with _refresh_lock:
        with httpx.Client(timeout=20, headers={"User-Agent": "Cadence-LeadScorer/1.0"}) as client:
            urls = _collect_page_urls(client)

        page_map: dict[str, str] = {}
        unmapped: list[str] = []
        for url in urls:
            path = scoring._normalise_path(url)
            if path == "/":
                page_map[path] = "homepage"
                continue
            category = scoring._classify_builtin(url)
            page_map[path] = category
            if category == "other" and not any(tok in path for tok in _EXPECTED_OTHER):
                unmapped.append(path)

        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": SITEMAP_INDEX_URL,
            "count": len(page_map),
            "map": page_map,
            "unmapped": sorted(set(unmapped)),
        }
        PAGE_MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
        PAGE_MAP_FILE.write_text(json.dumps(payload, indent=2))
        return payload


def load_page_map() -> dict | None:
    """Return the current page_map.json payload, or None if not yet built."""
    if not PAGE_MAP_FILE.exists():
        return None
    try:
        return json.loads(PAGE_MAP_FILE.read_text())
    except Exception:
        return None


def _is_stale() -> bool:
    try:
        age = time.time() - PAGE_MAP_FILE.stat().st_mtime
        return age > REFRESH_TTL_SECONDS
    except OSError:
        return True  # missing -> stale


def maybe_refresh_page_map() -> None:
    """If the map is missing or older than the TTL, refresh in the background.

    Never blocks the caller; scoring keeps using the existing cache (or built-in
    families) until the refresh lands.
    """
    if not _is_stale():
        return
    if _refresh_lock.locked():
        return

    def _run():
        try:
            refresh_page_map()
        except Exception as e:
            print(f"[services.sitemap] background refresh failed: {e}")

    threading.Thread(target=_run, daemon=True).start()
