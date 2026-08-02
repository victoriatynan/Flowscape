"""
The Observation plugin interface and its result type.

An Observation is a factual measurement over a Snapshot. It answers "what is
measurably true?" -- never "what does it mean?" (that is a Metric) or "is it a
problem?" (that is a Finding). Observations are the first and only computed
stage in Milestone 1; metrics, findings and recommendations are added later as
their own plugins on top of the SAME engine.

Contract:
  * `id`        -- unique, stable, snake_case identifier.
  * `category`  -- coarse grouping ("network", "traffic", ...).
  * `requires`  -- ids of the observations this one depends on. The pipeline
                   guarantees they are computed first and passes their results
                   in via `deps`. Most observations require nothing.
  * `compute(snapshot, deps) -> ObservationResult`.

Observations must be pure functions of (snapshot, deps): deterministic, with no
side effects and no access to global or live state.
"""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class ObservationResult:
    """One measured fact. `value` is the measurement (a number, or None when
    undefined -- e.g. average speed with no vehicles). `detail` is optional
    structured breakdown (e.g. building counts by type). `kind` labels the
    pipeline stage this result belongs to so the packager can partition a single
    result cache into observations / metrics / findings / recommendations."""
    id: str
    category: str
    value: Any
    units: Optional[str] = None
    detail: Optional[dict] = None
    kind: str = "observation"

    def to_dict(self) -> dict:
        d = {"id": self.id, "category": self.category, "kind": self.kind,
             "value": self.value, "units": self.units}
        if self.detail is not None:
            d["detail"] = self.detail
        return d


class Observation:
    """Base class for observation plugins. Subclasses set `id`/`category`/
    `requires` and implement `compute`. `kind` is the stage tag the pipeline
    uses to bucket results; observations are the first stage."""

    id: str = ""
    category: str = ""
    kind: str = "observation"
    requires: tuple = ()

    def compute(self, snapshot, deps) -> ObservationResult:
        raise NotImplementedError
