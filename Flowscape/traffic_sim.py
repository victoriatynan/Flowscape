"""
Traffic System: Dijkstra lane pathfinding + minimal vehicle traversal.

Validates the lane graph end-to-end: a single vehicle computes a lane path
ONCE (precomputed, deterministic Dijkstra) and then passively follows it --
no traffic rules, no decisions, no mid-route recalculation.

System flow:
    lane_graph.build_lane_graph()        node-level lane connections
        -> build_routing_graph()         directed lane graph {lane_id: edges}
        -> find_lane_path()              Dijkstra, uniform cost
        -> Vehicle (path = lane list)    lane-by-lane traversal
        -> node transitions validated against the lane-graph connections

Graph model:
  Lanes are the graph nodes. A directed lane is identified by
  lane_id = (road_id, "F"|"R", lane_index): forward lanes travel their
  road start->end, reverse lanes end->start. Each LaneConnection produced
  by lane_graph becomes a directed edge source.lane_id -> target.lane_id
  with uniform cost 1 for now; swap in lane length later if desired.

Traversal geometry:
  Roads stay visual-only; the simulation backbone is the lane polyline:
  the road centerline offset to the lane center (same sign convention as
  lane_graph/road_style), trimmed back to the junction mouths, and
  reversed for reverse-direction lanes. Between two lanes the vehicle
  crosses the junction along lane_graph.get_connection_curve(), the
  shared definition of junction connection geometry, used by
  the debug overlay, so what is drawn and what is driven can never
  diverge, and the vehicle never teleports laterally at a turn. The
  connection arc counts as the ENTRY of the next lane: that is the
  node-transition moment, where the move is validated against the
  lane-graph connection set (invalid -> state "blocked").

Strictly read-only on the RoadNetwork; nothing here is saved.
"""

import heapq
import math
import os
from dataclasses import dataclass, field

from lane_graph import build_lane_graph, get_connection_curve
from road_style import get_road_profile, offset_polyline

UNIFORM_EDGE_COST = 1.0
VEHICLE_SPEED_FT_S = 44.0      # ~30 mph
VEHICLE_LENGTH_FT = 14.0       # small car, real-world scale (world is feet)

# Top-down car sprite, source art pointing UP (head/windshield at the top,
# taillights at the bottom). The first existing candidate wins: a clean
# Affinity PNG export is preferred over the preview extracted from the
# .af working file.
_ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "2d Assets")
VEHICLE_SPRITE_CANDIDATES = [
    os.path.join(_ASSET_DIR, "smallcar-white.png"),
    os.path.join(_ASSET_DIR, "smallcar-white-extracted.png"),
]


def vehicle_sprite_path():
    """First existing vehicle sprite, or None (renderer falls back to a
    plain circle marker)."""
    for path in VEHICLE_SPRITE_CANDIDATES:
        if os.path.exists(path):
            return path
    return None

STATE_MOVING = "moving"
STATE_ARRIVED = "arrived"
STATE_BLOCKED = "blocked"

COLOR_PATH = (110, 130, 220)
COLOR_CURRENT_LANE = (255, 210, 90)
COLOR_NEXT_LANE = (90, 220, 255)
COLOR_TRANSITION = (240, 240, 240)
VEHICLE_COLORS = {
    STATE_MOVING: (90, 220, 120),
    STATE_ARRIVED: (180, 180, 180),
    STATE_BLOCKED: (255, 80, 80),
}
VEHICLE_RADIUS_FT = 5.0


# ----------------------------------------------------------------------
# Deterministic test map
# ----------------------------------------------------------------------

def create_lane_test_map():
    """Build and return a deterministic RoadNetwork for lane-graph /
    traversal validation:

      - two 4-way intersections (n2, n3) and two T-intersections (n5, n6)
      - 10 roads, including a 2+2-lane arterial (n1-n2-n3) and a curved
        segment (n5-n6)
      - six dead-end nodes (n1, n4, n7, n8, n10, n11) as clear start/end
        points; n10 -> n8 crosses a T and both 4-ways with turns.
    """
    from road_editor import RoadNetwork  # runtime import: avoids a module cycle

    net = RoadNetwork()
    n1 = net.add_node(-300, 0)
    n2 = net.add_node(0, 0)
    n3 = net.add_node(300, 0)
    n4 = net.add_node(600, 0)
    n5 = net.add_node(0, 300)
    n6 = net.add_node(300, 300)
    n7 = net.add_node(0, -300)
    n8 = net.add_node(300, -300)
    n10 = net.add_node(-300, 300)
    n11 = net.add_node(600, 300)

    arterial_w = net.add_road(n1.id, n2.id)
    arterial_e = net.add_road(n2.id, n3.id)
    net.add_road(n3.id, n4.id)
    net.add_road(n2.id, n5.id)
    net.add_road(n3.id, n6.id)
    net.add_road(n2.id, n7.id)
    net.add_road(n3.id, n8.id)
    net.add_road(n5.id, n6.id, curve_offset=(0.0, -90.0))  # curved segment
    net.add_road(n5.id, n10.id)
    net.add_road(n6.id, n11.id)

    for road in (arterial_w, arterial_e):
        road.data["profile"] = {"lane_count_forward": 2, "lane_count_reverse": 2}
    return net


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


# ----------------------------------------------------------------------
# Vehicle (minimal model)
# ----------------------------------------------------------------------

@dataclass
class Vehicle:
    """Passive follower of a precomputed lane sequence. Never recomputes
    its path or chooses lanes; at a lane end it transitions to the next
    lane in `path` (validated against the lane-graph connections) or
    stops with a debug failure state."""
    path: list                       # [lane_id, ...] from Dijkstra
    current_lane: tuple = None       # lane_id currently occupied/entered
    position_along_lane: float = 0.0  # 0 -> 1 within the current lane
    path_index: int = 0
    state: str = STATE_MOVING
    pos: tuple = (0.0, 0.0)
    heading: tuple = (1.0, 0.0)      # unit travel direction (for the sprite)
    speed: float = VEHICLE_SPEED_FT_S
    # Compiled traversal segments: [{"kind": "lane"|"connection",
    #   "lane_id", "points", "length", "node_pos"(connection only)}, ...]
    segments: list = field(default_factory=list)
    seg_index: int = 0
    seg_s: float = 0.0               # arc position within current segment
    # Destination building id (set for scheduled trips) so a building's
    # occupancy can be credited when this vehicle arrives.
    dest_building_id: int = None

    def _enter_segment(self, index, valid_edges):
        """Advance to segment `index`. Entering a connection segment IS the
        node transition: validate the lane switch and update path_index."""
        seg = self.segments[index]
        if seg["kind"] == "connection":
            prev_lane = self.current_lane
            next_lane = seg["lane_id"]
            if (prev_lane, next_lane) not in valid_edges:
                self.state = STATE_BLOCKED   # debug failure, vehicle stops
                return False
            self.current_lane = next_lane
            self.path_index = self.path.index(next_lane)
            self.position_along_lane = 0.0
        self.seg_index = index
        self.seg_s = 0.0
        return True

    def update(self, dt, valid_edges):
        if self.state != STATE_MOVING or not self.segments:
            return
        advance = self.speed * dt
        while advance > 0:
            seg = self.segments[self.seg_index]
            remaining = seg["length"] - self.seg_s
            if advance < remaining:
                self.seg_s += advance
                advance = 0
            else:
                advance -= remaining
                if self.seg_index + 1 >= len(self.segments):
                    self.seg_s = seg["length"]
                    self.state = STATE_ARRIVED
                    self.position_along_lane = 1.0
                    break
                if not self._enter_segment(self.seg_index + 1, valid_edges):
                    break
        seg = self.segments[self.seg_index]
        self.pos = _point_at_arc(seg["points"], self.seg_s)
        self.heading = _direction_at_arc(seg["points"], self.seg_s)
        if seg["kind"] == "lane" and seg["length"] > 0:
            self.position_along_lane = self.seg_s / seg["length"]

    @property
    def next_lane(self):
        if self.path_index + 1 < len(self.path):
            return self.path[self.path_index + 1]
        return None


# ----------------------------------------------------------------------
# Simulation manager (owns vehicles, builds paths, emits debug visuals)
# ----------------------------------------------------------------------

class TrafficSimulation:
    """Single-owner of vehicles for the editor. Paths are computed ONCE at
    spawn time from the current network; vehicles then follow them blindly,
    by design never recomputed mid-travel."""

    def __init__(self, network):
        self.network = network
        self.vehicles = []
        self._valid_edges = set()
        # Routing-graph cache for batch trip spawns (see prepare_routes).
        self._edges = None
        self._turns = None
        self._connections = None

    def reset(self):
        self.vehicles = []
        self._valid_edges = set()
        self._edges = None
        self._turns = None
        self._connections = None

    def spawn_vehicle(self, start_node_id, dest_node_id):
        """Compute a lane path start->dest and spawn a vehicle on it.
        Returns (vehicle, message); vehicle is None when no path exists."""
        edges, turns, connections = build_routing_graph(self.network)
        path = find_lane_path(edges,
                              lanes_departing_node(self.network, start_node_id),
                              lanes_arriving_node(self.network, dest_node_id))
        if path is None:
            return None, (f"No lane path from node {start_node_id} "
                          f"to node {dest_node_id}")

        vehicle = self._spawn_on_path(path, connections)
        self._valid_edges = set(turns.keys())
        turn_summary = [turns[(path[i], path[i + 1])]
                        for i in range(len(path) - 1)]
        return vehicle, (f"Path: {len(path)} lanes, "
                         f"turns: {', '.join(turn_summary) or 'none'}")

    def _spawn_on_path(self, path, connections):
        """Compile a lane path into traversal segments, create the Vehicle,
        add it, and return it. Caller owns self._valid_edges. Shared by the
        single-vehicle spawn_vehicle() and the batch spawn_trip()."""
        segments = []
        prev_lane = None
        for lane_id in path:
            pts = lane_polyline(self.network, lane_id)
            if prev_lane is not None:
                # Junction transition geometry comes from the shared
                # curve generator, the identical
                # curve the lane-graph overlay draws for this connection.
                conn = connections[(prev_lane, lane_id)]
                node = self.network.nodes[lane_arrival_node(self.network, prev_lane)]
                curve = get_connection_curve(conn.source, conn.target, node)
                segments.append({"kind": "connection", "lane_id": lane_id,
                                 "points": curve, "node_pos": node.pos,
                                 "length": _polyline_length(curve)})
            segments.append({"kind": "lane", "lane_id": lane_id,
                             "points": pts, "length": _polyline_length(pts)})
            prev_lane = lane_id

        vehicle = Vehicle(path=path, current_lane=path[0], segments=segments,
                          pos=segments[0]["points"][0],
                          heading=_direction_at_arc(segments[0]["points"], 0.0))
        self.vehicles.append(vehicle)
        return vehicle

    def prepare_routes(self):
        """Build the routing graph ONCE, to be reused across many trip
        spawns in a batch (see spawn_trip). Cheap per-spawn cost afterward."""
        self._edges, self._turns, self._connections = build_routing_graph(self.network)
        self._valid_edges = set(self._turns.keys())

    def spawn_trip(self, start_node_id, dest_node_id, dest_building_id=None):
        """Spawn one vehicle for a scheduled trip using the cached routing
        graph (prepare_routes() is called lazily if needed). Returns the
        Vehicle, or None when no path exists. Quiet: no status string, since
        this is called many times by the scheduler. `dest_building_id` rides
        along so the destination building's occupancy can be credited on
        arrival."""
        if self._edges is None:
            self.prepare_routes()
        path = find_lane_path(self._edges,
                              lanes_departing_node(self.network, start_node_id),
                              lanes_arriving_node(self.network, dest_node_id))
        if path is None:
            return None
        vehicle = self._spawn_on_path(path, self._connections)
        vehicle.dest_building_id = dest_building_id
        return vehicle

    def cull_arrived(self):
        """Drop vehicles that have reached their destination so a long trip
        run does not accumulate stationary cars on screen. Returns the list of
        culled (arrived) vehicles so callers can credit building occupancy."""
        arrived = [v for v in self.vehicles if v.state == STATE_ARRIVED]
        if arrived:
            self.vehicles = [v for v in self.vehicles if v.state != STATE_ARRIVED]
        return arrived

    def toggle_demo_vehicle(self):
        """Editor convenience (V key): spawn one vehicle between a
        deterministic pair of dead-end nodes (first by id -> farthest from
        it), or clear the current vehicle."""
        if self.vehicles:
            self.reset()
            return "Vehicle cleared"
        dead_ends = sorted(
            (n for n in self.network.nodes.values()
             if len([r for r in self.network.roads_for_node(n.id)
                     if not r.is_preview]) == 1),
            key=lambda n: n.id)
        if len(dead_ends) >= 2:
            start = dead_ends[0]
            dest = max(dead_ends[1:],
                       key=lambda n: (math.hypot(n.x - start.x, n.y - start.y),
                                      -n.id))
        elif len(self.network.nodes) >= 2:
            ids = sorted(self.network.nodes.keys())
            start = self.network.nodes[ids[0]]
            dest = self.network.nodes[ids[-1]]
        else:
            return "Need at least 2 nodes for a vehicle"
        vehicle, message = self.spawn_vehicle(start.id, dest.id)
        return f"Vehicle {start.id}->{dest.id}: {message}"

    def update(self, dt):
        for vehicle in self.vehicles:
            vehicle.update(dt, self._valid_edges)

    def visual_layers(self, show_paths=True):
        """Visualization emitted as the editor's generic visual-layer shape
        dicts. With `show_paths` (default), the route overlay is included:
        the full path polylines, node-transition markers, and the current/
        next-lane highlights. With show_paths=False, ONLY the vehicles (car
        sprites / state markers) are emitted: paths off, cars on."""
        layers = []
        for vehicle in self.vehicles:
            if show_paths:
                for seg in vehicle.segments:
                    layers.append({"shape": "line", "points": seg["points"],
                                   "color": COLOR_PATH, "width": 2})
                    if seg["kind"] == "connection":
                        layers.append({"shape": "circle", "pos": seg["node_pos"],
                                       "radius": 4, "color": COLOR_TRANSITION,
                                       "alpha": 120})
                for lane_id, color in ((vehicle.current_lane, COLOR_CURRENT_LANE),
                                       (vehicle.next_lane, COLOR_NEXT_LANE)):
                    if lane_id is None:
                        continue
                    for seg in vehicle.segments:
                        if seg["kind"] == "lane" and seg["lane_id"] == lane_id:
                            layers.append({"shape": "line", "points": seg["points"],
                                           "color": color, "width": 4})
            sprite = vehicle_sprite_path()
            if sprite is not None:
                # Non-moving debug states stay visible as a translucent
                # halo under the sprite (arrived = gray, blocked = red).
                if vehicle.state != STATE_MOVING:
                    layers.append({"shape": "circle", "pos": vehicle.pos,
                                   "radius": VEHICLE_LENGTH_FT * 0.65,
                                   "color": VEHICLE_COLORS[vehicle.state],
                                   "alpha": 120})
                layers.append({"shape": "sprite", "pos": vehicle.pos,
                               "heading": vehicle.heading,
                               "length_ft": VEHICLE_LENGTH_FT,
                               "image": sprite})
            else:
                layers.append({"shape": "circle", "pos": vehicle.pos,
                               "radius": VEHICLE_RADIUS_FT,
                               "color": VEHICLE_COLORS[vehicle.state],
                               "alpha": 255})
        return layers
