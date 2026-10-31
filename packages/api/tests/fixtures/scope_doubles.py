"""SOLUSDEV-321 P1-T1 — the scope planner's shared doubles, for tests about what a turn names
rather than what the index or the graph holds."""

from solus_api.agent.interfaces import ContextBudget, GraphContext, GraphScope
from solus_api.services.search import EntityHit


async def no_hits(q: str, limit: int) -> list[EntityHit]:
    """An index that resolves no name."""
    return []


async def empty_graph(scope: GraphScope, budget: ContextBudget) -> GraphContext:
    """A graph pull that finds nothing."""
    return GraphContext(entities=[], edges=[])
