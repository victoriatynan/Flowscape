"""
Vehicle Decision-Making System -- the "what does it want to do?" layer.

Three-layer driver model (see vehicle_dynamics.py for the full picture):

  Perception  -- "What does the vehicle know?"        vehicle_perception.py
  Decision    -- "What speed should it target?"       THIS MODULE
  Dynamics    -- "How does it physically reach it?"   vehicle_dynamics.py

This module's ONLY job is to set each vehicle's desired_speed. It is independent
of movement and dynamics: it reads nothing but logical vehicle state
(cruise_speed, and -- read-only -- the perception result) and writes nothing but
desired_speed. It never advances a vehicle, never integrates speed, never reads
how the dynamics layer works.

The speed-governor pattern (what keeps it extensible)
-----------------------------------------------------
Each driver concern is a RULE: a pure function `vehicle -> proposed speed cap`
(feet/second), or +inf when the rule has no opinion right now. The decided
speed is simply the most restrictive proposal:

    desired_speed = min(rule(vehicle) for rule in DECISION_RULES)

Every future feature -- speed limits, traffic lights, stop signs, pedestrians,
emergency vehicles, school zones, incidents -- is just another rule contributing
another candidate speed. It needs to know nothing about the other rules, and
none of them (nor the dynamics layer) change when it is added. `min` is
order-independent, so there is no priority wiring to maintain.

Implemented rules:
  - rule_following_distance : keep a minimum following distance behind the
    perceived leader.
  - rule_intersection_approach : ease to a smooth stop at the stop line of the
    next CONTROLLED junction while its controller has not yet granted entry
    (no effect once permission is available). The controller answers ONLY
    whether entry is permitted (read-only would_permit()); this rule decides
    HOW to approach comfortably -- it never enters, reserves, or moves anything.
No stop-sign/traffic-light timing, yielding, lane changes or congestion logic
yet -- those are simply additional rules (and richer controllers) to add later.

To consult systems outside the vehicle without coupling, a rule receives a
read-only DecisionContext alongside the vehicle (e.g. ctx.intersections); rules
that need only the vehicle ignore it. The functions stay pure -- no globals.

Design philosophy (shared with the rest of Flowscape):
  - Logical data is the source of truth: cruise_speed is the vehicle's logical
    free-flow target; desired_speed is a per-frame OUTPUT recomputed here every
    frame (a one-field handoff to dynamics, like vehicle.perception), not
    durable state.
  - Derived values are computed, not stored: which rule is binding, and the
    approach geometry, are computed on demand for debug, never persisted.
  - No unnecessary coupling: pure functions of (vehicle, ctx); this module
    imports nothing from traffic_sim, dynamics, perception or intersection_control
    -- outside systems arrive only through the duck-typed context.
"""

import math
from dataclasses import dataclass

INF = float("inf")


# ----------------------------------------------------------------------
# Decision context: the read-only environment handed to every rule.
# ----------------------------------------------------------------------

@dataclass
class DecisionContext:
    """Read-only environment passed to every decision rule each frame.

    It lets a rule consult systems OUTSIDE the vehicle (currently the
    intersection controllers) without importing them or using globals -- the
    rule stays a pure function of (vehicle, ctx). Rules that don't need it
    ignore it.

    `intersections` (if set) exposes controller_for(node_id), and each
    controller exposes the read-only would_permit(vehicle) query. The decision
    layer only ASKS whether entry is permitted; it never enters, reserves, or
    moves anything -- that stays entirely in the controller and movement layers.
    """
    intersections: object = None


# Shared empty context, so callers that pass no context still get pure rules
# (the intersection-approach rule simply finds no controllers -> no effect).
_EMPTY_CONTEXT = DecisionContext()

# --- Following-distance rule parameters (configurable policy) ---------------
# Minimum following distance to keep behind the leader, bumper-to-bumper (feet).
# This is the gap the rule settles the vehicle at when it is speed-limited by
# the car ahead.
MIN_FOLLOW_GAP_FT = 20.0

# Comfortable deceleration the following rule plans around (ft/s^2). The rule
# never lets a vehicle go faster than it could shed at this rate before the gap
# closes to the minimum, which is what guarantees no overlap. It MUST be <= a
# vehicle's braking_rate (the dynamics layer can always brake at least this
# hard), so the planned slowdown is physically achievable; keeping it strictly
# below max brake leaves emergency-braking headroom and reads smoother.
COMFORT_DECEL_FT_S2 = 10.0

# --- Intersection-approach rule parameters ----------------------------------
# How far SHORT of the junction mouth a vehicle aims to halt (feet): roughly
# half a car plus a small buffer, so its nose stops at the stop line instead of
# nosing into the junction. Kept as a local constant so this module stays free
# of any traffic_sim import.
STOP_LINE_SETBACK_FT = 9.0


# ----------------------------------------------------------------------
# Rules: each is a pure function (vehicle, ctx) -> proposed speed cap (ft/s),
# or INF when it does not constrain this vehicle right now. `ctx` is a
# DecisionContext; rules that need nothing beyond the vehicle ignore it.
# ----------------------------------------------------------------------

def rule_cruise(vehicle, ctx):
    """Baseline: a vehicle wants to travel at its own free-flow cruise speed.
    Always finite, so the min() below always has a defined result."""
    return vehicle.cruise_speed


def rule_following_distance(vehicle, ctx):
    """Keep at least MIN_FOLLOW_GAP_FT behind the perceived leader, smoothly.

    Reads only perception (the existing leader/gap output) and the leader's
    current_speed -- all logical state. Returns a speed cap; the governor's
    min() turns that into a smooth slow-down when the leader is close and lets
    the vehicle return to cruise as the gap opens. The mapping is continuous and
    monotonic in the gap, so it neither oscillates nor steps abruptly, and it
    reaches 0 as the gap vanishes, so vehicles never overlap.
    """
    p = getattr(vehicle, "perception", None)
    if p is None or not p.has_leader:
        return INF                       # clear lane ahead -> no constraint

    gap = p.clear_gap                    # bumper-to-bumper distance (feet)
    leader_v = p.leader.current_speed

    if gap <= 0.0:
        return 0.0                       # touching/overlapping -> stop, never overlap

    if gap < MIN_FOLLOW_GAP_FT:
        # Inside the minimum: ease BELOW the leader's speed in proportion to how
        # far inside we are, down to a full stop as the gap reaches zero. This
        # reopens the gap smoothly without reversing, and the 0-at-0 floor is
        # the hard overlap guard.
        return leader_v * (gap / MIN_FOLLOW_GAP_FT)

    # At or beyond the minimum: the fastest speed from which we could still
    # decelerate (at the comfortable rate) to the leader's speed before the gap
    # closes to the minimum -- the classic kinematic safe speed. sqrt() makes it
    # rise smoothly toward (and past) cruise as the surplus gap grows, so the
    # governor's min() returns the vehicle to cruise gently once the lane opens.
    surplus = gap - MIN_FOLLOW_GAP_FT
    return leader_v + math.sqrt(2.0 * COMFORT_DECEL_FT_S2 * surplus)


# --- Intersection-approach rule ---------------------------------------------

@dataclass
class ApproachInfo:
    """What the approach rule sees for the next controlled junction ahead.
    Recomputed on demand (rule + debug); never stored on the vehicle."""
    node_id: int
    stop_pos: tuple          # world-space stop-line point (the junction mouth)
    distance: float          # along-lane distance from the vehicle to the line
    brake_distance: float    # usable braking distance (after the stop setback)
    cap: float               # the smooth-stop speed cap this distance implies
    permitted: bool          # would the controller grant entry right now?


def _intersection_approach(vehicle, ctx):
    """If `vehicle` is on a lane immediately approaching a CONTROLLED junction,
    return an ApproachInfo; otherwise None.

    Pure: reads only the vehicle's own compiled segments + a read-only
    would_permit() query on the controller. It never enters or reserves -- it
    just measures the distance to the stop line and asks whether entry is open.
    """
    intersections = getattr(ctx, "intersections", None)
    if intersections is None:
        return None
    segs = getattr(vehicle, "segments", None)
    i = getattr(vehicle, "seg_index", 0)
    if not segs or i >= len(segs):
        return None
    seg = segs[i]
    if seg["kind"] != "lane":
        return None                      # already in a junction / not on a lane
    j = i + 1
    if j >= len(segs):
        return None                      # last lane -> arriving, no junction ahead
    conn = segs[j]
    if conn["kind"] != "connection":
        return None
    controller = intersections.controller_for(conn["node_id"])
    if controller is None:
        return None                      # uncontrolled junction -> nothing to anticipate

    distance = seg["length"] - vehicle.seg_s         # to the mouth (stop line)
    brake_distance = max(0.0, distance - STOP_LINE_SETBACK_FT)
    # Kinematic smooth-stop speed: the fastest speed from which the vehicle could
    # still decelerate to a halt at the comfortable rate within brake_distance.
    # sqrt() -> rises smoothly with distance, so it only constrains once the
    # vehicle is close, and reaches 0 exactly at the stop line.
    cap = math.sqrt(2.0 * COMFORT_DECEL_FT_S2 * brake_distance)
    return ApproachInfo(
        node_id=conn["node_id"], stop_pos=conn["points"][0],
        distance=distance, brake_distance=brake_distance, cap=cap,
        permitted=controller.would_permit(vehicle))


def rule_intersection_approach(vehicle, ctx):
    """Slow to a smooth stop at the stop line of the next CONTROLLED junction
    while entry is not yet permitted.

    If permission is already available, the rule has NO effect (returns INF): a
    vehicle approaching an open junction is never slowed. Otherwise it returns
    the kinematic smooth-stop speed cap, so the governor's min() eases the
    vehicle down to 0 right at the stop line and lets it resume the instant the
    controller opens. It composes with every other rule through that min(), and
    it only ever proposes a speed -- the controller decides permission, the
    dynamics layer achieves the speed, movement does the actual gating."""
    info = _intersection_approach(vehicle, ctx)
    if info is None or info.permitted:
        return INF
    return info.cap


def approach_info(vehicle, ctx=None):
    """Public accessor (for debug overlays): the ApproachInfo for `vehicle`, or
    None when it isn't approaching a controlled junction. Read-only."""
    return _intersection_approach(vehicle, ctx or _EMPTY_CONTEXT)


# Ordered (name, rule) pairs. Append new rules here -- nothing else changes.
DECISION_RULES = (
    ("cruise", rule_cruise),
    ("follow", rule_following_distance),
    ("approach", rule_intersection_approach),
)


# ----------------------------------------------------------------------
# Governor: desired_speed = min(all proposals).
# ----------------------------------------------------------------------

def proposals(vehicle, ctx=None, rules=DECISION_RULES):
    """[(rule_name, proposed_speed_ft_s), ...] for `vehicle`: every rule's speed
    cap, INF where a rule has no opinion. Pure; for the combinator and debug."""
    ctx = ctx or _EMPTY_CONTEXT
    return [(name, fn(vehicle, ctx)) for name, fn in rules]


def decide_desired_speed(vehicle, ctx=None, rules=DECISION_RULES):
    """The most restrictive proposal -- the decided desired_speed (ft/s)."""
    return min(speed for _, speed in proposals(vehicle, ctx, rules))


def binding_rule(vehicle, ctx=None, rules=DECISION_RULES):
    """Name of the rule currently setting desired_speed (the min proposer).
    Computed on demand for debug/inspection; never stored on the vehicle."""
    return min(proposals(vehicle, ctx, rules), key=lambda pair: pair[1])[0]


def compute_decisions(vehicles, ctx=None, rules=DECISION_RULES):
    """Decision pass: set every vehicle.desired_speed from its rules. Writes
    ONLY desired_speed; touches nothing else (movement, dynamics and perception
    are all left untouched). `ctx` (a DecisionContext) gives rules read-only
    access to outside systems (e.g. intersection controllers)."""
    ctx = ctx or _EMPTY_CONTEXT
    for vehicle in vehicles:
        vehicle.desired_speed = decide_desired_speed(vehicle, ctx, rules)
