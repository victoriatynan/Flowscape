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

from lane_graph import get_connection_curve
# Routing (extracted to routing.py; re-imported so existing
# `from traffic_sim import find_lane_path, ...` callers keep working).
from routing import (UNIFORM_EDGE_COST, build_routing_graph,
                     lanes_departing_node, lanes_arriving_node, find_lane_path,
                     _trim_polyline, lane_polyline, lane_arrival_node,
                     _polyline_length, _point_at_arc, _direction_at_arc)
from road_style import get_road_profile, offset_polyline
from vehicle_dynamics import (integrate_speed, motion_state,
                              DEFAULT_ACCELERATION_RATE, DEFAULT_BRAKING_RATE,
                              ACCELERATING, CRUISING, BRAKING)
from vehicle_decision import (compute_decisions, binding_rule, approach_info,
                              DecisionContext)
from intersection_control import IntersectionControl

# Default cruising speed -- the desired_speed a vehicle targets when nothing is
# slowing it down. A future decision layer will lower desired_speed below this
# (car-following, lights); the dynamics layer ramps current_speed toward it.
VEHICLE_SPEED_FT_S = 44.0      # ~30 mph
VEHICLE_LENGTH_FT = 14.0       # small car, real-world scale (world is feet)
# Render-only magnification for car sprites/markers. Purely cosmetic: it scales
# how big vehicles are DRAWN, never the physical length used by spawn
# clearance, perception, or car-following (those all key off VEHICLE_LENGTH_FT).
VEHICLE_RENDER_SCALE = 2.0
# Spawn gating: a trip is only released onto its departing lane when the lane's
# start point is clear of other cars by this margin. Vehicles accelerate from
# rest, so a leader that departed a moment ago is still sitting near the start;
# without this gate the new car lands on top of it (overlap < VEHICLE_LENGTH).
# This is a SPAWNER concern only -- it decides WHETHER to place a car, never how
# one moves; in-traffic spacing is the decision layer's car-following rule.
SPAWN_CLEARANCE_FT = 1.6 * VEHICLE_LENGTH_FT

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

# Perception debug overlay (optional): the leader-link color encodes the
# closing state -- warm = approaching (gap shrinking), cyan = separating,
# gray = steady (equal speeds).
COLOR_PERCEPTION_APPROACH = (255, 120, 90)
COLOR_PERCEPTION_SEPARATE = (110, 180, 255)
COLOR_PERCEPTION_STEADY = (200, 200, 200)

# Dynamics debug overlay (optional): the speed-readout color encodes the
# derived motion state -- green = accelerating, gray = cruising at target,
# red = braking.
DYNAMICS_STATE_COLORS = {
    ACCELERATING: (90, 220, 120),
    CRUISING: (210, 210, 210),
    BRAKING: (255, 90, 90),
}
DYNAMICS_STATE_GLYPHS = {ACCELERATING: "^", CRUISING: "=", BRAKING: "v"}

# Decision debug overlay (optional): the readout color shows which rule is
# currently binding the desired_speed -- gray = free cruise, amber = held back
# by the following-distance rule. New rules can add their own color here.
DECISION_RULE_COLORS = {
    "cruise": (170, 170, 170),
    "follow": (255, 190, 70),
    "approach": (255, 110, 60),     # slowing for a controlled junction ahead
}
COLOR_DECISION_DEFAULT = (200, 200, 200)
# Stop-line marker / approach link for the intersection-approach overlay.
COLOR_STOP_LINE = (235, 80, 80)


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
    from road_network import RoadNetwork  # local import: keeps module load light

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
# Vehicle (minimal model)
# ----------------------------------------------------------------------

@dataclass
class Vehicle:
    """Passive follower of a precomputed lane sequence. Never recomputes
    its path or chooses lanes; at a lane end it transitions to the next
    lane in `path` (validated against the lane-graph connections) or
    stops with a debug failure state."""
    path: list                       # [lane_id, ...] from Dijkstra
    vid: int = 0                     # stable per-run id (spawn order; deterministic)
    current_lane: tuple = None       # lane_id currently occupied/entered
    position_along_lane: float = 0.0  # 0 -> 1 within the current lane
    path_index: int = 0
    state: str = STATE_MOVING
    pos: tuple = (0.0, 0.0)
    heading: tuple = (1.0, 0.0)      # unit travel direction (for the sprite)
    # --- Motion state ---
    # current_speed starts at rest; the dynamics layer ramps it toward
    # desired_speed each frame. cruise_speed is the LOGICAL source of truth for
    # this vehicle's free-flow target (how fast it wants to go unconstrained).
    # desired_speed is a per-frame OUTPUT of the decision layer (a one-field
    # handoff to dynamics, recomputed every frame -- not durable state); the
    # decision layer is the ONLY writer of desired_speed and influences motion
    # solely through it. accel/brake are the per-vehicle kinematic limits. The
    # accel/brake STATE is not stored; it is derived via motion_state().
    current_speed: float = 0.0
    cruise_speed: float = VEHICLE_SPEED_FT_S
    desired_speed: float = VEHICLE_SPEED_FT_S
    acceleration_rate: float = DEFAULT_ACCELERATION_RATE
    braking_rate: float = DEFAULT_BRAKING_RATE
    # Compiled traversal segments: [{"kind": "lane"|"connection",
    #   "lane_id", "points", "length", "node_pos"(connection only)}, ...]
    segments: list = field(default_factory=list)
    seg_index: int = 0
    seg_s: float = 0.0               # arc position within current segment
    # Destination building id (set for scheduled trips) so a building's
    # occupancy can be credited when this vehicle arrives.
    dest_building_id: int = None
    # Destination node id, kept so the lateral lane-change pass can recompute a
    # valid downstream route from a newly chosen lane to the same destination
    # (the only re-routing the sim ever does; normal traversal never reroutes).
    dest_node_id: int = None
    # Seconds remaining before this vehicle may consider another lane change.
    # Set after a merge so cars commit to a lane instead of weaving; decremented
    # by the lane-change pass each frame. Transient; not saved.
    lane_change_cooldown: float = 0.0
    # Transient per-frame sensing result (vehicle_perception.Perception):
    # the leader ahead + gap, recomputed every frame. NEVER read by update()
    # or any movement code, and never saved -- perception only senses.
    perception: object = None
    # Transient: the intersection node id this vehicle is currently registered
    # inside (set by movement on entering a junction connection segment, cleared
    # on exit), or None. Bookkeeping for the intersection controller; not saved.
    junction_node: object = None

    def _enter_segment(self, index, valid_edges, intersections):
        """Advance to segment `index`. Entering a connection segment IS the
        junction transition: validate the lane switch, then REQUEST PERMISSION
        from the intersection controller before committing. Entering the lane
        that follows a connection means we have cleared that junction, so we
        deregister. Returns False (without advancing) if the lane switch is
        invalid or permission is denied -- the caller then holds the vehicle at
        the junction mouth."""
        seg = self.segments[index]
        if seg["kind"] == "connection":
            prev_lane = self.current_lane
            next_lane = seg["lane_id"]
            if (prev_lane, next_lane) not in valid_edges:
                self.state = STATE_BLOCKED   # debug failure, vehicle stops
                return False
            node_id = seg["node_id"]
            # ALL junction entry passes through the controller: ask first.
            if not intersections.can_enter(node_id, self):
                return False                 # denied: wait at the junction mouth
            intersections.vehicle_enter(node_id, self)
            self.junction_node = node_id
            self.current_lane = next_lane
            self.path_index = self.path.index(next_lane)
            self.position_along_lane = 0.0
        elif self.junction_node is not None:
            # Entering a lane after a connection: we have left that junction.
            intersections.vehicle_exit(self.junction_node, self)
            self.junction_node = None
        self.seg_index = index
        self.seg_s = 0.0
        return True

    def move(self, dt, valid_edges, intersections):
        """MOVEMENT layer: advance along the compiled segment chain by the
        distance current_speed covers this step, handling lane/junction
        transitions and arrival. Path following ONLY -- it reads current_speed
        but never changes it and knows nothing about WHY the speed is what it is
        (that belongs to the dynamics/decision layers). Every junction entry is
        gated by `intersections` (the IntersectionControl), so any intersection
        type plugs in WITHOUT changing this traversal. The geometry traversal is
        otherwise identical to the original constant-speed model; only the source
        of `advance` differs (current_speed, set by dynamics last frame)."""
        if self.state != STATE_MOVING or not self.segments:
            return
        advance = self.current_speed * dt
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
                if not self._enter_segment(self.seg_index + 1, valid_edges, intersections):
                    # Hard stop at the junction mouth (entry denied) or a dead
                    # blocked state. The vehicle physically stops here, so its
                    # speed is 0 -- movement keeps current_speed consistent with
                    # the (lack of) motion, which also lets followers car-follow
                    # a held vehicle correctly (a stopped leader, not a phantom
                    # moving one). This is the one place movement writes
                    # current_speed: a hard external stop, distinct from the
                    # dynamics layer's smooth integration toward desired_speed.
                    # (Decelerating SMOOTHLY before the line is a future decision
                    # rule; this is the safety backstop.)
                    self.seg_s = seg["length"]
                    self.current_speed = 0.0
                    break
        seg = self.segments[self.seg_index]
        self.pos = _point_at_arc(seg["points"], self.seg_s)
        self.heading = _direction_at_arc(seg["points"], self.seg_s)
        if seg["kind"] == "lane" and seg["length"] > 0:
            self.position_along_lane = self.seg_s / seg["length"]

    def integrate_dynamics(self, dt):
        """DYNAMICS layer: ramp current_speed toward desired_speed for the next
        movement step. A thin delegate to the pure vehicle_dynamics integrator;
        it carries no policy and reads only this vehicle's own speed state. The
        decision layer influences it SOLELY through desired_speed, so adding new
        decision rules never touches this code."""
        if self.state != STATE_MOVING:
            return
        self.current_speed = integrate_speed(
            self.current_speed, self.desired_speed,
            self.acceleration_rate, self.braking_rate, dt)

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
        # Stable per-run vehicle ids, assigned in spawn order (deterministic:
        # spawn order is itself deterministic). Lets clients track a vehicle
        # across snapshots (e.g. for render interpolation).
        self._next_vid = 1
        # Routing-graph cache for batch trip spawns (see prepare_routes).
        self._edges = None
        self._turns = None
        self._connections = None
        # Junction gatekeeping: one controller per controlled intersection.
        # Rebuilt from topology at reset / route prep / spawn; movement consults
        # it for every junction entry.
        self.intersections = IntersectionControl(network)

    def reset(self):
        self.vehicles = []
        self._valid_edges = set()
        self._next_vid = 1
        self._edges = None
        self._turns = None
        self._connections = None
        self.intersections.rebuild()

    def spawn_vehicle(self, start_node_id, dest_node_id):
        """Compute a lane path start->dest and spawn a vehicle on it.
        Returns (vehicle, message); vehicle is None when no path exists."""
        edges, turns, connections = build_routing_graph(self.network)
        self.intersections.rebuild()
        # Cache the routing graph so the lane-change pass can re-route the demo
        # car too (spawn_trip already caches; this matches that for spawn_vehicle).
        self._edges, self._turns, self._connections = edges, turns, connections
        path = find_lane_path(edges,
                              lanes_departing_node(self.network, start_node_id),
                              lanes_arriving_node(self.network, dest_node_id))
        if path is None:
            return None, (f"No lane path from node {start_node_id} "
                          f"to node {dest_node_id}")

        vehicle = self._spawn_on_path(path, connections, dest_node_id=dest_node_id)
        self._valid_edges = set(turns.keys())
        if vehicle is None:
            return None, (f"Spawn blocked: node {start_node_id}'s departing "
                          f"lane is occupied near the start")
        turn_summary = [turns[(path[i], path[i + 1])]
                        for i in range(len(path) - 1)]
        return vehicle, (f"Path: {len(path)} lanes, "
                         f"turns: {', '.join(turn_summary) or 'none'}")

    def _spawn_point_clear(self, spawn_pos):
        """SPAWNER gate: is the departing lane's start region free for a new
        car? True when no existing vehicle sits within SPAWN_CLEARANCE_FT of
        `spawn_pos`. Because cars accelerate from rest, a car that just left is
        still near the start; placing another there would overlap it. Purely a
        placement decision -- nothing here touches how vehicles move."""
        sx, sy = spawn_pos
        return all(math.hypot(v.pos[0] - sx, v.pos[1] - sy) >= SPAWN_CLEARANCE_FT
                   for v in self.vehicles)

    def _compile_segments(self, path, connections, first_segment=None):
        """Compile a lane path into the traversal segment chain
        [{"kind": "lane"|"connection", ...}, ...]. Shared by spawn and the
        lane-change re-route, so both produce identical lane/connection
        geometry and validation keys.

        `first_segment`, if given, REPLACES the lane segment for path[0] (the
        lane-change pass passes a pre-built merged remainder that starts at the
        car's current position rather than the lane start); the connection that
        would precede path[0] is omitted, since the car is already on path[0]."""
        segments = []
        prev_lane = None
        for idx, lane_id in enumerate(path):
            if idx == 0 and first_segment is not None:
                segments.append(first_segment)
                prev_lane = lane_id
                continue
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
                                 "node_id": node.id,
                                 # lane_graph's turn classification for this
                                 # movement, so the intersection controllers can
                                 # build first-class Movement objects.
                                 "turn_type": conn.turn_type,
                                 "length": _polyline_length(curve)})
            segments.append({"kind": "lane", "lane_id": lane_id,
                             "points": pts, "length": _polyline_length(pts)})
            prev_lane = lane_id
        return segments

    def _spawn_on_path(self, path, connections, dest_node_id=None):
        """Compile a lane path into traversal segments, create the Vehicle at the
        first clear slot along the departing lane, add it, and return it. Shared
        by spawn_vehicle() and spawn_trip(). Returns None only when the WHOLE
        departing lane is occupied. `dest_node_id` rides along for the
        lane-change re-route.

        SPAWN ZONE: rather than only the lane start, a car takes the first slot
        (stepping back by SPAWN_CLEARANCE_FT) that is clear of other cars, so a
        burst fills the departing lane nose-to-tail instead of one car at a time.
        This raises a single entrance/driveway's egress throughput to about
        lane_length / SPAWN_CLEARANCE_FT cars -- without ever overlapping (each
        slot is clearance-checked) and without adding junctions. A longer
        driveway is therefore a bigger off-road staging zone."""
        segments = self._compile_segments(path, connections)
        pts = segments[0]["points"]
        length = segments[0]["length"]
        spawn_arc = None
        arc = 0.0
        while arc <= length:
            if self._spawn_point_clear(_point_at_arc(pts, arc)):
                spawn_arc = arc
                break
            arc += SPAWN_CLEARANCE_FT
        if spawn_arc is None:
            return None

        vehicle = Vehicle(path=path, current_lane=path[0], segments=segments,
                          pos=_point_at_arc(pts, spawn_arc), dest_node_id=dest_node_id,
                          heading=_direction_at_arc(pts, spawn_arc),
                          seg_s=spawn_arc, vid=self._next_vid)
        self._next_vid += 1
        self.vehicles.append(vehicle)
        return vehicle

    def prepare_routes(self):
        """Build the routing graph ONCE, to be reused across many trip
        spawns in a batch (see spawn_trip). Cheap per-spawn cost afterward."""
        self._edges, self._turns, self._connections = build_routing_graph(self.network)
        self._valid_edges = set(self._turns.keys())
        self.intersections.rebuild()

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
        vehicle = self._spawn_on_path(path, self._connections,
                                      dest_node_id=dest_node_id)
        if vehicle is None:   # no path, or the departing lane's start is occupied
            return None
        vehicle.dest_building_id = dest_building_id
        return vehicle

    # ------------------------------------------------------------------
    # Spawn-queue interface (Phase 2a): resolve a route ONCE, then spawn from
    # the precomputed path on later frames so retries never re-run pathfinding.
    # ------------------------------------------------------------------
    def resolve_route(self, start_node_id, dest_node_id):
        """Resolve a lane path start->dest once, using the cached routing graph
        (prepared lazily). Returns the path (list of lane ids) or None when no
        path exists. The spawn queue calls this at release time."""
        if self._edges is None:
            self.prepare_routes()
        return find_lane_path(self._edges,
                              lanes_departing_node(self.network, start_node_id),
                              lanes_arriving_node(self.network, dest_node_id))

    def route_valid(self, path):
        """Cheap structural check that a previously-resolved path still exists
        in the current routing graph. Guards against a mid-run map edit; Phase
        2a otherwise treats the map as frozen for the duration of a demo run."""
        if self._connections is None or not path:
            return False
        return all((path[i], path[i + 1]) in self._connections
                   for i in range(len(path) - 1))

    def spawn_on_route(self, path, dest_node_id=None, dest_building_id=None):
        """Spawn a vehicle on an ALREADY-resolved, structurally-valid path (see
        resolve_route / route_valid). Returns the Vehicle, or None when the
        departing lane's start is still occupied -- a transient block the spawn
        queue retries next frame rather than dropping."""
        vehicle = self._spawn_on_path(path, self._connections,
                                      dest_node_id=dest_node_id)
        if vehicle is None:
            return None
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

    def begin_lane_change(self, vehicle, target_lane_id):
        """Execute a lateral lane change: rebuild `vehicle`'s segments so it
        glides onto `target_lane_id` and continues to the SAME destination,
        recomputing the downstream route from the new lane (the only re-routing
        the sim ever does). The merge polyline starts at the car's current
        position, so position/heading are unchanged at the handoff -- no
        teleport. Returns True on success.

        This is the ONLY executor of a lane change; the policy (whether/which)
        lives in vehicle_lane_change.choose_lane_change."""
        from vehicle_lane_change import build_merge_polyline, MERGE_LEN_FT, \
            LANE_CHANGE_COOLDOWN_S
        goal_lanes = lanes_arriving_node(self.network, vehicle.dest_node_id)
        new_path = find_lane_path(self._edges, [target_lane_id], goal_lanes)
        if new_path is None:
            return False        # safety: choose_lane_change already verified this
        cur_seg = vehicle.segments[vehicle.seg_index]
        new_lane_pts = lane_polyline(self.network, target_lane_id)
        merged = build_merge_polyline(cur_seg["points"], new_lane_pts,
                                      vehicle.seg_s, MERGE_LEN_FT)
        first_segment = {"kind": "lane", "lane_id": target_lane_id,
                         "points": merged, "length": _polyline_length(merged)}
        vehicle.segments = self._compile_segments(
            new_path, self._connections, first_segment=first_segment)
        vehicle.path = new_path
        vehicle.current_lane = target_lane_id
        vehicle.path_index = 0
        vehicle.seg_index = 0
        vehicle.seg_s = 0.0
        vehicle.position_along_lane = 0.0
        vehicle.lane_change_cooldown = LANE_CHANGE_COOLDOWN_S
        vehicle.pos = _point_at_arc(merged, 0.0)
        vehicle.heading = _direction_at_arc(merged, 0.0)
        return True

    def _update_lane_changes(self, dt):
        """LATERAL DECISION pass: held-up cars merge toward an emptier adjacent
        lane. Runs after perception (needs the leader for the held-up test) and
        before the speed-governor decision (which then recomputes desired_speed
        on the possibly-new segments). Rewrites geometry/path only -- never
        speed -- so Movement/Dynamics/the governor stay untouched."""
        from vehicle_lane_change import choose_lane_change
        if self._edges is None:
            self.prepare_routes()
        for vehicle in self.vehicles:
            if vehicle.lane_change_cooldown > 0.0:
                vehicle.lane_change_cooldown = max(
                    0.0, vehicle.lane_change_cooldown - dt)
            if vehicle.dest_node_id is None:
                continue
            goal_lanes = lanes_arriving_node(self.network, vehicle.dest_node_id)
            target = choose_lane_change(vehicle, self.network, self._edges,
                                        goal_lanes, self.vehicles, find_lane_path)
            if target is not None:
                self.begin_lane_change(vehicle, target)

    def update(self, dt):
        # Driver-model pipeline -- decoupled passes, each its own layer,
        # handing off through exactly one field:
        #
        #   0. Intersection control bookkeeping for this frame (clear per-frame
        #      waiters, age transition flashes, and let policy controllers observe
        #      approaching vehicles -- e.g. stop-sign arrival detection + dwell
        #      timing) before any junction requests.
        self.intersections.begin_step(self.vehicles, dt)
        #   1. MOVEMENT: advance each vehicle along its path using the speed the
        #      dynamics layer decided last frame (current_speed). Geometry only;
        #      every junction entry is gated by the intersection controllers.
        for vehicle in self.vehicles:
            vehicle.move(dt, self._valid_edges, self.intersections)
        #   2. PERCEPTION (sense): from the new positions, refresh each vehicle's
        #      view of the car ahead. Read-only w.r.t. motion -- it only sets
        #      vehicle.perception. Local import avoids a module-load cycle
        #      (vehicle_perception imports constants from this module).
        from vehicle_perception import compute_perception
        compute_perception(self.vehicles)
        #   2.5 LANE-CHANGE (lateral decision): a held-up car may begin a smooth
        #      merge onto an emptier adjacent lane and re-route to the same
        #      destination. Reads perception, writes geometry/path only -- never
        #      speed -- so the speed governor and dynamics are unaffected.
        self._update_lane_changes(dt)
        #   3. DECISION: from perception + logical state (and a read-only view of
        #      the intersection controllers, for approach planning), set each
        #      desired_speed via the speed-governor rules (min of all proposals).
        #      Writes ONLY desired_speed; new rules slot in here without touching
        #      dynamics, movement, or reservation logic.
        compute_decisions(self.vehicles, DecisionContext(self.intersections))
        #   4. DYNAMICS: ramp current_speed toward the freshly decided
        #      desired_speed, ready for next frame's movement.
        for vehicle in self.vehicles:
            vehicle.integrate_dynamics(dt)

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
                                   "radius": VEHICLE_LENGTH_FT * 0.65 * VEHICLE_RENDER_SCALE,
                                   "color": VEHICLE_COLORS[vehicle.state],
                                   "alpha": 120})
                layers.append({"shape": "sprite", "pos": vehicle.pos,
                               "heading": vehicle.heading,
                               "length_ft": VEHICLE_LENGTH_FT * VEHICLE_RENDER_SCALE,
                               "image": sprite})
            else:
                layers.append({"shape": "circle", "pos": vehicle.pos,
                               "radius": VEHICLE_RADIUS_FT * VEHICLE_RENDER_SCALE,
                               "color": VEHICLE_COLORS[vehicle.state],
                               "alpha": 255})
        return layers

    def perception_visual_layers(self):
        """Optional debug overlay for the perception system (separate from the
        vehicle/path layers above so it can be toggled independently): for each
        vehicle that has detected a leader, a link line from the follower to its
        leader (color-coded by closing state), a translucent ring on the
        leader, and the bumper-to-bumper following distance as a label at the
        link midpoint. Purely a view of vehicle.perception; reads nothing else
        and mutates nothing."""
        layers = []
        for vehicle in self.vehicles:
            p = getattr(vehicle, "perception", None)
            if p is None or not p.has_leader:
                continue
            if p.approaching:
                color = COLOR_PERCEPTION_APPROACH
            elif p.separating:
                color = COLOR_PERCEPTION_SEPARATE
            else:
                color = COLOR_PERCEPTION_STEADY
            leader = p.leader
            layers.append({"shape": "line", "points": [vehicle.pos, leader.pos],
                           "color": color, "width": 2})
            layers.append({"shape": "circle", "pos": leader.pos,
                           "radius": VEHICLE_LENGTH_FT * 0.75,
                           "color": color, "alpha": 90})
            mid = ((vehicle.pos[0] + leader.pos[0]) / 2.0,
                   (vehicle.pos[1] + leader.pos[1]) / 2.0)
            layers.append({"shape": "text", "pos": mid,
                           "text": f"{p.clear_gap:.0f} ft", "color": color})
        return layers

    def dynamics_visual_layers(self):
        """Optional debug overlay for the dynamics layer: a per-vehicle speed
        readout 'current/desired <glyph>' (ft/s) drawn just above each car,
        colored by the DERIVED motion state -- accelerating (green, ^),
        cruising (gray, =) or braking (red, v). Reads only the vehicle's speed
        state; the accel/brake state itself is computed here, never stored."""
        layers = []
        for vehicle in self.vehicles:
            state = motion_state(vehicle.current_speed, vehicle.desired_speed)
            layers.append({
                "shape": "text",
                "pos": (vehicle.pos[0], vehicle.pos[1] - VEHICLE_LENGTH_FT),
                "text": (f"{vehicle.current_speed:.0f}/{vehicle.desired_speed:.0f}"
                         f" {DYNAMICS_STATE_GLYPHS[state]}"),
                "color": DYNAMICS_STATE_COLORS[state],
            })
        return layers

    def decision_visual_layers(self):
        """Optional debug overlay for the decision layer: below each car, the
        rule currently binding its desired_speed and that target speed (ft/s),
        colored by rule (gray cruise / amber following / red-orange approach).
        For a car easing toward a controlled junction it ALSO draws the stop
        line, a link to it, and the stopping distance + governing approach speed.
        Everything is recomputed read-only from the speed-governor proposals and
        the intersection-approach geometry -- never stored on the vehicle."""
        ctx = DecisionContext(self.intersections)
        layers = []
        for vehicle in self.vehicles:
            name = binding_rule(vehicle, ctx)
            layers.append({
                "shape": "text",
                "pos": (vehicle.pos[0], vehicle.pos[1] + VEHICLE_LENGTH_FT),
                "text": f"{name} {vehicle.desired_speed:.0f}",
                "color": DECISION_RULE_COLORS.get(name, COLOR_DECISION_DEFAULT),
            })
            # Intersection-approach detail: only while the rule is actually
            # constraining (a controlled junction ahead that isn't open yet).
            info = approach_info(vehicle, ctx)
            if info is not None and not info.permitted:
                binding = (name == "approach")   # is this rule the one governing?
                layers.append({"shape": "line",
                               "points": [vehicle.pos, info.stop_pos],
                               "color": COLOR_STOP_LINE,
                               "width": 2 if binding else 1})
                layers.append({"shape": "circle", "pos": info.stop_pos,
                               "radius": 3.5, "color": COLOR_STOP_LINE,
                               "alpha": 220})
                mid = ((vehicle.pos[0] + info.stop_pos[0]) / 2.0,
                       (vehicle.pos[1] + info.stop_pos[1]) / 2.0)
                # stopping distance (to the line) + governing approach speed cap;
                # a '*' marks that this rule is the binding one this frame.
                tag = "*" if binding else ""
                layers.append({"shape": "text", "pos": mid,
                               "text": f"{tag}stop {info.distance:.0f}ft @{info.cap:.0f}",
                               "color": COLOR_STOP_LINE})
        return layers

    def intersection_visual_layers(self):
        """Optional debug overlay for the intersection-control framework:
        controlled junctions (discs + 'kind:count') and the vehicles currently
        registered inside them. Delegates to the controller set; read-only."""
        return self.intersections.visual_layers()
