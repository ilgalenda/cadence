"""The Owl tool registry — the seam that makes every sales agent conversational.

What matters here is that the two paths to an agent cannot diverge: a tool Owl
can call always has something able to run it, the roster the API reports is the
roster Owl is given, and a failing agent degrades to a sentence rather than
killing the turn mid-stream.
"""
import pytest

from agents.sales import tools


@pytest.fixture(autouse=True)
def empty_registry():
    """Registration is import-time in the app; tests get a clean registry."""
    tools.reset_for_tests()
    yield
    tools.reset_for_tests()


def _tool(name="xray", writes=False, run=None):
    return tools.SalesTool(
        name=name,
        description=f"Run {name}.",
        input_schema={"type": "object", "properties": {"company": {"type": "string"}}},
        run=run or (lambda username, args: f"{name} ran for {username} with {args}"),
        writes=writes,
    )


# ── Registration ────────────────────────────────────────────────────────────

def test_registry_starts_empty_so_owl_gets_no_tools():
    assert tools.names() == []
    assert tools.specs() == []


def test_register_exposes_the_tool_to_owl():
    tools.register(_tool("xray"))
    assert tools.names() == ["xray"]
    assert tools.specs() == [{
        "name": "xray",
        "description": "Run xray.",
        "input_schema": {"type": "object", "properties": {"company": {"type": "string"}}},
    }]


def test_registering_the_same_name_twice_is_an_error():
    tools.register(_tool("xray"))
    with pytest.raises(ValueError, match="already registered"):
        tools.register(_tool("xray"))


def test_specs_are_ordered_by_name_so_the_prompt_prefix_stays_stable():
    for name in ("research", "xray", "composer"):
        tools.register(_tool(name))
    assert [s["name"] for s in tools.specs()] == ["composer", "research", "xray"]


def test_a_spec_carries_only_what_the_model_needs():
    tools.register(_tool("xray", writes=True))
    assert set(tools.specs()[0]) == {"name", "description", "input_schema"}, \
        "writes is a platform concern, not something the model is told"


# ── Dispatch ────────────────────────────────────────────────────────────────

def test_dispatch_runs_the_registered_agent_with_the_calling_user():
    seen = {}
    tools.register(_tool("xray", run=lambda username, args: seen.update(u=username, a=args) or "done"))
    assert tools.dispatch("alice", "xray", {"company": "Northgate"}) == "done"
    assert seen == {"u": "alice", "a": {"company": "Northgate"}}


def test_dispatch_of_an_unknown_tool_answers_rather_than_raising():
    result = tools.dispatch("alice", "nope", {})
    assert "nope" in result
    assert "available" in result


def test_a_failing_agent_degrades_to_a_sentence(capsys):
    """An exception escaping into the streaming loop would strand the turn with
    no explanation, so a failure comes back as text the model can relay."""
    def explode(username, args):
        raise RuntimeError("Lusha is out of credits")

    tools.register(_tool("enrichment", run=explode))
    result = tools.dispatch("alice", "enrichment", {})
    assert "enrichment" in result
    assert "Lusha is out of credits" in result
    assert "sales.tools" in capsys.readouterr().out, "the failure is still logged"


def test_dispatch_tolerates_missing_arguments():
    tools.register(_tool("xray", run=lambda username, args: f"args={args}"))
    assert tools.dispatch("alice", "xray", None) == "args={}"


# ── The two paths agree ─────────────────────────────────────────────────────

def test_every_migrated_agent_declares_a_runnable_tool():
    """The real roster, not a synthetic one: schema and runner arrive together, so
    Owl can never be offered a tool with nothing behind it."""
    from agents.sales.registry import register_all

    register_all()

    assert tools.names() == [
        "analyse_call",
        "capture_learnings",
        "check_signals",
        "compose_outreach",
        "draft_recap",
        "find_target_companies",
        "recall_market",
        "research_account",
        "score_lead",
        "select_campaign",
        "xray",
    ]
    for name in tools.names():
        tool = tools.get(name)
        assert callable(tool.run)
        assert tool.input_schema.get("type") == "object"
        assert tool.description.strip()


def test_recall_market_is_read_only_and_says_it_does_not_search_the_web():
    """It reads the team's calls. Owl reaching for it when the user wants a
    company's *current* situation would answer from history and sound confident."""
    from agents.sales.registry import register_all

    register_all()
    tool = tools.get("recall_market")

    assert tool.writes is False
    assert "does NOT search the web" in tool.description
    assert "research_account" in tool.description, "it names what to use instead"


def test_the_api_roster_is_the_roster_owl_is_given():
    """`/api/sales/agents` and the model's tool list are the same set — the page
    path and the conversation path can never offer different agents."""
    tools.register(_tool("xray", writes=True))
    tools.register(_tool("research"))

    from agents.sales.routes import list_agents
    roster = list_agents(_user={"username": "alice"})

    assert [a["name"] for a in roster] == [s["name"] for s in tools.specs()]
    assert {a["name"]: a["writes"] for a in roster} == {"xray": True, "research": False}
