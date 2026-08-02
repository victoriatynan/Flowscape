"""
Traffic-operations findings: interpret the V/C metric into an operational
judgement. This is the finding stage of the Milestone 2 vertical slice.

    ... -> vc_ratio (metric) -> over_capacity (finding) -> recommendation

`OverCapacity` flags every road at or above the practical-capacity threshold
(from `metrics.standards`), grading each by how far over it runs, and packages
the flagged roads as traceable evidence.
"""

from .base import Finding, FindingResult
from ..metrics import standards


def _severity(vc):
    """Grade a single road's V/C. Below the practical threshold it is unflagged
    ("none"); at/over capacity is the worst grade."""
    if vc >= 1.0:
        return "high"
    if vc >= standards.PRACTICAL_CAPACITY_VC:
        return "moderate"
    return "none"


# Worst-to-best ordering, so the network severity is the max over flagged roads.
_RANK = {"none": 0, "low": 1, "moderate": 2, "high": 3}


class OverCapacity(Finding):
    """Roads operating at or above practical capacity (V/C >= the standard's
    threshold). Evidence is one entry per flagged road, worst first."""
    id = "over_capacity"
    category = "traffic"
    requires = ("vc_ratio",)

    def compute(self, snapshot, deps):
        per_road = deps["vc_ratio"].detail["per_road"]
        evidence = []
        for road_id, e in per_road.items():
            sev = _severity(e["vc"])
            if sev == "none":
                continue
            evidence.append({
                "road_id": road_id,
                "vc": round(e["vc"], 3),
                "volume_vph": e["volume"],
                "capacity_vph": e["capacity"],
                "severity": sev,
            })
        evidence.sort(key=lambda x: x["vc"], reverse=True)

        network_severity = max((e["severity"] for e in evidence),
                               key=lambda s: _RANK[s], default="none")
        if evidence:
            explanation = (
                f"{len(evidence)} road(s) operate at or above practical "
                f"capacity (V/C >= {standards.PRACTICAL_CAPACITY_VC:.2f}); "
                f"worst V/C {evidence[0]['vc']}. At these ratios delay rises "
                f"sharply and queues form.")
        else:
            explanation = (
                "No road reaches practical capacity (all V/C below "
                f"{standards.PRACTICAL_CAPACITY_VC:.2f}).")

        return FindingResult(
            id=self.id, category=self.category,
            name="Road operating above practical capacity",
            severity=network_severity,
            evidence=evidence,
            explanation=explanation,
            supporting_metrics=("vc_ratio", "road_capacity"),
            supporting_observations=("traffic_volume",),
        )


class ExcessCapacity(Finding):
    """The mirror image of OverCapacity: roads carrying so little of their
    capacity (V/C at or below the standard's excess threshold) that they are
    right-sizing candidates -- an over-built link where a lane could be reclaimed
    for parking, transit, or active travel. Only roads with MEASURED volume can
    be flagged; an unmeasured (static) road is not evidence of low demand.
    Evidence is one entry per flagged road, most under-utilized (lowest V/C)
    first."""
    id = "excess_capacity"
    category = "traffic"
    requires = ("vc_ratio",)

    def compute(self, snapshot, deps):
        per_road = deps["vc_ratio"].detail["per_road"]
        evidence = []
        for road_id, e in per_road.items():
            sev = standards.excess_capacity_severity(e["vc"])
            if sev == "none":
                continue
            evidence.append({
                "road_id": road_id,
                "vc": round(e["vc"], 3),
                "volume_vph": e["volume"],
                "capacity_vph": e["capacity"],
                "severity": sev,
            })
        evidence.sort(key=lambda x: x["vc"])          # most under-utilized first

        network_severity = max((e["severity"] for e in evidence),
                               key=lambda s: _RANK[s], default="none")
        if evidence:
            explanation = (
                f"{len(evidence)} road(s) carry well under their capacity "
                f"(V/C <= {standards.EXCESS_CAPACITY_VC:.2f}); lowest V/C "
                f"{evidence[0]['vc']}. Such over-built links are candidates for "
                f"right-sizing (a road diet), reclaiming space for other uses.")
        else:
            explanation = (
                "No road is substantially under capacity (all measured V/C "
                f"above {standards.EXCESS_CAPACITY_VC:.2f}).")

        return FindingResult(
            id=self.id, category=self.category,
            name="Road substantially under capacity",
            severity=network_severity,
            evidence=evidence,
            explanation=explanation,
            supporting_metrics=("vc_ratio", "road_capacity"),
            supporting_observations=("traffic_volume",),
        )
