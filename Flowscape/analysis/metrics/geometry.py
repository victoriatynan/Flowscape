"""
Horizontal-geometry metrics: the plan-view stopping sight distance vertical.

    horizontal_curvature (observation)
        -> required_ssd  (from design speed)
        -> available_ssd (from curve radius + lateral clearance)

These are the metric half of the Milestone 3 slice. All engineering numbers --
perception-reaction time, deceleration, the design-speed default, the lateral
clearance -- come from `standards.py`, so the standard is a data swap.

Documented fidelity: this is HORIZONTAL / plan-view SSD (2D approximation). There
is no grade term and no vertical component; the 2D world model does not have one.

Per-road values ride in `detail["per_road"]`, mirroring the traffic metrics so
downstream stages read them the same way.
"""

from .base import Metric, MetricResult
from . import standards


class RequiredSSD(Metric):
    """Per-road required stopping sight distance (ft) from the road's effective
    design speed (its own, or the class/global default when unset). Reads facts
    off the snapshot; needs no upstream metric. The aggregate `value` is the
    network's largest requirement."""
    id = "required_ssd"
    category = "geometry"
    requires = ()

    def compute(self, snapshot, deps):
        per_road = {}
        for r in snapshot.roads:
            v = standards.effective_design_speed(r.functional_class,
                                                 r.design_speed)
            per_road[r.id] = {"required_ft": standards.required_ssd_ft(v),
                              "design_speed_mph": v}
        worst = max((e["required_ft"] for e in per_road.values()), default=None)
        return MetricResult(self.id, self.category, value=worst,
                            units="ft", detail={"per_road": per_road})


class AvailableSSD(Metric):
    """Per-road available sight distance (ft) along its horizontal curve, limited
    by the standard lateral clearance. Defined only for CURVED roads (a straight
    road is not sight-limited by curvature and is absent from the map). Each
    entry keeps the radius alongside the distance for traceable evidence. The
    aggregate `value` is the network's worst (smallest) available SSD, or None."""
    id = "available_ssd"
    category = "geometry"
    requires = ("horizontal_curvature",)

    def compute(self, snapshot, deps):
        curvature = deps["horizontal_curvature"].detail["per_road"]
        per_road = {}
        for road_id, e in curvature.items():
            radius = e["radius_ft"]
            avail = standards.available_ssd_ft(radius)
            if avail is None:            # straight or clearance beyond the curve
                continue
            per_road[road_id] = {"available_ft": avail, "radius_ft": radius}
        worst = min((e["available_ft"] for e in per_road.values()), default=None)
        return MetricResult(self.id, self.category, value=worst,
                            units="ft", detail={"per_road": per_road})


class CurveAdvisorySpeed(Metric):
    """Per-road curve advisory (safe) speed (mph) -- the comfortable speed the
    road's sharpest horizontal curve supports, from the point-mass relation in
    `standards`. Defined only for CURVED roads; a straight road is absent (no
    curve, no curvature speed limit). Each entry keeps the radius and the road's
    effective design speed alongside the advisory speed for traceable evidence.
    The aggregate `value` is the network's lowest advisory speed, or None."""
    id = "curve_advisory_speed"
    category = "geometry"
    requires = ("horizontal_curvature",)

    def compute(self, snapshot, deps):
        curvature = deps["horizontal_curvature"].detail["per_road"]
        design_speed = {r.id: standards.effective_design_speed(
                            r.functional_class, r.design_speed)
                        for r in snapshot.roads}
        per_road = {}
        for road_id, e in curvature.items():
            radius = e["radius_ft"]
            advisory = standards.curve_advisory_speed_mph(radius)
            if advisory is None:             # straight road -> not curvature-limited
                continue
            per_road[road_id] = {"advisory_mph": advisory, "radius_ft": radius,
                                 "design_speed_mph": design_speed.get(road_id)}
        worst = min((e["advisory_mph"] for e in per_road.values()), default=None)
        return MetricResult(self.id, self.category, value=worst,
                            units="mph", detail={"per_road": per_road})


class IntersectionDensity(Metric):
    """Network-level intersection density: intersections per centerline mile, a
    standard connectivity measure (higher density = a finer, more permeable
    grid). A pure roll-up of two observations -- no per-road detail. `value` is
    None when there is no road length to divide by (an empty network)."""
    id = "intersection_density"
    category = "network"
    requires = ("intersection_count", "total_road_length")

    def compute(self, snapshot, deps):
        intersections = deps["intersection_count"].value
        length_ft = deps["total_road_length"].value
        length_mi = length_ft / 5280.0
        value = (intersections / length_mi) if length_mi > 0 else None
        return MetricResult(self.id, self.category, value=value,
                            units="per mi",
                            detail={"intersections": intersections,
                                    "length_mi": length_mi})
