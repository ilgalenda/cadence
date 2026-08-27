"""Lock the prompt-cache discipline of Owl's system blocks.

The cache breakpoint must sit on block 0 (persona + vault) only; the per-user
identity tail must carry no cache_control so it never invalidates the cached
prefix. Byte-stability of the prefix across calls is what keeps cache reads
working — an accidental edit or reorder would silently kill the cache.
"""
from agents.mind import blocks as knowledge


def _stub_vault(monkeypatch, text="VAULT-KNOWLEDGE"):
    monkeypatch.setattr(knowledge, "load_vault_for_session", lambda username: text)


def test_owl_blocks_have_single_cache_breakpoint_on_block0(monkeypatch):
    _stub_vault(monkeypatch)
    blocks = knowledge.owl_system_blocks("alice")
    assert len(blocks) == 2
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in blocks[1]


def test_owl_identity_tail_is_after_the_breakpoint(monkeypatch):
    _stub_vault(monkeypatch)
    blocks = knowledge.owl_system_blocks("alice")
    # The volatile per-user string is in the tail block, not the cached prefix.
    assert "alice" in blocks[1]["text"]
    assert "alice" not in blocks[0]["text"]


def test_cached_prefix_is_byte_stable_across_users(monkeypatch):
    _stub_vault(monkeypatch)
    a = knowledge.owl_system_blocks("alice")[0]["text"]
    b = knowledge.owl_system_blocks("bob")[0]["text"]
    assert a == b  # prefix must not depend on the user, or the cache never hits
