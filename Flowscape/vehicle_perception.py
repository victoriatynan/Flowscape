"""
Vehicle Perception System (sensing only -- no movement changes).

Every frame this computes, for each vehicle, the nearest vehicle AHEAD along
its own lane path -- its "leader" -- the gap to that leader, and whether the
gap is currently closing (approaching) or opening (separating). It is the
substrate a later car-following / queue-detection / traffic-statistics layer
will read; it brakes, accelerates and reroutes NOTHING.

Strict separation (same philosophy as lane_graph / traffic_sim's pathfinding):
  - Read-only with respect to motion. The pass attaches a Perception result to
    each vehicle (vehicle.perception); Vehicle.update() never reads that field,
    so perception can never alter how a car moves.
  - Logical data stays the source of truth: nothing here is saved, and the
    whole result is recomputed from live vehicle positions each frame, so it
    can never drift out of sync with the simulation.

Path-space, not screen-space:
  A vehicle's location is (segment kind, lane_id, arc), where `arc` is the
  distance from the START of the compiled segment it currently occupies (a
  lane segment -> distance along that lane; a connection segment -> distance
  into that junction curve). Gaps are measured by walking the FOLLOWER's own
  compiled segment chain forward -- those segment lengths already include the
  junction connection-curve arcs (see traffic_sim._spawn_on_path) -- so a gap
  is a true along-the-road distance through lanes and intersections, exactly
  what a car-following model needs, never a straight-line screen distance.

Why it lines up with the lane graph: two vehicles are comparable iff they sit
on the same directed lane (or the same junction connection) -- the lane_id is
the shared identity from lane_graph. A leader on a lane that is not part of the
follower's path is correctly never seen as "ahead".
"""

import math

from traffic_sim import VEHICLE_LENGTH_FT

# Relative-speed deadband (ft/s): within +/- this, the gap is treated as
# steady rather than approaching/separating. Vehicles now have independent
# dynamics, so speeds genuinely differ during accel/brake (and will differ more
# once a car-following decision layer varies desired_speed); pairs at a matched
# cruise still land in the deadband and read as steady.
CLOSING_EPS = 1e-3


class Perception:
    """One vehicle's view of the road ahead, recomputed every frame and never
    saved. `leader` is None when nothing is ahead on this vehicle's path.

    Fields:
      leader        : the perceived Vehicle ahead, or None.
      gap           : center-to-center distance to the leader along the
                      follower's path (feet); math.inf when no leader.
      clear_gap     : bumper-to-bumper following distance (gap minus one
                      vehicle length); what a car-following law would regulate.
      closing_speed : follower.current_speed - leader.current_speed (ft/s).
                      > 0 means the follower is faster, so the gap is closing.
      approaching / separating : sign of closing_speed outside the deadband.
    """

    __slots__ = ("leader", "gap", "clear_gap", "closing_speed",
                 "approaching", "separating")

    def __init__(self, leader=None, gap=math.inf, clear_gap=math.inf,
                 closing_speed=0.0, approaching=False, separating=False):
        self.leader = leader
        self.gap = gap
        self.clear_gap = clear_gap
        self.closing_speed = closing_speed
        self.approaching = approaching
        self.separating = separating

    @property
    def has_leader(self):
        return self.leader is not None


def vehicle_location(vehicle):
    """(kind, lane_id, arc) for where `vehicle` currently sits on its compiled
    path, or None if it has no segments. `arc` is measured from the start of
    the current segment; `lane_id` is that segment's lane id (for a connection
    segment, the lane it leads INTO -- the same key the follower indexes it by,
    see _ahead_distances)."""
    if not vehicle.segments:
        return None
    seg = vehicle.segments[vehicle.seg_index]
    return (seg["kind"], seg["lane_id"], vehicle.seg_s)


def _ahead_distances(vehicle):
    """Distance from `vehicle` to the START of every segment from its current
    one forward, walking its own compiled segments (whose lengths already
    include junction connection-curve arcs).

    Returns (lane_dist, conn_dist): {lane_id: distance_to_segment_start} for
    lane segments and for connection segments respectively. A directed lane id
    is unique within a simple Dijkstra path, so each key appears at most once;
    `setdefault` keeps the first (nearest-ahead) occurrence either way.

    The current segment's start sits BEHIND the vehicle by `seg_s`, so the walk
    seeds the accumulator at -seg_s: a leader on the current lane at arc `a`
    then resolves to gap = -seg_s + a = a - seg_s (positive only if ahead).
    """
    lane_dist = {}
    conn_dist = {}
    acc = -vehicle.seg_s
    for i in range(vehicle.seg_index, len(vehicle.segments)):
        seg = vehicle.segments[i]
        target = conn_dist if seg["kind"] == "connection" else lane_dist
        target.setdefault(seg["lane_id"], acc)
        acc += seg["length"]
    return lane_dist, conn_dist


def compute_perception(vehicles, max_range=None):
    """Compute and attach a Perception to every vehicle in `vehicles`.

    `max_range`, if given, ignores any leader farther than that many feet along
    the path (useful later to bound sensing range / cost); None = unlimited.

    Read-only w.r.t. motion: the only state written is `vehicle.perception`,
    which the movement step never consults. Cost is one O(N) bucketing pass
    plus, per follower, a walk of the lanes it can actually reach -- so it stays
    cheap at on-screen car counts, and the per-(kind, lane) buckets it builds
    are exactly the occupancy index queue detection and flow statistics will
    reuse.
    """
    # Bucket every vehicle by the (kind, lane_id) it occupies, so a follower
    # only ever inspects vehicles on lanes/junctions that lie on its own path.
    buckets = {}          # (kind, lane_id) -> [(vehicle, arc), ...]
    located = set()       # id() of vehicles that have a usable location
    for v in vehicles:
        loc = vehicle_location(v)
        if loc is None:
            v.perception = Perception()
            continue
        kind, lane_id, arc = loc
        located.add(id(v))
        buckets.setdefault((kind, lane_id), []).append((v, arc))

    for v in vehicles:
        if id(v) not in located:
            continue
        lane_dist, conn_dist = _ahead_distances(v)
        best_leader = None
        best_gap = math.inf
        # Same-lane leaders first, then leaders inside upcoming junction curves;
        # both are matched by the shared lane_id, distance read from this
        # follower's own forward segment walk.
        for dist_map, kind in ((lane_dist, "lane"), (conn_dist, "connection")):
            for lane_id, seg_start in dist_map.items():
                for other, arc in buckets.get((kind, lane_id), ()):
                    if other is v:
                        continue
                    gap = seg_start + arc
                    if gap > 0.0 and gap < best_gap:
                        best_gap = gap
                        best_leader = other

        if best_leader is None or (max_range is not None and best_gap > max_range):
            v.perception = Perception()
            continue
        closing = v.current_speed - best_leader.current_speed
        v.perception = Perception(
            leader=best_leader,
            gap=best_gap,
            clear_gap=best_gap - VEHICLE_LENGTH_FT,
            closing_speed=closing,
            approaching=closing > CLOSING_EPS,
            separating=closing < -CLOSING_EPS,
        )
