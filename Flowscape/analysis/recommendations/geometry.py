"""
Horizontal-geometry recommendations: propose improvements for roads the SSD
deficiency finding flagged. This closes the Milestone 3 geometry slice:

    ... -> ssd_deficiency (finding) -> improve_sight_distance (recommendation)

`ImproveSightDistance` proposes, per flagged road, the three classic horizontal
levers for an SSD shortfall -- flatten the curve (raise available SSD), lower the
design speed (lower required SSD), or clear the roadside obstruction (raise
available SSD) -- each with its benefit and trade-offs. It reads the finding
only; when nothing was flagged it recommends nothing.
"""

from .base import Recommendation, RecommendationResult


class ImproveSightDistance(Recommendation):
    id = "improve_sight_distance"
    category = "geometry"
    requires = ("ssd_deficiency",)

    def compute(self, snapshot, deps):
        finding = deps["ssd_deficiency"]
        items = []
        for e in finding.evidence:
            road_id = e["road_id"]
            evidence = {"road_id": road_id, "required_ft": e["required_ft"],
                        "available_ft": e["available_ft"],
                        "margin_ft": e["margin_ft"], "radius_ft": e["radius_ft"],
                        "design_speed_mph": e["design_speed_mph"]}
            items.append({
                "road_id": road_id,
                "title": "Increase the curve radius",
                "expected_benefit": ("Flattens the curve, raising available "
                                     "sight distance around it."),
                "tradeoffs": ("More right-of-way and earthwork; realigns the "
                              "road."),
                "supporting_evidence": evidence,
            })
            items.append({
                "road_id": road_id,
                "title": "Reduce the design speed",
                "expected_benefit": ("Lowers the required stopping sight "
                                     "distance to what the curve provides."),
                "tradeoffs": "Reduces mobility; needs enforcement to be real.",
                "supporting_evidence": evidence,
            })
            items.append({
                "road_id": road_id,
                "title": "Remove the sight obstruction / widen the clear zone",
                "expected_benefit": ("Increases lateral clearance, raising "
                                     "available sight distance without realigning."),
                "tradeoffs": ("Needs roadside right-of-way; may not be feasible "
                              "where the obstruction is a structure."),
                "supporting_evidence": evidence,
            })

        return RecommendationResult(
            id=self.id, category=self.category, items=items,
            supporting_findings=("ssd_deficiency",))


class CurveWarningTreatment(Recommendation):
    """For each curve the advisory-speed finding flagged, propose the two classic
    responses -- flatten the curve (raise the advisory speed toward the design
    speed) or post a curve-warning + advisory-speed treatment (align driver
    expectation with the safe speed). Reads the finding only; recommends nothing
    when nothing was flagged."""
    id = "curve_warning_treatment"
    category = "geometry"
    requires = ("curve_speed_advisory",)

    def compute(self, snapshot, deps):
        finding = deps["curve_speed_advisory"]
        items = []
        for e in finding.evidence:
            road_id = e["road_id"]
            evidence = {"road_id": road_id, "advisory_mph": e["advisory_mph"],
                        "design_speed_mph": e["design_speed_mph"],
                        "reduction_mph": e["reduction_mph"],
                        "radius_ft": e["radius_ft"]}
            items.append({
                "road_id": road_id,
                "title": "Increase the curve radius",
                "expected_benefit": ("Raises the comfortable speed toward the "
                                     "design speed, removing the advisory."),
                "tradeoffs": "More right-of-way and earthwork; realigns the road.",
                "supporting_evidence": evidence,
            })
            items.append({
                "road_id": road_id,
                "title": "Post curve warning + advisory speed",
                "expected_benefit": ("Aligns driver expectation with the safe "
                                     "speed at low cost, without realigning."),
                "tradeoffs": ("A mitigation, not a fix; relies on driver "
                              "compliance."),
                "supporting_evidence": evidence,
            })

        return RecommendationResult(
            id=self.id, category=self.category, items=items,
            supporting_findings=("curve_speed_advisory",))


class ConsolidateAccess(Recommendation):
    """For each short block the spacing finding flagged, propose consolidating or
    removing the closely-spaced intersection to restore spacing. Reads the
    finding only; recommends nothing when nothing was flagged."""
    id = "consolidate_access"
    category = "geometry"
    requires = ("short_block_spacing",)

    def compute(self, snapshot, deps):
        finding = deps["short_block_spacing"]
        items = []
        for e in finding.evidence:
            road_id = e["road_id"]
            evidence = {"road_id": road_id, "length_ft": e["length_ft"],
                        "minimum_ft": e["minimum_ft"]}
            items.append({
                "road_id": road_id,
                "title": "Consolidate the closely-spaced intersection",
                "expected_benefit": ("Restores intersection spacing, cutting "
                                     "conflict points and smoothing progression."),
                "tradeoffs": ("Removes an access/connection; may lengthen some "
                              "trips or need a replacement route."),
                "supporting_evidence": evidence,
            })

        return RecommendationResult(
            id=self.id, category=self.category, items=items,
            supporting_findings=("short_block_spacing",))
