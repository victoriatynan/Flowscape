"""
Immutable simulation snapshots -- the ONLY input to the Analysis Platform.

A Snapshot is a frozen, plain-data view of simulation state expressed in
canonical engineering units (true feet, mph, decimal hours). It contains FACTS
ONLY -- no capacity, no level of service, no "good/bad" judgement. Observations,
metrics and findings are computed downstream from these facts and never reach
back into the live network or simulation.

Everything here is a frozen dataclass built from tuples, so a Snapshot is deeply
immutable and hashable: the pipeline can key a per-run cache on it, and a stage
can never mutate the state it was handed. The road-classification fields
(`functional_class`, `design_speed`, `context`) are optional and default to
None, so the platform is fully useful before the P1 classification system lands.
"""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class RoadSnapshot:
    """One road, factual. `length_ft` is the true centerline length in feet
    (independent of ROAD_WIDTH_SCALE, which only affects rendered width). Lane
    counts are scale-invariant."""
    id: int
    length_ft: float
    lanes_forward: int
    lanes_reverse: int
    start_node_id: int
    end_node_id: int
    functional_class: Optional[str] = None
    design_speed: Optional[float] = None
    context: Optional[str] = None
    # Simulation-derived volume in veh/hr over the runtime window, or None on a
    # static snapshot (no sim = no measured volume, an honest "not applicable").
    observed_volume_vph: Optional[float] = None
    # Plan-view (horizontal) geometry, derived from the road's Bezier at the
    # builder boundary (Milestone 3). `governing_curve_radius_ft` is the tightest
    # radius of curvature along the road, in true feet, or None when the road is
    # straight (no curve = infinite radius). `horizontal_deflection_angle_deg` is
    # the total plan-view turn angle, ~0 for a straight road. The 2D world model
    # has no grade, so no vertical/grade field exists here by design.
    governing_curve_radius_ft: Optional[float] = None
    horizontal_deflection_angle_deg: float = 0.0


@dataclass(frozen=True)
class NodeSnapshot:
    """One graph node. `is_intersection` is precomputed at build time so
    downstream observations never need the live network to classify it."""
    id: int
    is_intersection: bool
    control_type: Optional[str]
    position: tuple


@dataclass(frozen=True)
class BuildingSnapshot:
    id: int
    building_type: str
    category: Optional[str]
    connection_node_ids: tuple
    # Nominal capacity (top of the type's count range) and whether the type is
    # residential, both resolved from the building catalogue at the builder
    # boundary -- the only layer allowed to read domain tables. They are facts,
    # not judgements: a building-mix observation rolls them into population/jobs
    # totals without the platform reaching back into the catalogue. None/False
    # for an unknown building type (mirrors the legacy endpoint skipping it).
    capacity: Optional[int] = None
    is_residential: bool = False


@dataclass(frozen=True)
class VehicleSnapshot:
    """One active vehicle. Present only under a runtime source; a static
    (editor) snapshot carries none. `speed_mph` is normalized from the sim's
    internal ft/s at the builder boundary."""
    id: int
    speed_mph: float
    position: tuple
    dest_node_id: Optional[int] = None
    dest_building_id: Optional[int] = None


@dataclass(frozen=True)
class SnapshotMeta:
    """Where this snapshot came from and (for runtime) when. `source_kind` is
    "static" or "runtime"; timing fields are None for a static snapshot."""
    source_kind: str
    is_running: bool
    sim_time_hours: Optional[float] = None
    tick: Optional[int] = None


@dataclass(frozen=True)
class Snapshot:
    """The complete immutable input to one analysis run."""
    roads: tuple
    nodes: tuple
    buildings: tuple
    vehicles: tuple
    meta: SnapshotMeta

    def describe(self) -> dict:
        """Small non-authoritative summary for metadata/debugging. Not an
        analysis result -- just counts a client can show while the real
        observations are what applications consume."""
        return {
            "roads": len(self.roads),
            "nodes": len(self.nodes),
            "buildings": len(self.buildings),
            "vehicles": len(self.vehicles),
            "source_kind": self.meta.source_kind,
            "is_running": self.meta.is_running,
        }
