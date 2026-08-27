"""The `/api/sales` surface — one router per agent, aggregated here.

Each agent owns its own `routes.py` and is included below as it lands. Keeping
the aggregation in one place means `main.py` never changes again as agents
migrate: it mounts this router once, and the sales section grows underneath it.

Each agent's old endpoints are deleted in the slice that replaces them, so the two
surfaces never both serve the same job. `high_intent` was retired whole in R4; what
remains alongside this router is `lead`, and only the endpoints its four surviving
pages call — the campaign builder, saved campaigns and the Google connection.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from agents.sales import tools
from agents.sales.registry import register_all
from auth import require_authed

# Mounting the sales surface is what puts the agents in Owl's hands.
register_all()

router = APIRouter(prefix="/api/sales", tags=["sales"])


@router.get("/agents")
def list_agents(_user: dict = Depends(require_authed)):
    """The agents Owl can run, and whether running one changes anything.

    Exposed so a surface can show what is available without hard-coding the
    roster, and so the two paths to an agent — page and conversation — are
    demonstrably the same set.
    """
    return [
        {
            "name": name,
            "description": tools.get(name).description,
            "writes": tools.get(name).writes,
        }
        for name in tools.names()
    ]


# Per-agent routers, included as each agent lands.
from agents.sales.call_analysis.routes import router as call_analysis_router  # noqa: E402
from agents.sales.campaign_intelligence.routes import router as intel_router  # noqa: E402
from agents.sales.campaign_selection.routes import router as campaign_router  # noqa: E402
from agents.sales.composer.routes import router as composer_router  # noqa: E402
from agents.sales.gtm.routes import router as gtm_router  # noqa: E402
from agents.sales.knowledge_capture.routes import router as capture_router  # noqa: E402
from agents.sales.recap.routes import router as recap_router  # noqa: E402
from agents.sales.research.routes import router as research_router  # noqa: E402
from agents.sales.signals.routes import router as signals_router  # noqa: E402
from agents.sales.scoring.routes import router as scoring_router  # noqa: E402
from agents.sales.xray.routes import router as xray_router  # noqa: E402

# Included in workflow order, so the surface reads like the path it serves —
# front half first, then everything after the conversation has happened.
router.include_router(scoring_router)
router.include_router(gtm_router)
router.include_router(xray_router)
router.include_router(research_router)
router.include_router(signals_router)
router.include_router(intel_router)
router.include_router(campaign_router)
router.include_router(composer_router)
router.include_router(call_analysis_router)
router.include_router(recap_router)
router.include_router(capture_router)
