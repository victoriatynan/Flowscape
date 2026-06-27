"""
Vehicle Lane-Change System -- the lateral decision layer.

The speed-governor decision layer (vehicle_decision.py) answers "what speed?";
this layer answers a different question: "should the car move sideways into a
better lane?". A lane change is a discrete maneuver, not a speed cap, so it does
NOT fit the min()-of-proposals governor and instead runs as its own pass
(TrafficSimulation._update_lane_changes), between Perception and Decision.

Policy (intentionally simple for now): a car changes lanes only when it is
HELD UP -- slowed by a leader close ahead -- and an adjacent same-direction lane
has FEWER cars ahead of it AND can still reach the destination. Of the eligible
adjacent lanes it picks the emptiest (deterministic tie-break below).

This module is split into:
  - policy (pure, read-only): adjacency, per-lane car counts, and the choice.
  - geometry (pure): build_merge_polyline(), the smooth diagonal that carries a
    car from its current lane onto the chosen one with no lateral teleport.
The EXECUTION (rewriting a vehicle's segments + re-routing) lives in
TrafficSimulation, which owns the routing graph and segment compilation.

Strictly read-only here: nothing in this module mutates a vehicle or the
network; the pass returns a target lane and the sim performs the change.
"""

import math

from road_style import get_road_profile
from vehicle_perception import vehicle_location
# Geometry helpers shared with traversal. traffic_sim imports THIS module
# lazily (inside the pass), so importing these names at module top is safe and
# mirrors vehicle_perception's `from traffic_sim import ...`.
from traffic_sim import (VEHICLE_LENGTH_FT, _point_at_arc, _polyline_length,
                         STATE_MOVING)
from vehicle_decision import MIN_FOLLOW_GAP_FT

# --- Tunable policy constants (feet / seconds) ------------------------------
# Longitudinal length of the merge glide (how far forward the car travels while
# crossing the lane gap). ~2.5 car lengths reads as a natural merge.
MERGE_LEN_FT = 2.5 * VEHICLE_LENGTH_FT
# "Held up" threshold: only consider changing when the bumper-to-bumper gap to
# the leader is below this (i.e. the follow rule is actually constraining).
LANE_CHANGE_GAP_FT = 2.0 * MIN_FOLLOW_GAP_FT
# Don't merge into a target lane if another car occupies the slot within this
# arc distance of the merge point (ahead or behind) -- avoids merging on top of
# someone or cutting them off.
LANE_CHANGE_SLOT_GAP_FT = 1.5 * VEHICLE_LENGTH_FT
# After a change, commit to the new lane for this long before considering another
# (prevents weaving / oscillation between two lanes).
LANE_CHANGE_COOLDOWN_S = 2.0
# Small buffer so a merge always finishes before the junction mouth.
MERGE_TAIL_BUFFER_FT = VEHICLE_LENGTH_FT


def adjacent_lane_ids(network, lane_id):
    """Same-direction neighbour lanes (road_id, dir, k-1/k+1) that actually
    exist for this road's profile. Innermost lane is index 0."""
    road_id, direction, k = lane_id
    road = network.roads.get(road_id)
    if road is None:
        return []
    profile = get_road_profile(road)
    count = profile.lanes_forward() if direction == "F" else profile.lanes_reverse()
    return [(road_id, direction, k + d) for d in (-1, 1)
            if 0 <= k + d < count]


def _located_on_lane(vehicles, lane_id):
    """[(vehicle, arc), ...] for every vehicle currently sitting on a LANE
    segment of `lane_id` (connection segments are excluded -- a car mid-junction
    isn't 'in' a road lane). arc is distance from that lane's start."""
    out = []
    for v in vehicles:
        loc = vehicle_location(v)
        if loc is None:
            continue
        kind, vid, arc = loc
        if kind == "lane" and vid == lane_id:
            out.append((v, arc))
    return out


def cars_ahead(vehicles, lane_id, ref_arc, exclude=None):
    """Number of vehicles on `lane_id` whose arc is ahead of `ref_arc`.
    Parallel lanes share the same trimmed centerline parameterization, so arcs
    compare directly across adjacent lanes."""
    return sum(1 for v, arc in _located_on_lane(vehicles, lane_id)
               if v is not exclude and arc > ref_arc)


def nearest_gap_ahead(vehicles, lane_id, ref_arc, exclude=None):
    """Arc distance to the nearest car ahead on `lane_id`, or +inf if none.
    Used only as a tie-break between equally-empty lanes (prefer more room)."""
    gaps = [arc - ref_arc for v, arc in _located_on_lane(vehicles, lane_id)
            if v is not exclude and arc > ref_arc]
    return min(gaps) if gaps else math.inf


def target_slot_clear(vehicles, lane_id, ref_arc, gap, exclude=None):
    """True when no car on `lane_id` sits within +/- `gap` arc of `ref_arc`."""
    return all(abs(arc - ref_arc) > gap
               for v, arc in _located_on_lane(vehicles, lane_id)
               if v is not exclude)


def _held_up(vehicle):
    """Is the car currently constrained by a close leader ahead? (the trigger
    condition: don't change lanes during free flow)."""
    p = getattr(vehicle, "perception", None)
    return bool(p and p.has_leader and p.clear_gap < LANE_CHANGE_GAP_FT)


def choose_lane_change(vehicle, network, edges, goal_lanes, vehicles,
                       find_lane_path):
    """Decide whether `vehicle` should change lanes, returning the target
    lane_id or None. Pure / read-only.

    `find_lane_path` and `edges` are injected (owned by traffic_sim) so this
    module never imports the router; `goal_lanes` is the set of lanes arriving
    at the destination node.
    """
    if vehicle.state != STATE_MOVING:
        return None
    if vehicle.lane_change_cooldown > 0.0:
        return None
    if not vehicle.segments:
        return None
    seg = vehicle.segments[vehicle.seg_index]
    if seg["kind"] != "lane":
        return None                         # mid-junction: never change here
    # Need room to finish the merge before the lane ends at the junction mouth.
    remaining = seg["length"] - vehicle.seg_s
    if remaining < MERGE_LEN_FT + MERGE_TAIL_BUFFER_FT:
        return None
    if not _held_up(vehicle):
        return None

    ref_arc = vehicle.seg_s
    here = cars_ahead(vehicles, vehicle.current_lane, ref_arc, exclude=vehicle)

    best = None  # (cars_ahead, -nearest_gap, lane_index, lane_id)
    for adj in adjacent_lane_ids(network, vehicle.current_lane):
        if not target_slot_clear(vehicles, adj, ref_arc,
                                  LANE_CHANGE_SLOT_GAP_FT, exclude=vehicle):
            continue
        ahead = cars_ahead(vehicles, adj, ref_arc, exclude=vehicle)
        if ahead >= here:
            continue                        # not emptier -> no reason to move
        # Must still be able to reach the destination from the adjacent lane.
        if find_lane_path(edges, [adj], goal_lanes) is None:
            continue
        # Tie-break: fewest cars ahead, then most room to the nearest car ahead,
        # then lower lane index (deterministic).
        key = (ahead, -nearest_gap_ahead(vehicles, adj, ref_arc, exclude=vehicle),
               adj[2])
        if best is None or key < best[0]:
            best = (key, adj)
    return best[1] if best is not None else None


def _smoothstep(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def build_merge_polyline(cur_pts, new_pts, start_arc, merge_len, step=2.0):
    """Smooth lateral-merge polyline: starts at the car's current position on
    `cur_pts` (arc `start_arc`) and glides diagonally onto `new_pts`, then
    follows `new_pts` to its end. Pure geometry.

    Both polylines are parallel offsets of the same trimmed road centerline, so
    a point at arc `a` on one corresponds to arc `a * scale` on the other
    (scale = length ratio), keeping the merge aligned even on curves. The
    crossing weight ramps 0->1 by smoothstep over `merge_len`, so the path
    leaves the current lane tangentially and settles onto the new lane with no
    kink and no single-frame lateral jump.
    """
    cur_len = _polyline_length(cur_pts)
    new_len = _polyline_length(new_pts)
    if cur_len <= 0.0:
        return list(new_pts)
    scale = (new_len / cur_len) if cur_len > 0 else 1.0

    out = []
    a = start_arc
    while a < cur_len:
        w = _smoothstep((a - start_arc) / merge_len) if merge_len > 0 else 1.0
        c = _point_at_arc(cur_pts, a)
        n = _point_at_arc(new_pts, a * scale)
        out.append((c[0] + (n[0] - c[0]) * w, c[1] + (n[1] - c[1]) * w))
        a += step
    # Always finish exactly on the new lane's end so it joins the next segment.
    out.append(new_pts[-1])
    if len(out) < 2:
        out = [_point_at_arc(cur_pts, start_arc), new_pts[-1]]
    return out
