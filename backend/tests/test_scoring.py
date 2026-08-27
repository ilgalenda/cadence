"""Tests for the deterministic lead scorer.

Runs under pytest (`python -m pytest backend/tests/test_scoring.py`) or directly
(`python backend/tests/test_scoring.py` from the backend/ directory).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.services import lead_scoring as scoring  # noqa: E402

# Real Leadinfo blocks pulled from production campaigns.
SRR = "Page views\n21:52\thttps://www.acme.example/acme-hardware/ocp-tap-timecard\t1m\n21:48\thttps://www.acme.example/\t45s"
BUFFALO = "Page views\n16:45\thttps://www.acme.example/post/the-future-of-precision-timing-exploring-ptp-ntp-grandmaster-clocks\t15s"
NOMURA = "Page views\n08:19\thttps://www.acme.example/acme-hardware\t1m\n08:18\thttps://www.acme.example/white-rabbit-ecosystem\t15s"
GLOBAL_TIMING_ZONE = "Page views\n10:00\thttps://www.acme.example/post/global-time-zones\t2m"
HOMEPAGE_BOUNCE = "Page views\n10:00\thttps://www.acme.example/\t5s"


def test_parse_dwell_variants():
    assert scoring._parse_dwell("1m") == 60
    assert scoring._parse_dwell("45s") == 45
    assert scoring._parse_dwell("1m 30s") == 90
    assert scoring._parse_dwell("90") == 90


def test_classify_new_site_urls():
    # Paths verbatim from the rebuilt live acme.example sitemap (2026-07-27).
    product = [
        "https://www.acme.example/hardware",
        "https://www.acme.example/hardware/open-timecard",
        "https://www.acme.example/hardware/open-time-node-wr",
        "https://www.acme.example/software",
        "https://www.acme.example/solutions/vgmc",
        "https://www.acme.example/industries/private-5g",
        "https://www.acme.example/sync-insight",
        "https://www.acme.example/acme-agent",
        "https://www.acme.example/ptp-feed",
        "https://www.acme.example/white-rabbit",
        "https://www.acme.example/downloads/software",
    ]
    for u in product:
        assert scoring.classify_url(u) == "product", u
    # New high-intent signals that were unclassified on the old taxonomy.
    assert scoring.classify_url("https://www.acme.example/book-a-call") == "contact"
    assert scoring.classify_url("https://www.acme.example/contact") == "contact"
    assert scoring.classify_url("https://www.acme.example/tools/cost-of-drift") == "pricing"
    # New sections.
    assert scoring.classify_url("https://www.acme.example/case-studies/power-industry") == "case_studies"
    assert scoring.classify_url("https://www.acme.example/learn/ptp-grandmaster-clock") == "learn"
    # Community platform docs — existing-customer browsing, near-zero intent —
    # must NOT be mistaken for product even though the path embeds a product name.
    assert scoring.classify_url("https://www.acme.example/community/open-time-appliance/installation") == "docs"
    assert scoring.classify_url("https://www.acme.example/community/platform/install-acme") == "docs"
    # Blog moved /post/* -> /blog/*.
    assert scoring.classify_url("https://www.acme.example/blog/ptp-vs-ntp") == "blog"
    assert scoring.classify_url("https://www.acme.example/blog/global-time-zones") == "timing_zone"
    assert scoring.classify_url("https://www.acme.example/") == "homepage"


def test_classify_legacy_urls_still_work():
    # Historical Leadinfo blocks still carry old Wix-era URLs; they must keep
    # classifying so already-stored leads score consistently.
    legacy_product = [
        "https://www.acme.example/acme-hardware/ocp-tap-timecard",
        "https://www.acme.example/acme-hardware/open-time-appliance",
        "https://www.acme.example/white-rabbit-ecosystem",
        "https://www.acme.example/solutions-1-1/clock-ensemble",
        "https://www.acme.example/acme-software-3",
        "https://www.acme.example/acme-advisory-service",
        "https://www.acme.example/acme-cloud-service",
        "https://www.acme.example/timing-for-private-5g",
        "https://www.acme.example/downloads-1",
    ]
    for u in legacy_product:
        assert scoring.classify_url(u) == "product", u
    assert scoring.classify_url("https://www.acme.example/post/some-article") == "blog"
    assert scoring.classify_url("https://www.acme.example/post/global-time-zones") == "timing_zone"
    assert scoring.classify_url("https://www.acme.example/contact-us") == "contact"


def test_product_dwell_beats_blog_dwell():
    prod = scoring.score_lead("Page views\n10:00\thttps://www.acme.example/acme-software\t60s")
    blog = scoring.score_lead("Page views\n10:00\thttps://www.acme.example/post/some-article\t60s")
    assert prod["score"] > blog["score"]


def _score_one(url: str, dwell: str = "60s") -> int:
    return scoring.score_lead(f"Page views\n10:00\t{url}\t{dwell}")["score"]


def test_new_bucket_intent_ordering():
    base = "https://www.acme.example"
    # product > case_studies > learn > blog, at equal dwell.
    product = _score_one(f"{base}/hardware")
    case = _score_one(f"{base}/case-studies/power-industry")
    learn = _score_one(f"{base}/learn/ptp-grandmaster-clock")
    blog = _score_one(f"{base}/blog/ptp-vs-ntp")
    assert product > case > learn > blog


def test_pricing_tool_is_high_intent():
    base = "https://www.acme.example"
    pricing = _score_one(f"{base}/tools/cost-of-drift")
    product = _score_one(f"{base}/hardware")
    assert pricing >= product
    signals = scoring.score_lead(f"Page views\n10:00\t{base}/tools/cost-of-drift\t60s")["signals"]
    assert any("cost-of-drift" in s or "buying signal" in s for s in signals)


def test_community_docs_are_near_zero():
    base = "https://www.acme.example"
    # A deep dwell on support docs must stay near zero — existing customers
    # reading platform docs are not a buying signal.
    docs = _score_one(f"{base}/community/platform/gnss-receiver-tuning", "180s")
    blog = _score_one(f"{base}/blog/ptp-vs-ntp", "60s")
    assert docs < blog
    assert docs < 5


def test_real_product_interest_grades_b():
    # Both are a product page for about a minute plus one shallow second page.
    # Under the old unbounded scale these were A, which is what made A meaningless:
    # it also covered a session that reached contact and pricing for three minutes
    # each. Real interest, not an explicit buying signal.
    assert scoring.score_lead(SRR)["grade"] == "B"
    assert scoring.score_lead(NOMURA)["grade"] == "B"


def test_reaching_pricing_grades_a():
    base = "https://www.acme.example"
    strong = scoring.score_lead(
        f"Page views\n10:00\t{base}/pricing\t45s"
        f"\n10:01\t{base}/hardware/open-time-server\t2m 10s"
        f"\n10:02\t{base}/case-studies\t30s"
    )
    assert strong["grade"] == "A"


def test_blog_skim_scores_low():
    r = scoring.score_lead(BUFFALO)
    assert r["grade"] == "C"


def test_timing_zone_penalises():
    # The scale floors at zero — a penalty cannot drive a lead below "nothing".
    r = scoring.score_lead(GLOBAL_TIMING_ZONE)
    assert r["score"] == 0
    assert any("Global Timing Zone" in s for s in r["signals"])


def test_homepage_bounce_penalises():
    r = scoring.score_lead(HOMEPAGE_BOUNCE)
    assert r["score"] == 0
    assert any("Bounced" in s for s in r["signals"])


def test_contact_page_is_highest_intent():
    assert scoring.classify_url("https://www.acme.example/contact-us") == "contact"
    assert scoring.classify_url("https://www.acme.example/contact") == "contact"
    assert scoring.classify_url("https://www.acme.example/book-a-call") == "contact"
    assert scoring.classify_url("https://www.acme.example/request-a-demo") == "contact"
    # A contact visit must score at least as high as the same dwell on a product page.
    contact = scoring.score_lead("Page views\n10:00\thttps://www.acme.example/contact-us\t30s")
    product = scoring.score_lead("Page views\n10:00\thttps://www.acme.example/acme-hardware\t30s")
    assert contact["score"] >= product["score"]
    assert any("contact" in s.lower() for s in contact["signals"])


def test_page_map_override_then_fallback():
    # An exact-path override from the synced sitemap wins over the built-in rule.
    original = scoring._load_page_map_lookup
    try:
        scoring._load_page_map_lookup = lambda: {"/brand-new-section": "product"}
        assert scoring.classify_url("https://www.acme.example/brand-new-section") == "product"
    finally:
        scoring._load_page_map_lookup = original
    # With no override, classification falls back to the built-in families.
    assert scoring.classify_url("https://www.acme.example/acme-hardware") == "product"


def test_larger_company_scores_lower():
    small = scoring.score_lead(NOMURA, {"company_size": "11-50"})["score"]
    mid = scoring.score_lead(NOMURA, {"company_size": "201-500"})["score"]
    large = scoring.score_lead(NOMURA, {"company_size": "10,000+"})["score"]
    assert small > mid > large


def test_unknown_company_size_no_penalty():
    none_size = scoring.score_lead(NOMURA, {})["score"]
    small = scoring.score_lead(NOMURA, {"company_size": "11-50"})["score"]
    assert none_size == small


# ── The 0-100 contract ──────────────────────────────────────────────────────
# The score is out of 100 by construction rather than by clamping a running total,
# and the page shows the breakdown as the reason for the number. Both of those are
# promises, so both are pinned here.

def test_score_never_leaves_the_scale():
    base = "https://www.acme.example"
    everything = "Page views\n" + "\n".join(
        f"10:0{i}\t{base}{path}\t3m" for i, path in enumerate(
            ["/contact", "/pricing", "/hardware", "/case-studies", "/learn/x", "/blog/y"])
    )
    r = scoring.score_lead(everything)
    assert 0 <= r["score"] <= r["max_score"] == 100
    # And the ceiling is not reached by brute force: a saturating model means more
    # pages and more minutes cannot buy the last of the scale.
    assert r["score"] < 100


def test_the_breakdown_adds_up_to_the_score():
    # The whole reason for capped components over a curve. If these drift apart the
    # page is showing a reason that does not produce its own number.
    base = "https://www.acme.example"
    r = scoring.score_lead(
        f"Page views\n10:00\t{base}/pricing\t45s\n10:01\t{base}/hardware\t90s\n10:02\t{base}/\t5s",
        {"company_size": "1001-5000"},
    )
    assert round(sum(part["points"] for part in r["breakdown"])) == r["score"]


def test_every_component_states_its_ceiling():
    r = scoring.score_lead(f"Page views\n10:00\thttps://www.acme.example/pricing\t45s")
    assert [part["label"] for part in r["breakdown"]] == ["Intent", "Depth", "Breadth"]
    assert all("max" in part for part in r["breakdown"])
    # Friction earns a row only when there is some to report.
    bounced = scoring.score_lead("Page views\n10:00\thttps://www.acme.example/\t5s")
    assert [part["label"] for part in bounced["breakdown"]][-1] == "Friction"


def test_the_scale_describes_the_same_model_the_score_uses():
    # The landing screen explains the scoring before anything has been scored. It
    # reads this, so the two must not be able to describe different models.
    shape = scoring.scale()
    ceilings = {c["label"]: c["max"] for c in shape["components"]}

    assert shape["max_score"] == 100
    assert ceilings == {
        "Intent": scoring.INTENT_CEILING,
        "Depth": scoring.DEPTH_CEILING,
        "Breadth": scoring.BREADTH_CEILING,
        "Friction": scoring.FRICTION_FLOOR,
    }
    # The three earning components total 90, not 100 — the scale keeps headroom,
    # and depth saturates so even 90 is asymptotic. A perfect session lands in the
    # high eighties. Pinned because it is a property worth noticing if a ceiling
    # ever moves, not an accident.
    assert sum(v for v in ceilings.values() if v > 0) == 90
    assert shape["thresholds"] == scoring.score_lead(NOMURA)["thresholds"]
    assert all(c["detail"] for c in shape["components"])


def test_thresholds_travel_with_the_score():
    # So no surface has to carry its own copy of where a grade begins.
    r = scoring.score_lead(NOMURA)
    bands = {b["grade"]: b["min"] for b in r["thresholds"]}
    assert bands["A"] == 55.0 and bands["B"] == 30.0
    assert bands["C"] is None


def test_dwell_cannot_outrank_what_was_reached():
    # The failure the component model exists to prevent: under the old additive
    # scale, three minutes on a blog post beat reaching the pricing page.
    base = "https://www.acme.example"
    long_blog = scoring.score_lead(f"Page views\n10:00\t{base}/blog/ptp-vs-ntp\t10m")
    brief_pricing = scoring.score_lead(f"Page views\n10:00\t{base}/pricing\t20s")
    assert brief_pricing["score"] > long_blog["score"]


def test_empty_input_is_zero():
    r = scoring.score_lead(None)
    assert r["score"] == 0
    assert r["page_views"] == []


# The `agents.lead.scoring` shim this file used to test was deleted with the rest
# of that package in Stage 3.3. `agents.services.lead_scoring` — which every test
# above already exercises directly — is now the only way in.


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
