"""
Horizontal-geometry observations: factual roadway shape read straight off the
snapshot. This seeds the Milestone 3 geometry vertical, the way `traffic_volume`
seeded the Milestone 2 traffic vertical.

Facts only -- radius and deflection are measurements, not judgements. Whether a
curve is "too sharp" is a metric/finding decision downstream (required vs
available SSD), never here.
"""

from .base import Observation, ObservationResult


class HorizontalCurvature(Observation):
    """Per-road horizontal curve radius and deflection. `detail["per_road"]` maps
    road id -> {radius_ft, deflection_deg}, with radius None for a straight road.
    The network roll-up `value` is the SHARPEST (smallest finite) radius on the
    network, or None when every road is straight."""
    id = "horizontal_curvature"
    category = "geometry"

    def compute(self, snapshot, deps):
        per_road = {}
        for r in snapshot.roads:
            per_road[r.id] = {
                "radius_ft": r.governing_curve_radius_ft,
                "deflection_deg": r.horizontal_deflection_angle_deg,
            }
        radii = [e["radius_ft"] for e in per_road.values()
                 if e["radius_ft"] is not None]
        sharpest = min(radii) if radii else None
        return ObservationResult(self.id, self.category, value=sharpest,
                                 units="ft", detail={"per_road": per_road})


class BlockLength(Observation):
    """Per-road intersection spacing: the length (ft) of each road bounded by an
    intersection at BOTH ends -- a "block". This is the spacing between adjacent
    intersections along that link, the raw fact an access-management finding
    (short blocks pack conflict points together) reads. A road terminating at a
    non-intersection node (a dead-end, a mid-run continuation, a driveway stub)
    is not a block and is absent from the map. `detail["per_road"]` maps road id
    -> length_ft for blocks only; the roll-up `value` is the SHORTEST block on
    the network, or None when there are no intersection-bounded roads."""
    id = "block_length"
    category = "geometry"

    def compute(self, snapshot, deps):
        is_intersection = {n.id: n.is_intersection for n in snapshot.nodes}
        per_road = {}
        for r in snapshot.roads:
            if (is_intersection.get(r.start_node_id)
                    and is_intersection.get(r.end_node_id)):
                per_road[r.id] = r.length_ft
        shortest = min(per_road.values()) if per_road else None
        return ObservationResult(self.id, self.category, value=shortest,
                                 units="ft", detail={"per_road": per_road})
