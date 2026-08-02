"""
Traffic-operations metrics: capacity, volume-to-capacity ratio, and level of
service. This is the metric half of the Milestone 2 vertical slice --

    traffic_volume (observation) -> road_capacity -> vc_ratio -> level_of_service

-- with each stage reading the previous through ordinary `requires` dependencies.
All engineering numbers come from `standards.py`, so the standard is a data swap.

Directionality note: the volume observation counts every traversal of a road
regardless of travel direction, so capacity here is likewise the road's TOTAL
(forward + reverse) lane capacity, keeping V/C an apples-to-apples ratio. A
directional model is a later refinement.

Per-road values ride in `detail["per_road"]`; the aggregate `value` is a
network roll-up. A road with no measured volume is simply absent from the V/C
and LOS maps (its ratio is undefined, not zero) -- so a static snapshot yields
empty maps and a network-level `value` of None.
"""

from .base import Metric, MetricResult
from . import standards


class RoadCapacity(Metric):
    """Per-road capacity (veh/hr) = total lanes x per-lane capacity for the
    road's functional class. Reads road facts straight off the snapshot; needs
    no upstream metric."""
    id = "road_capacity"
    category = "traffic"
    requires = ()

    def compute(self, snapshot, deps):
        per_road = {}
        for r in snapshot.roads:
            lanes = r.lanes_forward + r.lanes_reverse
            per_lane = standards.capacity_per_lane_vph(r.functional_class)
            per_road[r.id] = lanes * per_lane
        total = sum(per_road.values()) if per_road else None
        return MetricResult(self.id, self.category, value=total,
                            units="veh/hr", detail={"per_road": per_road})


class VolumeCapacityRatio(Metric):
    """Per-road V/C = measured volume / capacity. Defined only where volume was
    measured (and capacity > 0). Each per_road entry keeps volume and capacity
    alongside the ratio so a finding has traceable evidence without re-deriving
    it. The aggregate `value` is the network's worst (max) V/C, or None."""
    id = "vc_ratio"
    category = "traffic"
    requires = ("traffic_volume", "road_capacity")

    def compute(self, snapshot, deps):
        volumes = deps["traffic_volume"].detail["per_road"]
        caps = deps["road_capacity"].detail["per_road"]
        per_road = {}
        for road_id, volume in volumes.items():
            cap = caps.get(road_id)
            if not cap:                      # unknown or zero capacity
                continue
            per_road[road_id] = {"vc": volume / cap,
                                 "volume": volume, "capacity": cap}
        worst = max((e["vc"] for e in per_road.values()), default=None)
        return MetricResult(self.id, self.category, value=worst,
                            units="ratio", detail={"per_road": per_road})


class LevelOfService(Metric):
    """Per-road level-of-service letter (A-F) from V/C via the standards bands.
    The aggregate `value` is the network's worst LOS letter, or None."""
    id = "level_of_service"
    category = "traffic"
    requires = ("vc_ratio",)

    def compute(self, snapshot, deps):
        vc = deps["vc_ratio"].detail["per_road"]
        per_road = {road_id: standards.los_letter(entry["vc"])
                    for road_id, entry in vc.items()}
        worst = max(per_road.values(), default=None)   # 'F' > ... > 'A'
        return MetricResult(self.id, self.category, value=worst,
                            units="LOS", detail={"per_road": per_road})


class VehicleMilesTraveled(Metric):
    """Per-road vehicle-miles travelled per hour = measured volume (veh/hr) x
    the road's length (mi). A basic operational exposure/demand measure: how much
    travel each link actually carries, which weights where congestion and safety
    findings matter most. Defined only where volume was measured; a road with no
    measured volume is absent (its VMT is undefined, not zero). The aggregate
    `value` is the network total VMT/hr, or None on a static snapshot."""
    id = "vehicle_miles_traveled"
    category = "traffic"
    requires = ("traffic_volume",)

    def compute(self, snapshot, deps):
        volumes = deps["traffic_volume"].detail["per_road"]
        length_mi = {r.id: r.length_ft / 5280.0 for r in snapshot.roads}
        per_road = {}
        for road_id, volume in volumes.items():
            miles = length_mi.get(road_id)
            if miles is None:
                continue
            per_road[road_id] = {"vmt": volume * miles,
                                 "volume": volume, "length_mi": miles}
        total = sum(e["vmt"] for e in per_road.values()) if per_road else None
        return MetricResult(self.id, self.category, value=total,
                            units="veh-mi/hr", detail={"per_road": per_road})
