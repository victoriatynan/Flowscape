"""
Lane routing: the directed lane graph, deterministic Dijkstra pathfinding,
and lane traversal geometry (polylines, arc-length sampling).

Pure graph/geometry logic with no per-frame state -- extracted verbatim from
traffic_sim.py (REFACTOR_PLAN.md step 6) so routing is importable and testable
without the Vehicle/TrafficSimulation runtime.
"""

import heapq
import math

from lane_graph import build_lane_graph
from road_style import get_road_profile, offset_polyline

UNIFORM_EDGE_COST = 1.0


# ----------------------------------------------------------------------
# Routing graph (lanes as nodes) + Dijkstra
# ----------------------------------------------------------------------

def build_routing_graph(network):
    """Directed lane graph from the node-level lane connections.

    Returns (edges, turns, connections):
      edges: {lane_id: [(next_lane_id, cost), ...]}  (sorted, deterministic)
      turns: {(lane_id, next_lane_id): turn_type}    (for debug/validation)
      connections: {(lane_id, next_lane_id): LaneConnection}, which carries the
        LaneEnds whose mouth positions feed get_connection_curve(), so
        traversal geometry comes from the same objects as the lane graph.
    """
    node_graph = build_lane_graph(network)
    edges = {}
    turns = {}
    connections = {}
    for entry in node_graph.values():
        for conn in entry["connections"]:
            src, dst = conn.source.lane_id, conn.target.lane_id
            edges.setdefault(src, []).append((dst, UNIFORM_EDGE_COST))
            turns[(src, dst)] = conn.turn_type
            connections[(src, dst)] = conn
    for lane_id in edges:
        edges[lane_id].sort()
    return edges, turns, connections


def lanes_departing_node(network, node_id):
    """Directed lanes that leave `node_id` (covers dead ends, which have no
    entry in the node-level lane graph)."""
    lanes = []
    for road in sorted(network.roads_for_node(node_id), key=lambda r: r.id):
        if road.is_preview or road.start_node_id == road.end_node_id:
            continue
        profile = get_road_profile(road)
        if road.start_node_id == node_id:      # forward lanes depart here
            lanes += [(road.id, "F", k) for k in range(profile.lanes_forward())]
        if road.end_node_id == node_id:        # reverse lanes depart here
            lanes += [(road.id, "R", k) for k in range(profile.lanes_reverse())]
    return lanes


def lanes_arriving_node(network, node_id):
    """Directed lanes that end at `node_id`."""
    lanes = []
    for road in sorted(network.roads_for_node(node_id), key=lambda r: r.id):
        if road.is_preview or road.start_node_id == road.end_node_id:
            continue
        profile = get_road_profile(road)
        if road.end_node_id == node_id:        # forward lanes arrive here
            lanes += [(road.id, "F", k) for k in range(profile.lanes_forward())]
        if road.start_node_id == node_id:      # reverse lanes arrive here
            lanes += [(road.id, "R", k) for k in range(profile.lanes_reverse())]
    return lanes


def find_lane_path(edges, start_lanes, goal_lanes):
    """Deterministic multi-source/multi-target Dijkstra over the lane
    graph. Uniform edge cost; ties broken by lane_id ordering (tuple
    comparison), so equal-length routes always resolve the same way.
    Returns the lane_id sequence [start_lane, ..., goal_lane], or None."""
    goal_set = set(goal_lanes)
    if not goal_set:
        return None
    dist = {}
    prev = {}
    heap = []
    for lane in sorted(set(start_lanes)):
        dist[lane] = 0.0
        heapq.heappush(heap, (0.0, lane))
        if lane in goal_set:
            return [lane]
    while heap:
        d, lane = heapq.heappop(heap)
        if d > dist.get(lane, math.inf):
            continue
        if lane in goal_set:
            path = [lane]
            while lane in prev:
                lane = prev[lane]
                path.append(lane)
            path.reverse()
            return path
        for nxt, cost in edges.get(lane, ()):
            nd = d + cost
            if nd < dist.get(nxt, math.inf):
                dist[nxt] = nd
                prev[nxt] = lane
                heapq.heappush(heap, (nd, nxt))
    return None


# ----------------------------------------------------------------------
# Lane traversal geometry
# ----------------------------------------------------------------------

def _trim_polyline(points, start_trim, end_trim):
    """Arc-length trim from both ends (local copy of the editor's helper,
    kept here so this module never imports the editor)."""
    pts = list(points)
    for from_start, trim in ((True, start_trim), (False, end_trim)):
        remaining = trim
        while remaining > 0 and len(pts) >= 2:
            a, b = (pts[0], pts[1]) if from_start else (pts[-1], pts[-2])
            seg = math.hypot(b[0] - a[0], b[1] - a[1])
            if seg > remaining:
                t = remaining / seg
                moved = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                if from_start:
                    pts[0] = moved
                else:
                    pts[-1] = moved
                break
            remaining -= seg
            pts.pop(0 if from_start else -1)
    return pts if len(pts) >= 2 else list(points)


def lane_polyline(network, lane_id):
    """World-space centerline of one directed lane: road centerline trimmed
    to the junction mouths, then offset to the lane center, ordered in
    travel direction (reversed for "R" lanes).

    Trim-then-offset (not offset-then-trim) on purpose: it makes the lane
    endpoints coincide EXACTLY with the LaneEnd mouth positions lane_graph
    computes (the same points get_connection_curve() starts and ends at)
    so lane segments and junction connection curves join with zero gap.
    """
    road_id, direction, lane_index = lane_id
    road = network.roads[road_id]
    pts = network.geometry_for_road(road)["sampled_points"]
    profile = get_road_profile(road)
    sign = 1.0 if direction == "F" else -1.0
    offset = sign * (profile.median_width / 2.0
                     + (lane_index + 0.5) * profile.lane_width)
    trimmed = _trim_polyline(pts,
                             network.road_trim_at_node(road, road.start_node_id),
                             network.road_trim_at_node(road, road.end_node_id))
    lane_pts = offset_polyline(trimmed, offset)
    if direction == "R":
        lane_pts = list(reversed(lane_pts))
    return lane_pts


def lane_arrival_node(network, lane_id):
    """Node id a directed lane arrives at."""
    road = network.roads[lane_id[0]]
    return road.end_node_id if lane_id[1] == "F" else road.start_node_id


def _polyline_length(points):
    return sum(math.hypot(points[i + 1][0] - points[i][0],
                          points[i + 1][1] - points[i][1])
               for i in range(len(points) - 1))


def _point_at_arc(points, s):
    """Position at arc length s along a polyline (clamped to the ends)."""
    if s <= 0:
        return points[0]
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        seg = math.hypot(b[0] - a[0], b[1] - a[1])
        if seg >= s and seg > 0:
            t = s / seg
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        s -= seg
    return points[-1]


def _direction_at_arc(points, s):
    """Unit travel direction at arc length s along a polyline (the segment
    containing s; clamped to the first/last segment at the ends)."""
    s = max(0.0, s)
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        seg = math.hypot(b[0] - a[0], b[1] - a[1])
        if seg > 0 and (seg >= s or i == len(points) - 2):
            return ((b[0] - a[0]) / seg, (b[1] - a[1]) / seg)
        s -= seg
    return (1.0, 0.0)
