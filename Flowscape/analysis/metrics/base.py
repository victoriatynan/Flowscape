"""
The Metric plugin interface and its result type.

A Metric is an engineering CALCULATION over observations (and other metrics). It
answers "what does this measurement mean in engineering terms?" -- capacity, a
volume-to-capacity ratio, a level-of-service letter -- but never "is it a
problem?" (that is a Finding). Metrics are the SECOND computed stage; they run
on the same engine as observations, resolved by ordinary `requires` dependencies
and computed once into the same shared cache.

Contract (identical in shape to Observation, so the engine treats them alike):
  * `id`        -- unique, stable, snake_case identifier.
  * `category`  -- coarse grouping ("traffic", ...).
  * `kind`      -- "metric" (the pipeline buckets results by this).
  * `requires`  -- ids of the observations/metrics this one depends on; the
                   pipeline computes them first and passes their results in via
                   `deps`.
  * `compute(snapshot, deps) -> MetricResult`.

Metrics must be pure functions of (snapshot, deps): deterministic, no side
effects, no live state. Any engineering STANDARD a metric applies (per-lane
capacity, LOS thresholds) lives in `standards.py`, never hardcoded here -- so a
different standard is a data swap, not a code change.
"""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class MetricResult:
    """One engineering calculation. `value` is the network-level roll-up (or
    None when not applicable -- e.g. no measured volume); per-entity results
    ride in `detail["per_road"] = {road_id: ...}`, mirroring the observation
    convention so downstream stages read them the same way."""
    id: str
    category: str
    value: Any
    units: Optional[str] = None
    detail: Optional[dict] = None
    kind: str = "metric"

    def to_dict(self) -> dict:
        d = {"id": self.id, "category": self.category, "kind": self.kind,
             "value": self.value, "units": self.units}
        if self.detail is not None:
            d["detail"] = self.detail
        return d


class Metric:
    """Base class for metric plugins. Subclasses set `id`/`category`/`requires`
    and implement `compute`."""

    id: str = ""
    category: str = ""
    kind: str = "metric"
    requires: tuple = ()

    def compute(self, snapshot, deps) -> MetricResult:
        raise NotImplementedError
