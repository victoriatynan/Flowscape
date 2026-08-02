"""
Horizontal-geometry findings: interpret the SSD metrics into a design judgement.

    required_ssd + available_ssd (metrics) -> ssd_deficiency (finding) -> recommendation

`SSDDeficiency` flags every curved road where the available sight distance falls
short of the required stopping sight distance, grading each by how deep the
shortfall runs and packaging the flagged roads as traceable evidence (the exact
required / available / margin / radius structure the planning doc calls for).
"""

from .base import Finding, FindingResult
from ..metrics import standards


# Worst-to-best ordering, so the network severity is the max over flagged roads.
_RANK = {"none": 0, "low": 1, "moderate": 2, "high": 3}


class SSDDeficiency(Finding):
    """Curved roads whose available sight distance is below the required SSD.
    Only roads with a defined available SSD (i.e. curves) can be flagged; a
    straight road is never sight-limited by curvature. Evidence is one entry per
    flagged road, worst (most negative margin) first."""
    id = "ssd_deficiency"
    category = "geometry"
    requires = ("required_ssd", "available_ssd")

    def compute(self, snapshot, deps):
        required = deps["required_ssd"].detail["per_road"]
        available = deps["available_ssd"].detail["per_road"]
        evidence = []
        for road_id, avail in available.items():
            req = required.get(road_id)
            if req is None:              # no requirement computed -> skip
                continue
            required_ft = req["required_ft"]
            available_ft = avail["available_ft"]
            sev = standards.ssd_severity(required_ft, available_ft)
            if sev == "none":
                continue
            evidence.append({
                "road_id": road_id,
                "required_ft": round(required_ft, 1),
                "available_ft": round(available_ft, 1),
                "margin_ft": round(available_ft - required_ft, 1),
                "design_speed_mph": req["design_speed_mph"],
                "radius_ft": round(avail["radius_ft"], 1),
                "severity": sev,
            })
        evidence.sort(key=lambda x: x["margin_ft"])   # most deficient first

        network_severity = max((e["severity"] for e in evidence),
                               key=lambda s: _RANK[s], default="none")
        if evidence:
            worst = evidence[0]
            explanation = (
                f"{len(evidence)} curved road(s) provide less than the required "
                f"stopping sight distance; worst is {abs(worst['margin_ft'])} ft "
                f"short ({worst['available_ft']} ft available vs "
                f"{worst['required_ft']} ft required at "
                f"{worst['design_speed_mph']} mph). A driver may not see a stopped "
                f"vehicle in time to brake. (Horizontal / plan-view approximation.)")
        else:
            explanation = ("All curved roads provide adequate stopping sight "
                           "distance for their design speed (plan-view).")

        return FindingResult(
            id=self.id, category=self.category,
            name="Stopping sight distance deficiency",
            severity=network_severity,
            evidence=evidence,
            explanation=explanation,
            supporting_metrics=("required_ssd", "available_ssd"),
            supporting_observations=("horizontal_curvature",),
        )


class CurveSpeedAdvisory(Finding):
    """Curved roads whose advisory (safe) speed falls meaningfully below their
    design speed -- a driver holding the design speed would be pushed past
    comfortable side friction. Only curves have an advisory speed, so straight
    roads are never flagged. Evidence is one entry per flagged road, sharpest
    reduction (largest design-vs-advisory gap) first."""
    id = "curve_speed_advisory"
    category = "geometry"
    requires = ("curve_advisory_speed",)

    def compute(self, snapshot, deps):
        per_road = deps["curve_advisory_speed"].detail["per_road"]
        evidence = []
        for road_id, e in per_road.items():
            design = e["design_speed_mph"]
            advisory = e["advisory_mph"]
            sev = standards.advisory_speed_severity(design, advisory)
            if sev == "none":
                continue
            evidence.append({
                "road_id": road_id,
                "advisory_mph": round(advisory, 1),
                "design_speed_mph": design,
                "reduction_mph": round(design - advisory, 1),
                "radius_ft": round(e["radius_ft"], 1),
                "severity": sev,
            })
        evidence.sort(key=lambda x: x["reduction_mph"], reverse=True)

        network_severity = max((e["severity"] for e in evidence),
                               key=lambda s: _RANK[s], default="none")
        if evidence:
            worst = evidence[0]
            explanation = (
                f"{len(evidence)} curved road(s) support a safe speed below their "
                f"design speed; worst is {worst['reduction_mph']} mph under "
                f"({worst['advisory_mph']} mph advisory vs "
                f"{worst['design_speed_mph']} mph design, radius "
                f"{worst['radius_ft']} ft). Drivers at the design speed exceed "
                f"comfortable side friction. (Horizontal / plan-view, flat.)")
        else:
            explanation = ("All curved roads comfortably support their design "
                           "speed (plan-view).")

        return FindingResult(
            id=self.id, category=self.category,
            name="Curve advisory speed below design speed",
            severity=network_severity,
            evidence=evidence,
            explanation=explanation,
            supporting_metrics=("curve_advisory_speed",),
            supporting_observations=("horizontal_curvature",),
        )


class ShortBlockSpacing(Finding):
    """Blocks (roads bounded by an intersection at each end) shorter than the
    minimum intersection spacing. Closely-spaced intersections concentrate
    conflict points and turning movements, hurting capacity and safety. Evidence
    is one entry per flagged block, shortest first."""
    id = "short_block_spacing"
    category = "geometry"
    requires = ("block_length",)

    def compute(self, snapshot, deps):
        per_road = deps["block_length"].detail["per_road"]
        evidence = []
        for road_id, length_ft in per_road.items():
            sev = standards.short_block_severity(length_ft)
            if sev == "none":
                continue
            evidence.append({
                "road_id": road_id,
                "length_ft": round(length_ft, 1),
                "minimum_ft": standards.MIN_INTERSECTION_SPACING_FT,
                "severity": sev,
            })
        evidence.sort(key=lambda x: x["length_ft"])   # shortest first

        network_severity = max((e["severity"] for e in evidence),
                               key=lambda s: _RANK[s], default="none")
        if evidence:
            worst = evidence[0]
            explanation = (
                f"{len(evidence)} block(s) are shorter than the "
                f"{standards.MIN_INTERSECTION_SPACING_FT:.0f} ft minimum "
                f"intersection spacing; shortest is {worst['length_ft']} ft. "
                f"Closely-spaced intersections concentrate conflict points and "
                f"turning movements.")
        else:
            explanation = ("All intersection-bounded blocks meet the minimum "
                           f"{standards.MIN_INTERSECTION_SPACING_FT:.0f} ft spacing.")

        return FindingResult(
            id=self.id, category=self.category,
            name="Intersection spacing below minimum",
            severity=network_severity,
            evidence=evidence,
            explanation=explanation,
            supporting_metrics=(),
            supporting_observations=("block_length",),
        )
