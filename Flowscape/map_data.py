"""
Data System: JSON save/load for the map.

Strict separation:
  - Geometry system (road_geometry.py)        : curves, edges, polygons
  - Data system (this file)                   : nodes, roads, zones -> JSON
  - Rendering system (road_editor.py renderer): visual output
  - Simulation system (future)                : traffic logic

Only LOGICAL data is saved (positions in feet, curvature, width, lane
count, zone boundaries, plus each object's free-form 'data' dict for future
fields like traffic-light state). Anything derivable (sampled points,
control points, road polygons, edge points) is regenerated on load via
compute_road_geometry(), so the save format never needs to change when the
geometry/rendering systems change.
"""

import json

from buildings import Building
from road_geometry import Node, Road, Zone, compute_road_geometry

SCHEMA_VERSION = 1


def node_to_dict(node):
    return {
        "id": node.id,
        "x": node.x,
        "y": node.y,
        "type": node.type,
        "data": node.data,
    }


def node_from_dict(d):
    return Node(id=d["id"], x=d["x"], y=d["y"],
                 type=d.get("type", "road_node"), data=d.get("data", {}))


def road_to_dict(road):
    return {
        "id": road.id,
        "start_node_id": road.start_node_id,
        "end_node_id": road.end_node_id,
        "curve_offset": list(road.curve_offset),
        "width": road.width,
        "lane_count": road.lane_count,
        "data": road.data,
    }


def road_from_dict(d):
    return Road(
        id=d["id"],
        start_node_id=d["start_node_id"],
        end_node_id=d["end_node_id"],
        curve_offset=tuple(d.get("curve_offset", (0.0, 0.0))),
        width=d.get("width", 12.0),
        lane_count=d.get("lane_count", 1),
        data=d.get("data", {}),
    )


def zone_to_dict(zone):
    return {
        "id": zone.id,
        "type": zone.type,
        "boundary_points": [list(p) for p in zone.boundary_points],
        "data": zone.data,
    }


def zone_from_dict(d):
    return Zone(
        id=d["id"],
        type=d["type"],
        boundary_points=[tuple(p) for p in d.get("boundary_points", [])],
        data=d.get("data", {}),
    )


def building_to_dict(building):
    """Save only the placed-instance facts: which type, where, and which road
    nodes it attaches to. Category/size/capacity/hours are NOT saved; they
    come from the BuildingType registry (destinations.BUILDING_TYPES). No
    dynamic simulation state is saved."""
    return {
        "id": building.id,
        "building_type": building.building_type,
        "x": building.x,
        "y": building.y,
        "connection_node_ids": list(building.connection_node_ids),
        "data": building.data,
    }


def building_from_dict(d):
    return Building(
        id=d["id"],
        building_type=d.get("building_type", "House"),
        x=d.get("x", 0.0),
        y=d.get("y", 0.0),
        connection_node_ids=list(d.get("connection_node_ids", [])),
        data=d.get("data", {}),
    )


def map_to_dict(network):
    """Build the JSON-serializable dict for an entire RoadNetwork."""
    return {
        "version": SCHEMA_VERSION,
        "nodes": {str(n.id): node_to_dict(n) for n in network.nodes.values()},
        "roads": {str(r.id): road_to_dict(r) for r in network.roads.values()},
        "zones": {str(z.id): zone_to_dict(z) for z in network.zones.values()},
        "buildings": {str(b.id): building_to_dict(b)
                      for b in network.buildings.values()},
    }


def save_map(network, filepath):
    with open(filepath, "w") as f:
        json.dump(map_to_dict(network), f, indent=2)


def validate_network(network, verbose=True):
    """
    Debug-only consistency check, run after a load. Returns a list of
    warning strings (empty if everything resolves cleanly).

    Checks:
      - every road's start/end node id exists in network.nodes
      - warns about orphan nodes (road_nodes with zero connected roads)
    """
    warnings = []

    for road in network.roads.values():
        if road.start_node_id not in network.nodes:
            warnings.append(
                f"Road {road.id}: start_node_id {road.start_node_id} "
                f"does not exist (broken connection)")
        if road.end_node_id not in network.nodes:
            warnings.append(
                f"Road {road.id}: end_node_id {road.end_node_id} "
                f"does not exist (broken connection)")

    connected_node_ids = set()
    for road in network.roads.values():
        connected_node_ids.add(road.start_node_id)
        connected_node_ids.add(road.end_node_id)

    for node in network.nodes.values():
        if node.type == "road_node" and node.id not in connected_node_ids:
            warnings.append(f"Node {node.id}: orphan road_node (no roads attached)")

    if verbose:
        for w in warnings:
            print(f"[load_map] WARNING: {w}")

    return warnings


def load_map(network, filepath):
    """
    Reset and repopulate `network` from a JSON file, using a strict,
    deterministic rebuild order so saved data (IDs + numbers) maps back to
    a fully-connected runtime graph (objects + references + geometry):

      1. Clear all runtime state (empty world).
      2. Load nodes into network.nodes, keyed by node_id.
      3. Load zones (independent polygons; no dependency on roads/nodes).
      4. Load roads, referencing nodes ONLY by start_node_id/end_node_id
         (looked up from network.nodes, never stored as direct
         object references in JSON).
      5. Validate the graph (missing endpoints, orphan nodes).
      6. Rebuild geometry (spline curve, control point, edges, polygon)
         for every road from its saved curve_offset/width, using the
         unmodified compute_road_geometry().

    Step 6 is what guarantees control points and road shapes restore
    correctly: nothing about geometry is itself saved, it's fully
    regenerated from start/end node positions + curve_offset.
    """
    with open(filepath, "r") as f:
        raw = json.load(f)

    # Step 1: empty world state.
    network.nodes.clear()
    network.roads.clear()
    network.zones.clear()
    network.buildings.clear()

    # Step 2: nodes, keyed by id.
    max_node_id = 0
    for d in raw.get("nodes", {}).values():
        node = node_from_dict(d)
        network.nodes[node.id] = node
        max_node_id = max(max_node_id, node.id)

    # Step 3: zones (independent polygons, no road/node dependency).
    max_zone_id = 0
    for d in raw.get("zones", {}).values():
        zone = zone_from_dict(d)
        network.zones[zone.id] = zone
        max_zone_id = max(max_zone_id, zone.id)

    # Step 4: roads, connected to nodes purely via id lookup.
    max_road_id = 0
    for d in raw.get("roads", {}).values():
        road = road_from_dict(d)
        network.roads[road.id] = road
        max_road_id = max(max_road_id, road.id)

    # Buildings: lightweight instances referencing the BuildingType registry.
    # Loaded after nodes so their connection_node_ids resolve against a
    # populated graph (the lookup itself is done by consumers, not here).
    max_building_id = 0
    for d in raw.get("buildings", {}).values():
        building = building_from_dict(d)
        network.buildings[building.id] = building
        max_building_id = max(max_building_id, building.id)

    network._next_node_id = max_node_id + 1
    network._next_road_id = max_road_id + 1
    network._next_zone_id = max_zone_id + 1
    network._next_building_id = max_building_id + 1

    # Step 5: validate the rebuilt graph.
    validate_network(network)

    # Step 6: rebuild geometry for every road from node positions + curve_offset.
    for road in network.roads.values():
        if road.start_node_id not in network.nodes or road.end_node_id not in network.nodes:
            continue  # already warned in validate_network; nothing to rebuild
        start = network.nodes[road.start_node_id].pos
        end = network.nodes[road.end_node_id].pos
        geometry = compute_road_geometry(start, end, road.curve_offset, road.width)
        road.left_edge_points = geometry["left_edge_points"]
        road.right_edge_points = geometry["right_edge_points"]
        road.road_polygon = geometry["road_polygon"]
