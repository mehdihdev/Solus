"""Impact engine (SOLUS-IMP-01/02) — see `engine` and `consequences` docstrings."""

from solus_api.impact.consequences import build_narrate_fn, checker_provider
from solus_api.impact.engine import ConsequenceProvider, compute_impact

__all__ = ["ConsequenceProvider", "build_narrate_fn", "checker_provider", "compute_impact"]
