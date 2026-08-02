"""
AnalysisResult -- the complete, JSON-serializable output of one analysis run.

Milestone 1 carried observations only. Milestone 2 adds `metrics`, `findings`
and `recommendations` -- the downstream stages of the same pipeline. All four
are {id: result} maps of stage-tagged results; downstream applications consume
this package and never perform engineering calculations themselves. The extra
fields default to empty, so a Milestone-1-only run (or any caller that predates
M2) serializes exactly as before plus three empty maps.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AnalysisResult:
    observations: dict                    # {observation_id: ObservationResult}
    metadata: dict
    metrics: dict = field(default_factory=dict)          # {metric_id: MetricResult}
    findings: dict = field(default_factory=dict)         # {finding_id: FindingResult}
    recommendations: dict = field(default_factory=dict)  # {rec_id: RecommendationResult}

    def to_dict(self) -> dict:
        return {
            "observations": {oid: r.to_dict()
                             for oid, r in self.observations.items()},
            "metrics": {mid: r.to_dict() for mid, r in self.metrics.items()},
            "findings": {fid: r.to_dict() for fid, r in self.findings.items()},
            "recommendations": {rid: r.to_dict()
                                for rid, r in self.recommendations.items()},
            "metadata": self.metadata,
        }
