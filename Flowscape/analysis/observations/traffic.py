"""
Traffic observations: factual measurements over the active vehicle set.

Under a static snapshot there are no vehicles, so these are 0 / undefined -- by
design (the framework must work identically whether or not a simulation is
running). Average speed will later feed delay and level-of-service metrics.
"""

from .base import Observation, ObservationResult


class VehicleCount(Observation):
    id = "vehicle_count"
    category = "traffic"

    def compute(self, snapshot, deps):
        return ObservationResult(self.id, self.category,
                                 value=len(snapshot.vehicles), units="count")


class AverageVehicleSpeed(Observation):
    """Mean speed of active vehicles, mph. Undefined (None) with no vehicles --
    an honest 'not applicable', never a misleading 0."""
    id = "average_speed"
    category = "traffic"

    def compute(self, snapshot, deps):
        vs = snapshot.vehicles
        value = (sum(v.speed_mph for v in vs) / len(vs)) if vs else None
        return ObservationResult(self.id, self.category, value=value, units="mph")


class TrafficVolume(Observation):
    """Simulation-derived volume per road, in veh/hr, measured over the runtime
    window (how many vehicles actually TRAVERSED each road -- not demand, not
    capacity). The first observation that feeds the traffic-operations metric
    chain (capacity -> V/C -> level of service).

    Per-road values ride in `detail["per_road"] = {road_id: veh_per_hr}`; the
    aggregate `value` is the network total veh/hr. On a static snapshot no
    volume was measured, so every road's value is None and the per_road map is
    empty -- V/C and LOS then read as 'not applicable' downstream."""
    id = "traffic_volume"
    category = "traffic"

    def compute(self, snapshot, deps):
        per_road = {r.id: r.observed_volume_vph
                    for r in snapshot.roads
                    if r.observed_volume_vph is not None}
        total = sum(per_road.values()) if per_road else None
        return ObservationResult(self.id, self.category, value=total,
                                 units="veh/hr",
                                 detail={"per_road": per_road})
