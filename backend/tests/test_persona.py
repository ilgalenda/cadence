"""Lock the shared Persona contracts (Phase 1)."""
from agents.mind import persona


def test_core_is_universal_and_has_no_conversational_directives():
    core = persona.OWL_PERSONA_CORE
    assert "You are Owl" in core
    assert "three pillars" in core
    # The calibrated reply-style / partner stance must NOT be in the universal
    # core — it would leak into compose/analyze JSON output.
    assert "want me to expand" not in core.lower()
    assert "yes-man" not in core.lower()


def test_chat_stance_holds_the_reply_style():
    stance = persona.CHAT_STANCE.lower()
    assert "yes-man" in stance
    assert "lead with the direct answer" in stance
    assert "want me to expand" in stance  # the anti-pattern it forbids


def test_system_blocks_cached_prefix_structure():
    blocks = persona.system_blocks(
        role_overlay="ROLE-OVERLAY",
        vault_knowledge="VAULT-BODY",
        tail="TAIL",
        cache=True,
    )
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    prefix = blocks[0]["text"]
    assert "You are Owl" in prefix
    assert "ROLE-OVERLAY" in prefix
    assert prefix.index(persona.KNOWLEDGE_INTRO) < prefix.index("VAULT-BODY")  # intro before vault
    assert "cache_control" not in blocks[1]
    assert blocks[1]["text"] == "TAIL"


def test_memory_lives_in_tail_and_prefix_stays_byte_stable():
    base = persona.system_blocks(role_overlay="R", vault_knowledge="V", tail="TAIL")
    withmem = persona.system_blocks(
        role_overlay="R", vault_knowledge="V", tail="TAIL", memory_block="MEMORY-XYZ"
    )
    # Changing memory must NOT change the cached block-0 prefix.
    assert base[0]["text"] == withmem[0]["text"]
    # Memory rides the uncached tail.
    assert "MEMORY-XYZ" in withmem[1]["text"]
    assert "cache_control" not in withmem[1]


def test_cache_false_drops_the_breakpoint():
    blocks = persona.system_blocks(vault_knowledge="V", tail="T", cache=False)
    assert "cache_control" not in blocks[0]
