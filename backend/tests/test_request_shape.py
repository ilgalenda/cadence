"""Request-shape 'golden' tests: assert the kwargs each call site hands to the
Anthropic SDK.

These are the load-bearing characterisation tests for the Owl Core migration.
The SDK boundary is mocked (see conftest.recording_anthropic), so the SAME
assertions run against a call site before it is repointed (hand-rolled kwargs)
and after (Mind-built kwargs). Model IDs are asserted LOOSELY (tier substring)
so the deliberate model-generation upgrade does not break these tests; exact IDs
are pinned separately in test_models_pinned.py.

Sites are added here as they are covered; the pilot (OwlRefiner) lands first.

Stage 3.3 note: `agents/lead` was retired, so the call sites here moved rather than
disappeared — `OwlRefiner` to `agents.sales.refine`, and `pipeline._claude_call`'s
analysis shape to `sales/scoring/agent._analyse_raw`, which is the same request with
the same image handling. Both are **repointed, not dropped**: the shape is still
sent, and the base64 block ordering in particular is the sort of thing that breaks
without any test noticing. The campaign builder's chat shape *is* gone — it had no
successor, which was the point of retiring it.
"""
from agents.mind import blocks as knowledge
from agents.sales.refine import OwlRefiner


SAMPLING_KEYS = ("temperature", "top_p", "top_k", "budget_tokens")


def _no_sampling_params(kwargs):
    for key in SAMPLING_KEYS:
        assert key not in kwargs, f"{key} must not be sent (400 on current models)"


def test_owl_refiner_call_request_shape(monkeypatch, recording_anthropic):
    monkeypatch.setattr(knowledge, "load_vault_for_session", lambda u: "VAULT")

    refiner = OwlRefiner("alice")
    refiner._call("refine this please", max_tokens=2048)

    kwargs = recording_anthropic.only("create")
    assert "sonnet" in kwargs["model"]
    assert kwargs["max_tokens"] == 2048
    # cached persona prefix + uncached per-user tail
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in kwargs["system"][1]
    assert kwargs["messages"] == [{"role": "user", "content": "refine this please"}]
    _no_sampling_params(kwargs)


def test_owl_refiner_fill_uses_smaller_cap(monkeypatch, recording_anthropic):
    monkeypatch.setattr(knowledge, "load_vault_for_session", lambda u: "VAULT")

    refiner = OwlRefiner("alice")
    refiner.fill("subject_line", {"company": "Acme"}, "make it punchy")

    kwargs = recording_anthropic.only("create")
    assert kwargs["max_tokens"] == 512
    assert "sonnet" in kwargs["model"]
    _no_sampling_params(kwargs)


# --- sales/scoring signal analysis (analyze; + base64 image) ---
def test_signal_analysis_request_shape(recording_anthropic):
    from agents.sales import prompts
    from agents.sales.scoring import agent as scoring

    recording_anthropic.create_text = "{}"
    scoring._analyse_raw("generate this", None, None)

    kwargs = recording_anthropic.only("create")
    assert "sonnet" in kwargs["model"]
    assert kwargs["max_tokens"] == 1024
    assert kwargs["system"] == prompts.CLAUDE_BASE_SYSTEM  # uncached analysis-style
    assert kwargs["messages"] == [{"role": "user", "content": "generate this"}]
    _no_sampling_params(kwargs)


def test_signal_analysis_image_block_order(recording_anthropic):
    """The image goes before the text. Reversed, the model describes the prompt."""
    from agents.sales.scoring import agent as scoring

    recording_anthropic.create_text = "{}"
    scoring._analyse_raw("describe", "B64", "image/png")

    content = recording_anthropic.only("create")["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert content[0]["source"]["data"] == "B64"
    assert content[0]["source"]["media_type"] == "image/png"
    assert content[1] == {"type": "text", "text": "describe"}


# --- services/name_sources.WebSearchNameSource.discover (research; web_search) ---
def test_name_source_discover_request_shape(recording_anthropic):
    from agents.services.name_sources import WebSearchNameSource

    recording_anthropic.create_text = "[]"
    WebSearchNameSource().discover("SYSTEM", "find people at Acme")

    kwargs = recording_anthropic.only("create")
    assert "sonnet" in kwargs["model"]
    assert kwargs["max_tokens"] == 16384
    assert kwargs["tool_choice"] == {"type": "auto"}
    assert kwargs["tools"][0]["max_uses"] == 5
    _no_sampling_params(kwargs)

    # Pinned, not incidental: discovery reads names out of raw result snippets,
    # so it must stay on the pre-dynamic-filtering web_search generation. The
    # filtering generation summarises results before the model sees them and
    # spends this same max_uses budget doing it, which measurably collapsed the
    # shortlist. Asserting the exact type is what stops a well-meaning bump to
    # the newest tool version from silently gutting X-ray again.
    assert kwargs["tools"][0]["type"] == "web_search_20250305"


# --- owl correction classifier (classify; Haiku) ---
def test_owl_classify_correction_uses_haiku(recording_anthropic):
    from agents.owl import routes

    recording_anthropic.create_text = '{"is_correction": false}'
    routes._classify_correction("Owl said X", "no, actually it is Y")

    kwargs = recording_anthropic.only("create")
    assert kwargs["model"] == "claude-haiku-4-5"
    assert kwargs["max_tokens"] == 400
    assert "thinking" not in kwargs  # Haiku: no thinking config
    _no_sampling_params(kwargs)
