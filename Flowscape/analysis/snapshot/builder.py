"""
The snapshot builder -- THE unit-normalization boundary.

This is the only module in the Analysis Platform that knows about simulation
internals (RoadNetwork geometry, ROAD_WIDTH_SCALE, the sim's ft/s speed, the
demand clock). It converts raw state into canonical engineering units and emits
an immutable Snapshot. Everything downstream sees clean facts (feet, mph, hours)
and never touches the live network again.

Normalization rules:
  * length_ft  -- the road's true centerline length. Centerline sampling is in
                  feet already (road_geometry.PIXELS_PER_FOOT == 1.0), and
                  ROAD_WIDTH_SCALE scales rendered WIDTH only, never length.
  * lane counts -- read from the profile; counts are scale-invariant.
  * speed_mph  -- the sim integrates speed in ft/s; convert to mph here.
  * sim time   -- the scheduler clock is already decimal sim-HOURS.
"""

from road_style import get_road_profile
from routing import _polyline_length
from destinations import BUILDING_TYPES, RESIDENTIAL

from .models import (RoadSnapshot, NodeSnapshot, BuildingSnapshot,
                     VehicleSnapshot, SnapshotMeta, Snapshot)
from .geometry_math import governing_curve_radius_ft, horizontal_deflection_deg

# ft/s -> mph. 1 mile = 5280 ft, 1 hour = 3600 s.
FT_PER_S_TO_MPH = 3600.0 / 5280.0


def build_snapshot(source) -> Snapshot:
    """Build an immutable Snapshot from a StaticSource or RuntimeSource."""
    net = source.network

    # Simulation-derived per-road volume (veh/hr); empty for a static source.
    volumes = source.road_volumes()
    roads = tuple(_road_snapshot(net, road, volumes)
                  for road in net.roads.values() if not road.is_preview)
    nodes = tuple(
        NodeSnapshot(id=nid,
                     is_intersection=net.is_intersection(nid),
                     control_type=node.data.get("control"),
                     position=(node.x, node.y))
        for nid, node in net.nodes.items())
    buildings = tuple(_building_snapshot(b) for b in net.buildings.values())
    vehicles = tuple(_vehicle_snapshot(v) for v in source.raw_vehicles())

    meta = SnapshotMeta(source_kind=source.kind,
                        is_running=source.is_running,
                        sim_time_hours=source.sim_time_hours,
                        tick=source.tick)
    return Snapshot(roads=roads, nodes=nodes, buildings=buildings,
                    vehicles=vehicles, meta=meta)


def _road_snapshot(net, road, volumes) -> RoadSnapshot:
    profile = get_road_profile(road)   # lane counts are scale-invariant
    geometry = net.geometry_for_road(road)
    centerline = geometry["sampled_points"]
    length_ft = _polyline_length(centerline)
    # Horizontal geometry from the road's three Bezier control points (endpoints
    # + control_point), in true feet. Exact plan-view facts; no vertical model.
    p0 = net.nodes[road.start_node_id].pos
    p2 = net.nodes[road.end_node_id].pos
    p1 = geometry["control_point"]
    # Optional road-classification fields ride in road.data["profile"]; absent
    # today (P1 not yet re-applied), so they normalize to None.
    pdata = road.data.get("profile") or {}
    return RoadSnapshot(
        id=road.id,
        length_ft=length_ft,
        lanes_forward=profile.lanes_forward(),
        lanes_reverse=profile.lanes_reverse(),
        start_node_id=road.start_node_id,
        end_node_id=road.end_node_id,
        functional_class=pdata.get("functional_class"),
        design_speed=pdata.get("design_speed"),
        context=pdata.get("context"),
        # Already veh/hr at the session boundary; None when unmeasured (static).
        observed_volume_vph=volumes.get(road.id),
        governing_curve_radius_ft=governing_curve_radius_ft(p0, p1, p2),
        horizontal_deflection_angle_deg=horizontal_deflection_deg(p0, p1, p2),
    )


def _building_snapshot(building) -> BuildingSnapshot:
    bt = BUILDING_TYPES.get(building.building_type)
    return BuildingSnapshot(
        id=building.id,
        building_type=building.building_type,
        category=bt.category if bt else None,
        connection_node_ids=tuple(building.connection_node_ids),
        capacity=bt.capacity if bt else None,
        is_residential=bool(bt and bt.category == RESIDENTIAL),
    )


def _vehicle_snapshot(v) -> VehicleSnapshot:
    # v is the session's plain-data vehicle dict (speed in ft/s).
    return VehicleSnapshot(
        id=v["id"],
        speed_mph=v["speed"] * FT_PER_S_TO_MPH,
        position=tuple(v["pos"]),
        dest_node_id=v.get("dest_node"),
        dest_building_id=v.get("dest_building"),
    )
