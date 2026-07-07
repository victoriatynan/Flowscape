"""
Intersection Control Framework.

A distinct environmental question in the driver model: not "what does the
vehicle want?" (decision) or "how does it move?" (dynamics), but "may it ENTER
this junction right now?" This module owns junction gatekeeping and nothing
else.

Layered position
----------------
The MOVEMENT layer asks an IntersectionController for permission before a
vehicle enters a junction connection segment; the controller answers yes/no and
tracks who is inside. It is independent of:
  - vehicle DYNAMICS  -- it never reads or sets speed; and
  - the DECISION layer -- it never sets desired_speed.
The controller answers ONLY whether entry is permitted. Smoothly slowing for a
future red light or stop sign is the decision layer's job (set desired_speed);
the controller is the hard safety GATE. The two concerns are orthogonal and
compose -- decision shapes the approach speed, the controller guarantees no
unpermitted entry. (A vehicle denied entry is hard-held at the junction mouth by
movement; its followers queue behind it via the existing car-following decision
rule. Only the frontmost held vehicle keeps a non-zero speed for now -- zeroing
it smoothly is a future decision rule, deliberately out of scope here.)

Controller hierarchy
--------------------
  IntersectionController            -- base interface + occupancy. Always grants.
    ReservationController           -- exclusive access to CONFLICTING movements.
                                       The reusable base for all real control:
      StopSignController            -- wait-your-turn, then super().can_enter()
      TrafficLightController        -- phase is green, then super().can_enter()
      YieldController                -- no priority traffic, then super().can_enter()
      (future) RoundaboutController -- refine movements_conflict(), reuse the rest

Future types add their distinguishing policy ON TOP of super().can_enter() and
register in CONTROLLER_TYPES; they never re-implement mutual exclusion, and
vehicle movement never changes. New types are selected per node by
make_controller() from node.data['control'].

Design philosophy (shared with the rest of Flowscape): a controller holds the
minimal LOGICAL state (who is inside, active reservations, plus future
phase/queue state); the set of controlled nodes is rebuilt from the network
topology on demand, never persisted. This module imports nothing from
traffic_sim / dynamics / decision -- it is a leaf, so movement can depend on it
without a cycle. (It does share the turn-classification vocabulary with
lane_graph, the single source of truth for what counts as LEFT/RIGHT/STRAIGHT/
UTURN; importing those constants is a one-way leaf->leaf dependency, no cycle.)
"""

import math
import os
from dataclasses import dataclass

from lane_graph import (TURN_STRAIGHT, TURN_LEFT, TURN_RIGHT, TURN_UTURN,
                        TURN_COLORS)

CONTROL_UNCONTROLLED = "uncontrolled"
CONTROL_RESERVATION = "reservation"
CONTROL_TRAFFIC_LIGHT = "traffic_light"
CONTROL_YIELD = "yield"
# Future control kinds: listed in the editor's control-type selector as disabled
# placeholders, but deliberately NOT registered in CONTROLLER_TYPES yet (no
# concrete controller class), so they can't be instantiated. Adding a controller
# class + a CONTROLLER_TYPES entry is all that's needed to enable one.
CONTROL_ROUNDABOUT = "roundabout"

# Default control for a junction node when its data doesn't say otherwise.
# Intersections are reservation-managed out of the box; set node.data['control']
# = 'uncontrolled' to opt a node out (e.g. for testing).
DEFAULT_INTERSECTION_CONTROL = CONTROL_RESERVATION

# How long (frames) a reservation grant/release event stays in the debug overlay.
TRANSITION_TTL_FRAMES = 45


def junction_radius(network, node_id):
    """Approximate world-space radius (feet) of a junction, from the largest
    trim its roads pull back -- used to size the debug disc / place labels."""
    return max((network.road_trim_at_node(r, node_id)
                for r in network.roads_for_node(node_id)), default=12.0) or 12.0


class IntersectionController:
    """Per-intersection-node gatekeeper. Base policy: grant immediately.

    The interface vehicle movement depends on is exactly the three methods
    can_enter()/vehicle_enter()/vehicle_exit(). Subclasses override can_enter()
    with their own policy and may keep extra state, but keep this interface, so
    movement never changes as new types are added. begin_step() is an optional
    once-per-frame hook (clearing transient per-frame state, advancing timers).
    """

    kind = CONTROL_UNCONTROLLED

    def __init__(self, node_id):
        self.node_id = node_id
        # Vehicles currently inside the junction. An identity list, not a set:
        # Vehicle is a mutable (unhashable) dataclass, so we never hash it or
        # use == on it -- only `is`.
        self.occupants = []

    # --- the interface vehicle movement uses -------------------------------
    def can_enter(self, vehicle):
        """May `vehicle` enter the junction now? Base: always yes. Override this
        (and only this, plus any state it needs) for reservations, stop signs,
        lights, etc."""
        return True

    # --- read-only query used by the DECISION layer ------------------------
    def would_permit(self, vehicle):
        """Would entry be granted right now -- with NO side effects? Base: yes.

        Same question as can_enter(), but guaranteed side-effect-free: it never
        records a waiter, never touches reservations, never moves anything. The
        decision layer consults this to plan a smooth approach to the stop line;
        MOVEMENT still uses can_enter() as the actual gate. (The controller still
        only answers whether entry is permitted -- this just lets it be asked
        without committing.)"""
        return True

    def vehicle_enter(self, vehicle):
        """Register `vehicle` as inside the junction. Movement calls this
        immediately after a granted can_enter()."""
        if all(v is not vehicle for v in self.occupants):
            self.occupants.append(vehicle)

    def vehicle_exit(self, vehicle):
        """Deregister `vehicle` as it leaves the junction onto the next lane."""
        self.occupants = [v for v in self.occupants if v is not vehicle]

    def begin_step(self, vehicles, dt):
        """Once-per-frame hook, called before the movement pass with the live
        vehicle list and the frame's dt. Base: nothing. Subclasses clear
        per-frame transient state, advance timers, and observe approaching
        vehicles here (the one place a controller is handed the world)."""

    @property
    def occupancy(self):
        return len(self.occupants)

    # --- optional debug visualization (polymorphic per controller type) ----
    def visual_layers(self, network):
        """Generic shape dicts (see RoadRenderer.draw_visual_layers) for THIS
        controller: a translucent disc + 'kind:count' label, green when occupied
        and blue when empty, plus a marker on each occupant. Subclasses extend
        this with their own state (super().visual_layers() + extras). Read-only.
        """
        node = network.nodes.get(self.node_id)
        if node is None:
            return []
        radius = junction_radius(network, self.node_id)
        occupied = self.occupancy > 0
        layers = [
            {"shape": "circle", "pos": node.pos, "radius": radius,
             "color": (90, 200, 90) if occupied else (90, 170, 255),
             "alpha": 70 if occupied else 40},
            {"shape": "text", "pos": node.pos,
             "text": f"{self.kind}:{self.occupancy}", "color": (240, 240, 240)},
        ]
        for vehicle in self.occupants:
            layers.append({"shape": "circle", "pos": vehicle.pos, "radius": 4.0,
                           "color": (90, 200, 90), "alpha": 220})
        return layers


# ----------------------------------------------------------------------
# Reservation-based control.
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class Movement:
    """A junction movement as a FIRST-CLASS semantic object: the directed lane
    pair plus its turn classification.

    The `lane_pair` (incoming, outgoing) is the IDENTITY -- exactly the tuple the
    reservation system used before -- so conflict resolution and any persistence
    are unchanged. `turn_type` is ADDITIONAL semantics (LEFT / RIGHT / STRAIGHT /
    UTURN, the same vocabulary lane_graph assigns to every connection) that
    policy controllers can reason about WITHOUT re-deriving geometry: a traffic
    light can release all STRAIGHT movements on an axis, a roundabout can
    prioritize circulating turns, a yield can defer only to conflicting LEFTs.
    The base ReservationController ignores turn_type entirely (it resolves
    conflicts on the lane pair), so adding this changes no existing behavior."""
    incoming: tuple                  # incoming directed lane_id (road_id,"F"/"R",idx)
    outgoing: tuple                  # outgoing directed lane_id
    turn_type: str = TURN_STRAIGHT   # LEFT | RIGHT | STRAIGHT | UTURN

    @property
    def lane_pair(self):
        """The (incoming, outgoing) identity -- the old movement tuple, so
        existing conflict logic and equality are preserved verbatim."""
        return (self.incoming, self.outgoing)


@dataclass
class Reservation:
    """One vehicle's exclusive claim on a Movement through the junction."""
    vehicle: object
    movement: Movement


class ReservationController(IntersectionController):
    """Grants a vehicle entry only when its intended movement does not conflict
    with any movement already reserved -- exclusive access to conflicting
    movements through the junction.

    A vehicle's movement is (current_lane, next_lane), read straight off the
    vehicle (no movement-layer change). A request is granted iff no other active
    reservation's movement conflicts with it; the reservation is recorded on
    entry and released on exit, so the junction frees up the instant the vehicle
    clears it. Non-conflicting movements (by default, only the SAME movement --
    e.g. a platoon making the identical turn) may hold reservations at once.

    This is the reusable base for stop signs / lights / yields / roundabouts:
    they add their own precondition before delegating to super().can_enter() for
    the conflict exclusion, and/or sharpen movements_conflict() with real
    geometry. They never reimplement the reservation lifecycle below.
    """

    kind = CONTROL_RESERVATION

    def __init__(self, node_id):
        super().__init__(node_id)
        self.reservations = []          # [Reservation] active claims
        self._waiting = []              # vehicles denied THIS frame (transient)
        self._events = []               # [[text, ttl_frames, color]] for debug

    # --- conflict model (override point) -----------------------------------
    def movements_conflict(self, m1, m2):
        """Do two Movements conflict (cannot be in the junction together)?

        Base policy is conservative and geometry-free, resolved purely on the
        LANE-PAIR identity (turn_type is deliberately ignored here, so this is
        byte-for-byte the behavior from before Movement existed): any two
        DIFFERENT lane pairs conflict; an identical pair (same in->out lane) does
        not, so vehicles making the same turn still flow (car-following spaces
        them). Policy subclasses (roundabout, yield, light) override this to
        reason about `m1.turn_type` / `m2.turn_type` and real crossing geometry;
        everything else is reused unchanged."""
        return m1.lane_pair != m2.lane_pair

    # --- the interface vehicle movement uses -------------------------------
    def can_enter(self, vehicle):
        movement = self._movement(vehicle)
        if movement is None:
            return True                 # indeterminate -> don't block
        if self._conflicting_reservation(vehicle, movement) is not None:
            if all(v is not vehicle for v in self._waiting):
                self._waiting.append(vehicle)   # remains stopped at the mouth
            return False
        return True

    def would_permit(self, vehicle):
        """Read-only permission query for the DECISION layer's approach planning:
        would this vehicle's movement be granted right now? Reuses the SAME
        predicate as can_enter() (no conflicting reservation), but with no side
        effects -- it does not record the vehicle as waiting and does not touch
        reservations. Reservation grant/release logic is entirely unchanged."""
        movement = self._movement(vehicle)
        if movement is None:
            return True
        return self._conflicting_reservation(vehicle, movement) is None

    def vehicle_enter(self, vehicle):
        super().vehicle_enter(vehicle)          # occupancy tracking
        movement = self._movement(vehicle)
        if movement is not None:
            self.reservations.append(Reservation(vehicle, movement))
            self._note(f"+grant {self._movement_label(movement)}", (120, 230, 140))
        self._waiting = [v for v in self._waiting if v is not vehicle]

    def vehicle_exit(self, vehicle):
        super().vehicle_exit(vehicle)
        before = len(self.reservations)
        self.reservations = [r for r in self.reservations if r.vehicle is not vehicle]
        if len(self.reservations) != before:
            self._note("-release", (180, 180, 180))

    def begin_step(self, vehicles, dt):
        # Waiting is recomputed every frame from the denials in can_enter().
        self._waiting = []
        # Age out reservation-transition flashes.
        for event in self._events:
            event[1] -= 1
        self._events = [e for e in self._events if e[1] > 0]

    # --- reservation helpers ----------------------------------------------
    def _movement(self, vehicle):
        """The Movement `vehicle` is about to take through THIS node, or None if
        undeterminable. The lane pair is read off the vehicle's own current/next
        lane at the moment of the request (before movement reassigns
        current_lane); the turn classification comes from the vehicle's compiled
        connection segment for this node (set from lane_graph). Subclasses get
        the full semantic object via self._movement(vehicle)."""
        incoming = getattr(vehicle, "current_lane", None)
        outgoing = getattr(vehicle, "next_lane", None)
        if incoming is None or outgoing is None:
            return None
        return Movement(incoming, outgoing, self._turn_type(vehicle, outgoing))

    def _turn_type(self, vehicle, outgoing):
        """Turn classification for this node's movement into `outgoing`, read
        from the vehicle's compiled connection segment (which carries the
        lane_graph turn_type). Defaults to STRAIGHT if the segment lacks it."""
        for seg in getattr(vehicle, "segments", ()) or ():
            if (seg.get("kind") == "connection"
                    and seg.get("node_id") == self.node_id
                    and seg.get("lane_id") == outgoing):
                return seg.get("turn_type", TURN_STRAIGHT)
        return TURN_STRAIGHT

    def _conflicting_reservation(self, vehicle, movement):
        """First active reservation (held by a DIFFERENT vehicle) whose movement
        conflicts with `movement`, or None."""
        for reservation in self.reservations:
            if reservation.vehicle is vehicle:
                continue
            if self.movements_conflict(movement, reservation.movement):
                return reservation
        return None

    def _approach_distance(self, vehicle):
        """Along-lane distance (feet) from `vehicle` to THIS node's stop line, if
        it is on a lane whose next connection is this junction; else None. Reads
        only the vehicle's own compiled path -- approach detection, not anything
        about reservations. Shared by stop-sign and yield policies."""
        segs = getattr(vehicle, "segments", None)
        i = getattr(vehicle, "seg_index", 0)
        if not segs or i + 1 >= len(segs):
            return None
        seg = segs[i]
        if seg["kind"] != "lane":
            return None
        nxt = segs[i + 1]
        if nxt["kind"] != "connection" or nxt.get("node_id") != self.node_id:
            return None
        return seg["length"] - vehicle.seg_s

    @staticmethod
    def _movement_label(movement):
        # Compact "in_road>out_road TURN" tag: lane-pair identity + classified
        # movement type (lane_id = (road_id, dir, index)).
        return (f"{movement.incoming[0]}>{movement.outgoing[0]} "
                f"{movement.turn_type}")

    def _note(self, text, color):
        self._events.append([text, TRANSITION_TTL_FRAMES, color])
        if len(self._events) > 6:
            self._events = self._events[-6:]

    # --- debug visualization ----------------------------------------------
    def visual_layers(self, network):
        layers = super().visual_layers(network)   # disc + count + occupant dots
        node = network.nodes.get(self.node_id)
        if node is None:
            return layers
        radius = junction_radius(network, self.node_id)

        # Reservation OWNERS: link + tag color-coded by the CLASSIFIED movement
        # type (lane_graph's turn colors: STRAIGHT green / LEFT orange / RIGHT
        # blue / UTURN red), with the "in>out TURN" label showing the movement.
        for reservation in self.reservations:
            owner = reservation.vehicle
            color = TURN_COLORS.get(reservation.movement.turn_type, (90, 220, 120))
            layers.append({"shape": "line", "points": [node.pos, owner.pos],
                           "color": color, "width": 2})
            layers.append({"shape": "text", "pos": owner.pos,
                           "text": f"R {self._movement_label(reservation.movement)}",
                           "color": color})

        # WAITING vehicles (denied this frame): amber marker + link to the mouth.
        for waiter in self._waiting:
            layers.append({"shape": "line", "points": [node.pos, waiter.pos],
                           "color": (255, 180, 70), "width": 1})
            layers.append({"shape": "circle", "pos": waiter.pos, "radius": 5.0,
                           "color": (255, 180, 70), "alpha": 200})

        # Reservation TRANSITIONS: recent grant/release events stacked below.
        for i, (text, _ttl, color) in enumerate(reversed(self._events)):
            layers.append({"shape": "text",
                           "pos": (node.x, node.y + radius + 8.0 + i * 10.0),
                           "text": text, "color": color})
        return layers


# ----------------------------------------------------------------------
# Stop sign: a POLICY layer on top of the reservation CONCURRENCY layer.
# ----------------------------------------------------------------------

CONTROL_STOP_SIGN = "stop_sign"

# A vehicle at or below this speed (ft/s) counts as having fully stopped.
STOP_SPEED_EPS_FT_S = 0.5
# How close to the junction mouth a vehicle must be to count as 'arrived' at the
# sign (feet) -- a bit beyond the decision layer's stop-line setback so a car
# halted at the line is detected. Pure approach geometry, not reservation logic.
ARRIVAL_DISTANCE_FT = 20.0
# Default dwell time at the stop line (seconds). Configurable per node via
# node.data['stop_duration'] (see make_controller) or per instance.
DEFAULT_STOP_DURATION_S = 2.0

# Stop-sign debug overlay colors.
STOPSIGN_QUEUE_COLOR = (255, 200, 80)      # queued, not yet eligible
STOPSIGN_ELIGIBLE_COLOR = (90, 230, 120)   # front of queue, stop done -> may go


@dataclass
class StopEntry:
    """One vehicle's place in a stop sign's FIFO arrival queue."""
    vehicle: object
    stopped: bool = False     # has it completed a full stop yet?
    timer: float = 0.0        # seconds elapsed since it stopped


class StopSignController(ReservationController):
    """All-way stop sign -- the first concrete traffic-control POLICY.

    It owns ONLY stop-sign policy: arrival detection, complete-stop
    verification, a FIFO arrival queue, a configurable dwell time, and queue
    cleanup. It decides WHEN a vehicle is eligible to request a reservation, and
    delegates EVERYTHING about concurrency -- conflict detection, reservation
    ownership, release, waiters, transitions -- to ReservationController,
    unchanged (no reservation logic is duplicated here).

    A vehicle is eligible only once it is at the FRONT of the arrival queue, has
    come to a complete stop, and has waited stop_duration. Eligibility gates the
    two questions the controller already answers -- the read-only would_permit()
    (so the decision-layer approach rule eases the car to a smooth stop) and the
    can_enter() movement gate (the hard backstop) -- and only THEN does the
    unchanged base decide whether the movement conflicts with traffic inside.
    """

    kind = CONTROL_STOP_SIGN

    def __init__(self, node_id, stop_duration=DEFAULT_STOP_DURATION_S):
        super().__init__(node_id)
        self.stop_duration = stop_duration   # configurable dwell time (seconds)
        self._queue = []                     # [StopEntry], index 0 = first arrival

    # --- policy: eligibility (pure -- reads queue state, never mutates) ------
    def _eligible(self, vehicle):
        """May `vehicle` request a reservation now? It must be at the FRONT of
        the FIFO queue, fully stopped, and past the dwell time. Pure, so
        would_permit()/can_enter() stay safe to call repeatedly per frame."""
        if not self._queue:
            return False
        front = self._queue[0]
        return (front.vehicle is vehicle and front.stopped
                and front.timer >= self.stop_duration)

    # --- policy gates: eligibility, THEN the unchanged reservation logic -----
    def would_permit(self, vehicle):
        # Read-only twin used by the decision approach rule. Stays pure.
        return self._eligible(vehicle) and super().would_permit(vehicle)

    def can_enter(self, vehicle):
        # Movement gate / hard backstop: not eligible -> hold (and don't record
        # a waiter; queued cars are tracked by this controller, not the base).
        if not self._eligible(vehicle):
            return False
        return super().can_enter(vehicle)

    def vehicle_enter(self, vehicle):
        # Base owns the reservation + occupancy; we only drop the proceeding
        # vehicle from our queue (so the next arrival becomes the front).
        super().vehicle_enter(vehicle)
        self._dequeue(vehicle)

    # --- policy: per-frame arrival detection, stop timing, queue cleanup -----
    def begin_step(self, vehicles, dt):
        super().begin_step(vehicles, dt)     # base clears waiters / ages events

        present = []
        for vehicle in vehicles:
            distance = self._approach_distance(vehicle)
            if distance is not None and distance <= ARRIVAL_DISTANCE_FT:
                present.append((distance, vehicle))
        present_ids = {id(v) for _, v in present}

        # Queue cleanup: drop anyone who has left the approach (entered the
        # junction, was culled, or is no longer near the line).
        self._queue = [e for e in self._queue if id(e.vehicle) in present_ids]

        # Arrival detection: append newly-arrived vehicles, nearest-the-line
        # first as a deterministic FIFO tie-break.
        queued_ids = {id(e.vehicle) for e in self._queue}
        for _distance, vehicle in sorted(present, key=lambda dv: dv[0]):
            if id(vehicle) not in queued_ids:
                self._queue.append(StopEntry(vehicle))
                queued_ids.add(id(vehicle))

        # Complete-stop verification + dwell timing.
        for entry in self._queue:
            if getattr(entry.vehicle, "current_speed", 0.0) <= STOP_SPEED_EPS_FT_S:
                entry.stopped = True          # latched once stopped
                entry.timer += dt

    # --- helpers (approach detection is path geometry, not reservation logic)-
    def _dequeue(self, vehicle):
        self._queue = [e for e in self._queue if e.vehicle is not vehicle]

    # --- debug visualization (extends the base's owners/waiters/transitions) -
    def visual_layers(self, network):
        layers = super().visual_layers(network)
        for idx, entry in enumerate(self._queue):
            vehicle = entry.vehicle
            eligible = self._eligible(vehicle)
            color = STOPSIGN_ELIGIBLE_COLOR if eligible else STOPSIGN_QUEUE_COLOR
            label = f"#{idx + 1}"                 # FIFO position
            if entry.stopped:
                label += f" {entry.timer:.1f}/{self.stop_duration:.0f}s"  # elapsed timer
            if eligible:
                label += " GO"                    # currently eligible vehicle
            layers.append({"shape": "circle", "pos": vehicle.pos, "radius": 6.0,
                           "color": color, "alpha": 200})
            layers.append({"shape": "text",
                           "pos": (vehicle.pos[0], vehicle.pos[1] - 16.0),
                           "text": label, "color": color})
        return layers


# ----------------------------------------------------------------------
# Yield / give-way: through-traffic has priority.
# ----------------------------------------------------------------------

# How close a conflicting priority (through) vehicle must be for a yielding
# (turning) vehicle to wait for it (feet). Larger = more cautious merges.
YIELD_GAP_FT = 45.0


class YieldController(ReservationController):
    """Yield / give-way. STRAIGHT (through) movements have priority; a vehicle
    making a TURN defers to any conflicting priority movement that is inside the
    junction OR approaching within `yield_gap`. Once clear it falls through to
    the unchanged reservation logic (which still guarantees collision-free
    exclusion), so a yield is always at least as safe as plain reservation --
    it only changes WHO waits (turners), not the safety guarantee.

    Turn-type is the priority signal (per the framework's design note), so the
    controller stays geometry-light and needs no knowledge of road classes: a
    driveway car turning onto a road yields to the through-traffic it crosses.
    A geometry-aware refinement (yield only to actually-crossing directions) is
    a future subclass concern -- deferring to all conflicting through-traffic is
    the safe, simple give-way rule.
    """

    kind = CONTROL_YIELD

    def __init__(self, node_id, yield_gap=YIELD_GAP_FT):
        super().__init__(node_id)
        self.yield_gap = yield_gap
        self._priority_movements = []   # approaching STRAIGHT movements, this frame

    # --- policy: a turning vehicle waits for conflicting priority traffic -----
    def _must_yield(self, vehicle, movement):
        for r in self.reservations:
            if (r.vehicle is not vehicle and r.movement.turn_type == TURN_STRAIGHT
                    and self.movements_conflict(movement, r.movement)):
                return True             # priority traffic already in the junction
        for m in self._priority_movements:
            if self.movements_conflict(movement, m):
                return True             # priority traffic approaching within the gap
        return False

    def _may_proceed(self, vehicle):
        movement = self._movement(vehicle)
        if movement is None or movement.turn_type == TURN_STRAIGHT:
            return True                 # straight-through -> never yields
        return not self._must_yield(vehicle, movement)

    # --- policy gates: yield precondition, THEN the unchanged reservation logic
    def would_permit(self, vehicle):
        return self._may_proceed(vehicle) and super().would_permit(vehicle)

    def can_enter(self, vehicle):
        if not self._may_proceed(vehicle):
            return False
        return super().can_enter(vehicle)

    def begin_step(self, vehicles, dt):
        super().begin_step(vehicles, dt)
        # Snapshot the STRAIGHT (priority) movements approaching this junction
        # within the gap, so the per-vehicle yield check is a cheap read.
        self._priority_movements = []
        for v in vehicles:
            d = self._approach_distance(v)
            if d is None or d > self.yield_gap:
                continue
            m = self._movement(v)
            if m is not None and m.turn_type == TURN_STRAIGHT:
                self._priority_movements.append(m)


# ----------------------------------------------------------------------
# Traffic light: axis-based 2-phase signal -- a POLICY layer on top of the
# reservation CONCURRENCY layer, same shape as stop signs and yields.
# ----------------------------------------------------------------------

TL_GREEN = "green"
TL_YELLOW = "yellow"
TL_ALL_RED = "all_red"

TL_STATE_COLORS = {
    TL_GREEN: (90, 230, 120),
    TL_YELLOW: (240, 200, 60),
    TL_ALL_RED: (220, 70, 70),
}

# Per-approach signal-head lamp placement: just beyond the junction disc, back
# along each road's own direction, roughly where a stopped car's hood would be.
SIGNAL_HEAD_OFFSET_FT = 15.0
SIGNAL_HEAD_RADIUS_FT = 5.0

# Placeholder signal-head art (tools/make_placeholder_traffic_light_icons.py),
# in the same "2d Assets" folder as the vehicle sprite -- a world-space sprite
# that rotates to face each approach, unlike the stop sign's fixed UI icon.
# Drop finished art at the same filenames to replace these with no code
# change. Missing files fall back to the plain colored lamp circle.
_TL_ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "2d Assets")
TL_ICON_PATHS = {
    TL_GREEN: os.path.join(_TL_ASSET_DIR, "trafficlight-green.png"),
    TL_YELLOW: os.path.join(_TL_ASSET_DIR, "trafficlight-yellow.png"),
    TL_ALL_RED: os.path.join(_TL_ASSET_DIR, "trafficlight-red.png"),
}
TL_ICON_HEIGHT_FT = 6.0


def _tl_icon_path(state):
    path = TL_ICON_PATHS.get(state)
    return path if path is not None and os.path.exists(path) else None


class TrafficLightController(ReservationController):
    """Signalized junction. It decides WHEN a movement may be attempted (is
    its approach's phase green right now?) and delegates conflict exclusion to
    the reservation lifecycle -- exactly like stop signs and yields, a wrong
    phase assignment can only make traffic wait longer, never cause a crash.

    Phases group the node's roads by approach bearing (opposite roads share a
    phase; see _axis_phase_groups), giving a simple 2-phase axis light for the
    common 4-way/T junction: e.g. N-S green, then E-W green. Left turns are
    permissive: they move on green, and movements_conflict() (refined with
    real turn-type geometry -- see below) makes them yield to the opposing
    through movement, while opposing STRAIGHT traffic and opposing turns flow
    concurrently. Protected-turn phases and non-axis geometries are a future
    refinement.

    One phase runs green_duration, then yellow_duration (no NEW entries --
    treated as a brief all-stop before the swap, the simplest safe choice),
    then all_red_duration (both axes stopped, clearing the junction) before
    the next phase's green. cycle_length is informational (nominally
    phase_count * (green+yellow+all_red)); phase advancement is driven
    directly by the per-state durations, not by cycle_length.
    """

    kind = CONTROL_TRAFFIC_LIGHT

    def __init__(self, node_id, network, cycle_length=60.0, green_duration=25.0,
                 yellow_duration=3.0, all_red_duration=2.0, initial_phase=0):
        super().__init__(node_id)
        self.cycle_length = cycle_length
        self.green_duration = green_duration
        self.yellow_duration = yellow_duration
        self.all_red_duration = all_red_duration
        self.initial_phase = initial_phase
        self._phase_groups, self._road_phase = self._axis_phase_groups(network)
        # Resolved on the first begin_step(), so a node-data override of
        # initial_phase -- applied by make_controller AFTER construction -- is
        # picked up before the phase clock starts.
        self._phase = None
        self._state = TL_GREEN
        self._state_timer = 0.0

    # --- phase geometry (override point: refine for non-axis junctions) -----
    def _axis_phase_groups(self, network):
        """Group this node's roads into 2 phases by approach bearing: sort
        roads by outward-tangent angle and alternate them. For a roughly
        evenly-spaced junction (4-way or T), alternating indices in angle
        order puts OPPOSITE approaches in the same phase (axis-based N-S vs
        E-W) -- the same angle-order trick the junction-polygon renderer uses
        (road_editor.py's _merge_junction_polygon). Returns
        ([set(road_id), set(road_id)], {road_id: phase_index})."""
        roads = network.roads_for_node(self.node_id)
        bearings = []
        for road in roads:
            tangent = network.outward_tangent_at_node(road, self.node_id)
            bearings.append((math.atan2(tangent[1], tangent[0]), road))
        bearings.sort(key=lambda pair: pair[0])
        groups = [set(), set()]
        road_phase = {}
        for i, (_angle, road) in enumerate(bearings):
            phase = i % 2
            groups[phase].add(road.id)
            road_phase[road.id] = phase
        return groups, road_phase

    # --- conflict model (TL-c: permissive lefts, real same-axis geometry) ---
    def movements_conflict(self, m1, m2):
        """Refine the base's conservative lane-pair-only conflict model with
        real turn-type geometry -- the exact override point its docstring
        names. Only ever asked about movements _is_green() already let
        through, so ordinarily both are on the SAME (currently green) axis;
        the cross-axis branch below only fires for a leftover reservation
        still clearing from the previous phase, and stays conservative.

          - SAME lane pair: never conflicts (base rule, unchanged -- a platoon).
          - DIFFERENT axis (only a stale prior-phase reservation can cause
            this): conflicts -- safe default, matches the base exactly.
          - SAME incoming road, same axis (lanes fanning out of one
            approach -- e.g. straight + left from the same road): no
            conflict, lane discipline already keeps them apart.
          - DIFFERENT (opposing) approaches, same axis:
              straight vs straight   -> no conflict (pass side by side)
              straight vs left/uturn -> conflict (permissive left YIELDS to
                                        the opposing through movement)
              turn vs turn           -> no conflict (opposing turns curve
                                        away from each other)
        """
        if m1.lane_pair == m2.lane_pair:
            return False
        if self._road_phase.get(m1.incoming[0]) != self._road_phase.get(m2.incoming[0]):
            return True
        if m1.incoming[0] == m2.incoming[0]:
            return False
        if m1.turn_type == TURN_STRAIGHT and m2.turn_type == TURN_STRAIGHT:
            return False
        if TURN_STRAIGHT in (m1.turn_type, m2.turn_type):
            return True
        return False

    # --- policy: is THIS vehicle's movement green right now? ----------------
    def _is_green(self, vehicle):
        if self._state != TL_GREEN:
            return False
        movement = self._movement(vehicle)
        if movement is None:
            return True                 # indeterminate -> don't block
        return self._road_phase.get(movement.incoming[0]) == self._phase

    # --- policy gates: phase precondition, THEN the unchanged reservation ---
    def would_permit(self, vehicle):
        return self._is_green(vehicle) and super().would_permit(vehicle)

    def can_enter(self, vehicle):
        # Not green -> held at the line (like a stop sign, not a base waiter;
        # the phase clock -- not a conflicting reservation -- is why it waits).
        if not self._is_green(vehicle):
            return False
        return super().can_enter(vehicle)

    # --- policy: advance the phase clock -------------------------------------
    def begin_step(self, vehicles, dt):
        super().begin_step(vehicles, dt)
        if self._phase is None:
            self._phase = int(self.initial_phase) % len(self._phase_groups)
        self._state_timer += dt
        duration = {TL_GREEN: self.green_duration,
                    TL_YELLOW: self.yellow_duration,
                    TL_ALL_RED: self.all_red_duration}[self._state]
        if self._state_timer < duration:
            return
        self._state_timer -= duration
        if self._state == TL_GREEN:
            self._state = TL_YELLOW
        elif self._state == TL_YELLOW:
            self._state = TL_ALL_RED
        else:
            self._state = TL_GREEN
            self._phase = (self._phase + 1) % len(self._phase_groups)

    # --- debug visualization (extends the base's owners/waiters/transitions) -
    # DYNAMIC, unlike a stop sign's static icon: the lamp colors change every
    # frame with the phase clock, so this must never be static-cached (see
    # RoadRenderer's _static_signature -- it excludes controller runtime state
    # for exactly this reason).
    def visual_layers(self, network):
        layers = super().visual_layers(network)
        if self._phase is None:
            return layers
        node = network.nodes.get(self.node_id)
        if node is None:
            return layers
        radius = junction_radius(network, self.node_id)
        color = TL_STATE_COLORS[self._state]
        layers.append({"shape": "text",
                       "pos": (node.x, node.y - radius - 12.0),
                       "text": f"{self._state.upper()} phase {self._phase}",
                       "color": color})

        # One signal-head lamp per approach, its state driven by whether ITS
        # phase is active right now: this controller's own state (green/
        # yellow/all-red) while it's this axis's turn, always all-red
        # otherwise (the other axis is never moving while it isn't its turn).
        for road in network.roads_for_node(self.node_id):
            phase = self._road_phase.get(road.id)
            if phase is None:
                continue
            lamp_state = self._state if phase == self._phase else TL_ALL_RED
            tangent = network.outward_tangent_at_node(road, self.node_id)
            lamp_pos = (node.x + tangent[0] * (radius + SIGNAL_HEAD_OFFSET_FT),
                       node.y + tangent[1] * (radius + SIGNAL_HEAD_OFFSET_FT))
            icon = _tl_icon_path(lamp_state)
            if icon is not None:
                # Face oncoming traffic: -tangent points from the lamp back
                # toward the junction, the direction an approaching driver
                # looks along.
                layers.append({"shape": "sprite", "pos": lamp_pos,
                               "heading": (-tangent[0], -tangent[1]),
                               "length_ft": TL_ICON_HEIGHT_FT, "image": icon})
            else:
                layers.append({"shape": "circle", "pos": lamp_pos,
                               "radius": SIGNAL_HEAD_RADIUS_FT,
                               "color": TL_STATE_COLORS[lamp_state], "alpha": 230})
        return layers


# Registry: control kind -> controller class. Future types add an entry here
# (e.g. CONTROLLER_TYPES["roundabout"] = RoundaboutController); movement is
# unaffected.
CONTROLLER_TYPES = {
    CONTROL_UNCONTROLLED: IntersectionController,
    CONTROL_RESERVATION: ReservationController,
    CONTROL_STOP_SIGN: StopSignController,
    CONTROL_YIELD: YieldController,
    CONTROL_TRAFFIC_LIGHT: TrafficLightController,
}


# ----------------------------------------------------------------------
# Control-type catalog + per-type settings schema (for the editor UI).
# ----------------------------------------------------------------------
#
# The editor's Intersection Control inspector renders ENTIRELY from this
# metadata -- the selector lists CONTROL_TYPE_ORDER (greying out anything not in
# CONTROL_TYPE_IMPLEMENTED), and a node's per-type settings come from
# control_settings_schema(). So a new controller is exposed by adding a label, a
# CONTROLLER_TYPES entry, and (optionally) a schema -- no UI code changes.

# Display order in the selector; labels shown to the user.
CONTROL_TYPE_ORDER = (CONTROL_UNCONTROLLED, CONTROL_RESERVATION, CONTROL_STOP_SIGN,
                      CONTROL_TRAFFIC_LIGHT, CONTROL_YIELD, CONTROL_ROUNDABOUT)
CONTROL_TYPE_LABELS = {
    CONTROL_UNCONTROLLED: "Uncontrolled",
    CONTROL_RESERVATION: "Reservation",
    CONTROL_STOP_SIGN: "Stop Sign",
    CONTROL_TRAFFIC_LIGHT: "Traffic Light",
    CONTROL_YIELD: "Yield",
    CONTROL_ROUNDABOUT: "Roundabout",
}
# Kinds with a real controller class (selectable now). Everything else in the
# order is a disabled placeholder until its class lands in CONTROLLER_TYPES.
CONTROL_TYPE_IMPLEMENTED = frozenset(CONTROLLER_TYPES.keys())


@dataclass(frozen=True)
class FieldSpec:
    """One editable per-controller setting, stored at node.data[key]. The
    Inspector renders a numeric stepper from this; make_controller() applies it
    to the controller instance (by attribute name == key)."""
    key: str
    label: str
    type: str           # "float" | "int"
    minimum: float
    maximum: float
    step: float
    default: float


# Per-control-kind settings. Stop sign is live; the traffic-light schema is
# defined ahead of its controller so enabling it later is pure data.
_CONTROL_SETTINGS = {
    CONTROL_STOP_SIGN: (
        FieldSpec("stop_duration", "Stop duration (s)", "float",
                  0.5, 10.0, 0.5, DEFAULT_STOP_DURATION_S),
    ),
    CONTROL_YIELD: (
        FieldSpec("yield_gap", "Yield gap (ft)", "float",
                  10.0, 120.0, 5.0, YIELD_GAP_FT),
    ),
    CONTROL_TRAFFIC_LIGHT: (
        FieldSpec("cycle_length", "Cycle length (s)", "float", 10.0, 180.0, 5.0, 60.0),
        FieldSpec("green_duration", "Green (s)", "float", 3.0, 120.0, 1.0, 25.0),
        FieldSpec("yellow_duration", "Yellow (s)", "float", 1.0, 10.0, 0.5, 3.0),
        FieldSpec("all_red_duration", "All-red (s)", "float", 0.0, 10.0, 0.5, 2.0),
        FieldSpec("initial_phase", "Initial phase", "int", 0.0, 8.0, 1.0, 0.0),
    ),
}


def control_settings_schema(kind):
    """Ordered settings (FieldSpec tuple) for a control kind; () if none."""
    return _CONTROL_SETTINGS.get(kind, ())


def make_controller(network, node_id):
    """Build the controller for an intersection node from its logical config
    (node.data['control'], default DEFAULT_INTERSECTION_CONTROL). The single
    place a controller TYPE is chosen; vehicle movement only ever sees the
    resulting interface. Per-node policy settings from control_settings_schema()
    are applied generically (attribute name == FieldSpec.key) where present."""
    data = network.nodes[node_id].data or {}
    kind = data.get("control", DEFAULT_INTERSECTION_CONTROL)
    cls = CONTROLLER_TYPES.get(kind, ReservationController)
    # TrafficLightController is the only type that needs junction geometry (to
    # group approaches into axis-based phases), so it alone takes `network`.
    if kind == CONTROL_TRAFFIC_LIGHT:
        controller = cls(node_id, network)
    else:
        controller = cls(node_id)
    for field in control_settings_schema(kind):
        value = data.get(field.key)
        if value is not None and hasattr(controller, field.key):
            setattr(controller, field.key, value)
    return controller


class IntersectionControl:
    """Owns one IntersectionController per controlled intersection node and
    routes node-addressed junction requests to the right one.

    'Controlled' = a true junction node (3+ roads). A 2-road continuation bend
    is NOT an intersection and gets no controller; a request for any uncontrolled
    node resolves to 'no controller' and is granted. That lets movement ask
    about EVERY junction connection uniformly, controlled or not.
    """

    def __init__(self, network):
        self.network = network
        self.controllers = {}
        self.rebuild()

    def rebuild(self):
        """(Re)build controllers from the current topology. Called when the
        network changes (spawn / route prep / reset). Occupancy and reservations
        are transient runtime state and refill as vehicles move."""
        self.controllers = {
            nid: make_controller(self.network, nid)
            for nid in self.network.nodes
            if self.network.is_intersection(nid)
        }

    def begin_step(self, vehicles, dt):
        """Per-frame hook, called once before the movement pass so controllers
        can clear transient state (waiters), advance timers, and observe the
        approaching vehicles."""
        for controller in self.controllers.values():
            controller.begin_step(vehicles, dt)

    def controller_for(self, node_id):
        return self.controllers.get(node_id)

    # --- the interface vehicle movement uses (node-addressed) --------------
    def can_enter(self, node_id, vehicle):
        c = self.controllers.get(node_id)
        return c is None or c.can_enter(vehicle)

    # --- read-only query for the decision layer (node-addressed) -----------
    def would_permit(self, node_id, vehicle):
        """Side-effect-free 'would entry be permitted?' for a node. Uncontrolled
        nodes resolve to permitted."""
        c = self.controllers.get(node_id)
        return c is None or c.would_permit(vehicle)

    def vehicle_enter(self, node_id, vehicle):
        c = self.controllers.get(node_id)
        if c is not None:
            c.vehicle_enter(vehicle)

    def vehicle_exit(self, node_id, vehicle):
        c = self.controllers.get(node_id)
        if c is not None:
            c.vehicle_exit(vehicle)

    # --- optional debug visualization --------------------------------------
    def visual_layers(self):
        """Concatenate every controller's own debug layers (polymorphic per
        type). Read-only."""
        layers = []
        for controller in self.controllers.values():
            layers += controller.visual_layers(self.network)
        return layers
