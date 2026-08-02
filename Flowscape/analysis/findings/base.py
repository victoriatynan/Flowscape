"""
The Finding plugin interface and its result type.

A Finding INTERPRETS metrics -- it is the first stage that makes an engineering
judgement ("is this a problem?"). It never recomputes numbers; it reads metric
results and states their significance, with every conclusion traceable back to
the evidence it rests on. Findings are the THIRD computed stage, running on the
same engine via ordinary `requires` dependencies.

Contract (same shape as Observation/Metric, so the engine treats them alike):
  * `id` / `category` / `kind` ("finding") / `requires` / `compute(snapshot, deps)`.

A finding may flag zero, one, or many entities (e.g. roads). It emits ONE
FindingResult whose `evidence` lists the flagged instances; an empty list means
"checked, nothing flagged" -- an honest all-clear, not a missing result. Every
threshold it judges against comes from `metrics.standards`, never hardcoded.
"""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class FindingResult:
    """One interpreted finding over the network. Structure follows the planning
    doc: a name, severity, optional confidence, the metric/observation ids it
    rests on, the concrete `evidence` (flagged instances), and a plain-language
    engineering explanation. `flagged` is True when `evidence` is non-empty."""
    id: str
    category: str
    name: str
    severity: str                              # "none" | "low" | "moderate" | "high"
    evidence: list                             # [{road_id, vc, volume, capacity, ...}]
    explanation: str
    supporting_metrics: tuple = ()
    supporting_observations: tuple = ()
    confidence: Optional[float] = None
    kind: str = "finding"

    @property
    def flagged(self) -> bool:
        return bool(self.evidence)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "category": self.category, "kind": self.kind,
            "name": self.name, "severity": self.severity,
            "flagged": self.flagged, "evidence": self.evidence,
            "explanation": self.explanation,
            "supporting_metrics": list(self.supporting_metrics),
            "supporting_observations": list(self.supporting_observations),
            "confidence": self.confidence,
        }


class Finding:
    """Base class for finding plugins. Subclasses set `id`/`category`/`requires`
    and implement `compute`."""

    id: str = ""
    category: str = ""
    kind: str = "finding"
    requires: tuple = ()

    def compute(self, snapshot, deps) -> FindingResult:
        raise NotImplementedError
