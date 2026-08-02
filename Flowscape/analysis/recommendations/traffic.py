"""
Traffic-operations recommendations: propose improvements for roads the
over-capacity finding flagged. This closes the Milestone 2 vertical slice:

    ... -> over_capacity (finding) -> add_capacity (recommendation)

`AddCapacity` proposes, per flagged road, the two classic levers for an
over-capacity link -- add a through lane (raise capacity) or reduce upstream
demand (lower volume) -- each with its benefit and trade-offs. It reads the
finding only; when nothing was flagged it recommends nothing.
"""

from .base import Recommendation, RecommendationResult


class RightSizeRoad(Recommendation):
    """For each road the excess-capacity finding flagged, propose reclaiming the
    under-used lane -- a road diet (reallocate to parking/transit/active travel)
    or a narrower cross-section. Reads the finding only; recommends nothing when
    nothing was flagged."""
    id = "right_size_road"
    category = "traffic"
    requires = ("excess_capacity",)

    def compute(self, snapshot, deps):
        finding = deps["excess_capacity"]
        items = []
        for e in finding.evidence:
            road_id = e["road_id"]
            evidence = {"road_id": road_id, "vc": e["vc"],
                        "volume_vph": e["volume_vph"],
                        "capacity_vph": e["capacity_vph"]}
            items.append({
                "road_id": road_id,
                "title": "Reallocate a lane (road diet)",
                "expected_benefit": ("Reclaims under-used capacity for parking, "
                                     "transit, or active travel with little "
                                     "effect on vehicle delay at this volume."),
                "tradeoffs": ("Less resilience to future demand growth; "
                              "reversing it later costs pavement work."),
                "supporting_evidence": evidence,
            })

        return RecommendationResult(
            id=self.id, category=self.category, items=items,
            supporting_findings=("excess_capacity",))


class AddCapacity(Recommendation):
    id = "add_capacity"
    category = "traffic"
    requires = ("over_capacity",)

    def compute(self, snapshot, deps):
        finding = deps["over_capacity"]
        items = []
        for e in finding.evidence:
            road_id = e["road_id"]
            evidence = {"road_id": road_id, "vc": e["vc"],
                        "volume_vph": e["volume_vph"],
                        "capacity_vph": e["capacity_vph"]}
            items.append({
                "road_id": road_id,
                "title": "Add a through lane",
                "expected_benefit": ("Raises capacity, lowering V/C and the "
                                     "delay/queueing it drives."),
                "tradeoffs": ("More pavement and right-of-way; may shift the "
                              "bottleneck downstream."),
                "supporting_evidence": evidence,
            })
            items.append({
                "road_id": road_id,
                "title": "Reduce upstream demand",
                "expected_benefit": ("Lowers volume on this link (reroute, "
                                     "meter, or adjust land use)."),
                "tradeoffs": "Pushes trips onto other routes or times.",
                "supporting_evidence": evidence,
            })

        return RecommendationResult(
            id=self.id, category=self.category, items=items,
            supporting_findings=("over_capacity",))
