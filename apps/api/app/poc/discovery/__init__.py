"""Read-only PoC metadata discovery and explainable ranking."""

from .engine import DiscoveryEngine, discover
from .ranking import rank_candidate, score_candidate

__all__ = ["DiscoveryEngine", "discover", "rank_candidate", "score_candidate"]
