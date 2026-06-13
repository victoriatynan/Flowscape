"""
Intersection Lane-Matching (Lane Connectivity Graph).

Builds a many-to-many, weighted lane-to-lane connection graph at every
junction node, purely from direction geometry -- no manual rules, no
hardcoded road logic, no per-intersection configuration.

Pipeline (per node with >= 2 connected roads):

  1. Lane classification: every lane of every connected road contributes a
     LaneEnd at the node -- position at the junction mouth, normalized
     travel-direction vector, and a role: forward lanes travel start->end,
     so at a road's END node they are INCOMING and at its START node
     OUTGOING; reverse lanes the opposite.

  2. Road-level movement filter (vector-based): for each incoming road ->
     outgoing road pair, score = dot(in_dir, out_dir) (cosine similarity).
     Movements below SCORE_THRESHOLD are rejected (backward-facing /
     nonsensical connections). Same-road movements are U-turns: skipped
     unless explicitly allowed.

  3. Lane fan-out within each accepted movement: lanes are ordered by
     lateral position in their own travel frame (leftmost first) and
     mapped proportionally (leftmost<->leftmost), so multi-lane roads
     connect without crossing assignments. This is the many-to-many model:
     one incoming lane connects to one or more outgoing lanes across ALL
     valid outgoing roads (straight + left + right), each connection
     carrying its own score.

  4. Turn classification from the signed angle between in/out directions:
     STRAIGHT (within ~30 deg), LEFT / RIGHT (sign of the cross product --
     screen space is y-down, so cross > 0 means a right turn), UTURN
     (beyond ~150 deg).

Strictly read-only: consumes the RoadNetwork through its public query
methods and never mutates nodes/roads/zones; nothing here is saved. The
graph is fully regenerated on demand from node positions + curve offsets +
lane profiles, so it can never drift out of sync with the map.

`lane_graph_visual_layers()` turns a built graph into the editor's generic
visual-layer shape dicts (lines/polygons) for debug rendering: incoming and
outgoing lane arrows plus connection curves color-coded by turn type.
"""

import math
from dataclasses import dataclass

from road_geometry import sample_quadratic_bezier
from road_style import get_road_profile

TURN_STRAIGHT = "STRAIGHT"
TURN_LEFT = "LEFT"
TURN_RIGHT = "RIGHT"
TURN_UTURN = "UTURN"

# Reject movements whose directions disagree past this cosine similarity
# (dot(in_dir, out_dir) <= threshold -> no connection).
SCORE_THRESHOLD = -0.2

# Turn-classification bands (degrees of deviation between in/out travel
# directions): <= STRAIGHT_MAX_DEG -> STRAIGHT, >= UTURN_MIN_DEG -> UTURN,
# in between -> LEFT/RIGHT by turn side.
STRAIGHT_MAX_DEG = 30.0
UTURN_MIN_DEG = 150.0

TURN_COLORS = {
    TURN_STRAIGHT: (90, 220, 120),   # green
    TURN_LEFT: (255, 170, 60),       # orange
    TURN_RIGHT: (90, 170, 255),      # blue
    TURN_UTURN: (255, 80, 80),       # red
}

COLOR_ARROW_IN = (240, 240, 240)
COLOR_ARROW_OUT = (255, 210, 90)

ARROW_LENGTH_FT = 7.0
ARROW_HEAD_FT = 3.0
CONNECTION_SAMPLES = 12


@dataclass(frozen=True)
class LaneEnd:
    """One lane of one road where it meets a junction node."""
    node_id: int
    road_id: int
    lane_index: int      # 0 = innermost (next to centerline/median)
    role: str            # "in" | "out"
    pos: tuple           # world-space lane-center position at the mouth
    direction: tuple     # unit travel direction at the node
    lateral: float       # signed left-of-travel offset (for lane ordering)
    forward: bool = True  # True = travels start->end of its road

    @property
    def lane_id(self):
        """Stable directed-lane identity (road, direction, lane index) --
        the node id of this lane in the routing graph."""
        return (self.road_id, "F" if self.forward else "R", self.lane_index)


@dataclass(frozen=True)
class LaneConnection:
    """A weighted directed edge of the lane graph: incoming -> outgoing."""
    node_id: int
    source: LaneEnd
    target: LaneEnd
    score: float         # dot(in_dir, out_dir), higher = straighter
    turn_type: str       # TURN_STRAIGHT | TURN_LEFT | TURN_RIGHT | TURN_UTURN


def _normalize(dx, dy):
    length = math.hypot(dx, dy)
    if length == 0:
        return (0.0, 0.0)
    return (dx / length, dy / length)


def _point_along(points, from_start, distance):
    """Walk `distance` (arc length) along a polyline from one end and
    return (position, forward_tangent) there, where forward_tangent is
    always oriented start->end regardless of which end we walked from.
    Clamps to the far endpoint if the polyline is shorter than distance."""
    pts = list(points) if from_start else list(reversed(points))
    remaining = max(0.0, distance)
    for i in range(len(pts) - 1):
        ax, ay = pts[i]
        bx, by = pts[i + 1]
        seg = math.hypot(bx - ax, by - ay)
        if seg > 1e-12 and seg >= remaining:
            t = remaining / seg
            pos = (ax + (bx - ax) * t, ay + (by - ay) * t)
            d = _normalize(bx - ax, by - ay)
            return pos, (d if from_start else (-d[0], -d[1]))
        remaining -= seg
    ax, ay = pts[-2]
    bx, by = pts[-1]
    d = _normalize(bx - ax, by - ay)
    return pts[-1], (d if from_start else (-d[0], -d[1]))


def classify_turn(in_dir, out_dir):
    """Turn type from the signed angle between travel directions. Screen
    space is y-down, so a positive cross product (rotating from in_dir
    toward out_dir) is a clockwise rotation = a RIGHT turn."""
    dot = max(-1.0, min(1.0, in_dir[0] * out_dir[0] + in_dir[1] * out_dir[1]))
    cross = in_dir[0] * out_dir[1] - in_dir[1] * out_dir[0]
    deviation = math.degrees(math.atan2(abs(cross), dot))
    if deviation <= STRAIGHT_MAX_DEG:
        return TURN_STRAIGHT
    if deviation >= UTURN_MIN_DEG:
        return TURN_UTURN
    return TURN_RIGHT if cross > 0 else TURN_LEFT


def _lane_ends(network, road, node_id):
    """All LaneEnds contributed by `road` at `node_id`. Lane positions sit
    at the junction mouth (the same trim distance the renderer uses), each
    lane centered in its strip using the profile's sign convention
    (positive offset = left of start->end travel = forward side)."""
    pts = network.geometry_for_road(road)["sampled_points"]
    if len(pts) < 2:
        return []
    at_start = (road.start_node_id == node_id)
    trim = network.road_trim_at_node(road, node_id)
    mouth, forward = _point_along(pts, from_start=at_start, distance=trim)
    if forward == (0.0, 0.0):
        return []
    normal = (-forward[1], forward[0])  # left of start->end travel

    profile = get_road_profile(road)
    half_median = profile.median_width / 2.0

    ends = []
    # (lane_count, side sign on the normal, travel direction, role, forward?)
    sides = (
        (profile.lanes_forward(), 1.0, forward,
         "out" if at_start else "in", True),
        (profile.lanes_reverse(), -1.0, (-forward[0], -forward[1]),
         "in" if at_start else "out", False),
    )
    for lane_count, sign, direction, role, is_forward in sides:
        left_axis = (-direction[1], direction[0])
        for k in range(lane_count):
            offset = sign * (half_median + (k + 0.5) * profile.lane_width)
            pos = (mouth[0] + normal[0] * offset, mouth[1] + normal[1] * offset)
            lateral = ((pos[0] - mouth[0]) * left_axis[0]
                       + (pos[1] - mouth[1]) * left_axis[1])
            ends.append(LaneEnd(node_id=node_id, road_id=road.id, lane_index=k,
                                role=role, pos=pos, direction=direction,
                                lateral=lateral, forward=is_forward))
    return ends


def _fan_pairs(n_in, n_out):
    """Proportional index mapping between two ordered lane groups (both
    leftmost-first). Every incoming and every outgoing lane is covered;
    order is preserved, so assignments never cross."""
    pairs = []
    if n_in <= 0 or n_out <= 0:
        return pairs
    if n_out >= n_in:
        for i in range(n_in):
            lo = (i * n_out) // n_in
            hi = ((i + 1) * n_out) // n_in - 1
            for j in range(lo, max(lo, hi) + 1):
                pairs.append((i, j))
    else:
        for i in range(n_in):
            pairs.append((i, (i * n_out) // n_in))
    return pairs


def build_lane_graph(network, score_threshold=SCORE_THRESHOLD, allow_uturns=False):
    """
    Build the lane connectivity graph for every node with >= 2 committed
    roads (intersections AND continuation bends, so the graph is routable
    end-to-end). Deterministic: nodes, roads and lanes are processed in
    sorted-id / lateral order.

    Returns {node_id: {"incoming": [LaneEnd], "outgoing": [LaneEnd],
                       "connections": [LaneConnection]}}.
    """
    graph = {}
    for node_id in sorted(network.nodes.keys()):
        roads = sorted((r for r in network.roads_for_node(node_id)
                        if not r.is_preview), key=lambda r: r.id)
        if len(roads) < 2:
            continue

        incoming_by_road = {}
        outgoing_by_road = {}
        for road in roads:
            for end in _lane_ends(network, road, node_id):
                target = incoming_by_road if end.role == "in" else outgoing_by_road
                target.setdefault(road.id, []).append(end)
        # Leftmost-first ordering within each road group, so proportional
        # fan mapping pairs leftmost<->leftmost and never crosses.
        for groups in (incoming_by_road, outgoing_by_road):
            for lanes in groups.values():
                lanes.sort(key=lambda e: -e.lateral)

        connections = []
        for in_road_id in sorted(incoming_by_road.keys()):
            in_lanes = incoming_by_road[in_road_id]
            for out_road_id in sorted(outgoing_by_road.keys()):
                out_lanes = outgoing_by_road[out_road_id]
                if not in_lanes or not out_lanes:
                    continue

                is_uturn_movement = (in_road_id == out_road_id)
                if is_uturn_movement and not allow_uturns:
                    continue

                # Road-level movement filter: cosine similarity between
                # representative travel directions. U-turn movements are
                # near-opposite by construction, so they bypass the
                # threshold when explicitly allowed.
                din = in_lanes[0].direction
                dout = out_lanes[0].direction
                movement_score = din[0] * dout[0] + din[1] * dout[1]
                if not is_uturn_movement and movement_score <= score_threshold:
                    continue

                for i, j in _fan_pairs(len(in_lanes), len(out_lanes)):
                    src, dst = in_lanes[i], out_lanes[j]
                    score = (src.direction[0] * dst.direction[0]
                             + src.direction[1] * dst.direction[1])
                    turn = (TURN_UTURN if is_uturn_movement
                            else classify_turn(src.direction, dst.direction))
                    connections.append(LaneConnection(
                        node_id=node_id, source=src, target=dst,
                        score=score, turn_type=turn))

        graph[node_id] = {
            "incoming": [e for lanes in incoming_by_road.values() for e in lanes],
            "outgoing": [e for lanes in outgoing_by_road.values() for e in lanes],
            "connections": connections,
        }
    return graph


# ----------------------------------------------------------------------
# Junction connection geometry: SINGLE SOURCE OF TRUTH.
# ----------------------------------------------------------------------

def get_connection_curve(lane_a, lane_b, node, samples=CONNECTION_SAMPLES):
    """The one and only definition of junction connection-curve geometry.

    Every system that needs the drivable/visible curve between an incoming
    and an outgoing lane (debug overlay, lane-graph visualization, vehicle
    junction transitions, future intersection visuals or traffic logic)
    MUST call this -- no system may compute its own curve, or views of the
    same intersection will diverge.

    Geometry contract (all of it lives here):
      - endpoints: the canonical junction mouth positions, lane_a.pos ->
        lane_b.pos (LaneEnd mouths -- centerline trimmed to the junction,
        offset to the lane center)
      - shape: quadratic Bezier sampled at `samples` intervals
      - control point: currently the junction node itself, identical for
        every turn type. Turn-specific control points (tangent-based
        left/right/straight shaping) belong HERE when introduced, so all
        callers pick them up at once.

    Pure and deterministic: same inputs -> same points; reads nothing but
    its arguments and mutates nothing.

    lane_a/lane_b: LaneEnd (incoming/outgoing). node: Node or (x, y).
    Returns the sampled curve points, endpoints included.
    """
    control = getattr(node, "pos", node)
    return sample_quadratic_bezier(lane_a.pos, control, lane_b.pos, samples)


# ----------------------------------------------------------------------
# Debug visualization: translate a built graph into the editor's generic
# visual-layer shape dicts (RoadRenderer.draw_visual_layers). Pure output;
# the UI keeps zero knowledge of lane-graph semantics.
# ----------------------------------------------------------------------

def _arrow_layers(end):
    """Shaft line + head triangle for one lane end. Incoming arrows point
    INTO the node (head at the mouth), outgoing arrows point away."""
    d = end.direction
    color = COLOR_ARROW_IN if end.role == "in" else COLOR_ARROW_OUT
    if end.role == "in":
        tail = (end.pos[0] - d[0] * ARROW_LENGTH_FT, end.pos[1] - d[1] * ARROW_LENGTH_FT)
        tip = end.pos
    else:
        tail = end.pos
        tip = (end.pos[0] + d[0] * ARROW_LENGTH_FT, end.pos[1] + d[1] * ARROW_LENGTH_FT)
    left = (-d[1], d[0])
    base = (tip[0] - d[0] * ARROW_HEAD_FT, tip[1] - d[1] * ARROW_HEAD_FT)
    half = ARROW_HEAD_FT * 0.6
    head = [tip,
            (base[0] + left[0] * half, base[1] + left[1] * half),
            (base[0] - left[0] * half, base[1] - left[1] * half)]
    return [
        {"shape": "line", "points": [tail, base], "color": color, "width": 2},
        {"shape": "polygon", "points": head, "color": color, "alpha": 255},
    ]


def lane_graph_visual_layers(network, graph):
    """Visual-layer dicts for an entire lane graph: connection curves first
    (color-coded by turn type), then lane arrows on top."""
    curves = []
    arrows = []
    for node_id, entry in graph.items():
        node = network.nodes.get(node_id)
        if node is None:
            continue
        for conn in entry["connections"]:
            pts = get_connection_curve(conn.source, conn.target, node)
            curves.append({"shape": "line", "points": pts,
                           "color": TURN_COLORS[conn.turn_type], "width": 2})
        for end in entry["incoming"] + entry["outgoing"]:
            arrows.extend(_arrow_layers(end))
    return curves + arrows
