"""
The Recommendation plugin interface and its result type.

A Recommendation proposes a possible engineering improvement in response to a
finding. It is the FOURTH and final computed stage. Recommendations are
INDEPENDENT of findings in the sense the planning doc means: a finding does not
dictate them, and one finding may yield zero, one, or many. Each recommendation
states an expected benefit, its trade-offs, and the evidence it rests on, so it
stays advisory and traceable -- never an automatic action on the network.

Contract (same shape as the other stages): `id` / `category` / `kind`
("recommendation") / `requires` / `compute(snapshot, deps)`.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class RecommendationResult:
    """A set of proposed improvements. `items` is a list of proposals, each a
    dict with at least a `title`, `expected_benefit`, `tradeoffs`, and the
    `supporting_evidence` (e.g. the road and its V/C) it addresses. An empty
    list means "nothing to recommend" -- an honest all-clear."""
    id: str
    category: str
    items: list
    supporting_findings: tuple = ()
    confidence: Optional[float] = None
    kind: str = "recommendation"

    def to_dict(self) -> dict:
        return {
            "id": self.id, "category": self.category, "kind": self.kind,
            "items": self.items,
            "supporting_findings": list(self.supporting_findings),
            "confidence": self.confidence,
        }


class Recommendation:
    """Base class for recommendation plugins. Subclasses set `id`/`category`/
    `requires` and implement `compute`."""

    id: str = ""
    category: str = ""
    kind: str = "recommendation"
    requires: tuple = ()

    def compute(self, snapshot, deps) -> RecommendationResult:
        raise NotImplementedError
