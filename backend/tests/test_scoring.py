"""Tests for the deterministic lead scorer.

Runs under pytest (`python -m pytest backend/tests/test_scoring.py`) or directly
(`python backend/tests/test_scoring.py` from the backend/ directory).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.lead import scoring  # noqa: E402

# Real Leadinfo blocks pulled from production campaigns.
SRR = "Page views\n21:52\thttps://www.timebeat.app/timebeat-hardware/ocp-tap-timecard\t1m\n21:48\thttps://www.timebeat.app/\t45s"
BUFFALO = "Page views\n16:45\thttps://www.timebeat.app/post/the-future-of-precision-timing-exploring-ptp-ntp-grandmaster-clocks\t15s"
NOMURA = "Page views\n08:19\thttps://www.timebeat.app/timebeat-hardware\t1m\n08:18\thttps://www.timebeat.app/white-rabbit-ecosystem\t15s"
GLOBAL_TIMING_ZONE = "Page views\n10:00\thttps://www.timebeat.app/post/global-time-zones\t2m"
HOMEPAGE_BOUNCE = "Page views\n10:00\thttps://www.timebeat.app/\t5s"


def test_parse_dwell_variants():
    assert scoring._parse_dwell("1m") == 60
    assert scoring._parse_dwell("45s") == 45
    assert scoring._parse_dwell("1m 30s") == 90
    assert scoring._parse_dwell("90") == 90


def test_classify_real_urls():
    # Paths verbatim from the live timebeat.app sitemap (2026-06-08).
    product = [
        "https://www.timebeat.app/timebeat-hardware/ocp-tap-timecard",
        "https://www.timebeat.app/timebeat-hardware/open-time-appliance",
        "https://www.timebeat.app/white-rabbit-ecosystem",
        "https://www.timebeat.app/solutions/ptp-squared-mesh",
        "https://www.timebeat.app/solutions-1-1/clock-ensemble",
        "https://www.timebeat.app/industries/finance",
        "https://www.timebeat.app/timebeat-software-3",
        "https://www.timebeat.app/timebeat-advisory-service",
        "https://www.timebeat.app/timebeat-cloud-service",
        "https://www.timebeat.app/timing-for-private-5g",
        "https://www.timebeat.app/downloads-1",
    ]
    for u in product:
        assert scoring.classify_url(u) == "product", u
    assert scoring.classify_url("https://www.timebeat.app/") == "homepage"
    assert scoring.classify_url("https://www.timebeat.app/post/some-article") == "blog"
    # The Global Timing Zone article lives under /post/ but must NOT be a blog.
    assert scoring.classify_url("https://www.timebeat.app/post/global-time-zones") == "timing_zone"


def test_product_dwell_beats_blog_dwell():
    prod = scoring.score_lead("Page views\n10:00\thttps://www.timebeat.app/timebeat-software\t60s")
    blog = scoring.score_lead("Page views\n10:00\thttps://www.timebeat.app/post/some-article\t60s")
    assert prod["score"] > blog["score"]


def test_high_intent_visits_grade_well():
    assert scoring.score_lead(SRR)["grade"] == "A"
    assert scoring.score_lead(NOMURA)["grade"] == "A"


def test_blog_skim_scores_low():
    r = scoring.score_lead(BUFFALO)
    assert r["grade"] == "C"


def test_timing_zone_penalises():
    r = scoring.score_lead(GLOBAL_TIMING_ZONE)
    assert r["score"] < 0
    assert any("Global Timing Zone" in s for s in r["signals"])


def test_homepage_bounce_penalises():
    r = scoring.score_lead(HOMEPAGE_BOUNCE)
    assert r["score"] < 0
    assert any("Bounced" in s for s in r["signals"])


def test_contact_page_is_highest_intent():
    assert scoring.classify_url("https://www.timebeat.app/contact-us") == "contact"
    assert scoring.classify_url("https://www.timebeat.app/request-a-demo") == "contact"
    # A contact visit must score at least as high as the same dwell on a product page.
    contact = scoring.score_lead("Page views\n10:00\thttps://www.timebeat.app/contact-us\t30s")
    product = scoring.score_lead("Page views\n10:00\thttps://www.timebeat.app/timebeat-hardware\t30s")
    assert contact["score"] >= product["score"]
    assert any("contact" in s.lower() for s in contact["signals"])


def test_page_map_override_then_fallback():
    # An exact-path override from the synced sitemap wins over the built-in rule.
    original = scoring._load_page_map_lookup
    try:
        scoring._load_page_map_lookup = lambda: {"/brand-new-section": "product"}
        assert scoring.classify_url("https://www.timebeat.app/brand-new-section") == "product"
    finally:
        scoring._load_page_map_lookup = original
    # With no override, classification falls back to the built-in families.
    assert scoring.classify_url("https://www.timebeat.app/timebeat-hardware") == "product"


def test_larger_company_scores_lower():
    small = scoring.score_lead(NOMURA, {"company_size": "11-50"})["score"]
    mid = scoring.score_lead(NOMURA, {"company_size": "201-500"})["score"]
    large = scoring.score_lead(NOMURA, {"company_size": "10,000+"})["score"]
    assert small > mid > large


def test_unknown_company_size_no_penalty():
    none_size = scoring.score_lead(NOMURA, {})["score"]
    small = scoring.score_lead(NOMURA, {"company_size": "11-50"})["score"]
    assert none_size == small


def test_empty_input_is_zero():
    r = scoring.score_lead(None)
    assert r["score"] == 0
    assert r["page_views"] == []


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
