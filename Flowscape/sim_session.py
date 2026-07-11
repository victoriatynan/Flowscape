"""
Fixed-timestep headless simulation session (WEB_MIGRATION_PLAN.md Phase 2).

A SimulationSession owns the full runtime spine -- demand (generate_trips)
-> scheduling (TripScheduler) -> spawning (SpawnQueue) -> simulation
(TrafficSimulation) -- and advances it in FIXED timesteps, independent of
rendering, frame rate, or wall-clock time. No pygame, no window: this is
the "Simulation -> Update -> State" loop the web backend will wrap.

The per-tick step order is the strict pipeline the editor uses
(road_editor.InputController.update_traffic): CULL -> RELEASE -> EXPIRE
-> DRAIN -> ADVANCE. Determinism: given the same network (building seeds)
and the same settings, a session replays identically -- the clock advances
by exactly tick_dt per tick, so tick N is always the same sim time.
"""

import math

from destinations import BUILDING_TYPES, RESIDENTIAL, generate_trips
from sim_clock import TripScheduler
from spawn_queue import SpawnQueue, SpawnResult, DEFAULT_MAX_WAIT_SEC
from traffic_sim import TrafficSimulation

# Trip demo defaults: a watchable subset of the day's trips, played back over
# an accelerated clock. The full realistic count would be too many cars.
# (Owned here -- the simulation side -- and re-imported by the editor UI.)
DEMO_TRIP_LIMIT = 60        # per DAY. Tuned to the road's REAL throughput so
# demand doesn't outrun it: measured on the demo network, 60 trips/day clear
# with ~0% expiry and a ~29-car peak (under the 40 cap), while 65+ tips into
# congestion collapse (queue backs up, trips expire before a slot frees). The
# old value (100) lost ~38% of trips to expiry despite the "few expire" claim.
DEMO_START_HOUR = 6.5
DEMO_HOURS_PER_SEC = 0.1    # ~4-min day; slow enough that a building's cars
                            # space out and clear their origin instead of
                            # expiring at the spawn-clearance gate.
# Clamp the per-frame sim advance so a frame hitch/stall can't dump a huge
# batch of due trips into the spawn queue at once (Phase 2a). The fixed
# tick_dt must stay at or below this.
MAX_SIM_STEP_SEC = 0.1
# "Trips at once": cap on concurrent cars. When at the cap, a due departure
# waits until a car finishes its trip.
TRIPS_AT_ONCE_DEFAULT = 40
# How long a queued departure may wait (in REAL seconds) before it expires.
# Real-time, not sim-time: the wait budget must match how long the road
# actually takes to absorb a car (see spawn_queue.py). Owned here so the demo
# tuning lives next to the clock and concurrency knobs it's balanced against.
DEMO_MAX_WAIT_SEC = DEFAULT_MAX_WAIT_SEC

# Fixed simulation tick rate (ticks per real second at 1x). 60 ticks/sec
# matches the editor's frame-locked feel; snapshot broadcast and rendering
# rates are independent of this (see WEB_MIGRATION_PLAN.md).
DEFAULT_TICK_RATE = 60

# --- Unified single-clock prototype (OPT-IN; not the shipping default) -------
# The decoupled model above is the default: an accelerated DEMAND clock over
# real-time MOTION. This experimental mode instead runs ONE clock -- motion,
# demand, and expiry all advance together in sim-time at `time_scale`
# sim-seconds per real second. Because you cannot just scale the physics dt
# (at the demo's 360x that's 264 ft/tick, which shatters car-following and
# junction gating), the vehicle physics is SUB-STEPPED: ceil(time_scale)
# tick-sized advances per tick. That keeps motion stable but makes compute
# scale with time_scale -- the core trade this prototype exists to expose.
# With one clock the sim-time expiry is finally honest (the road absorbs cars
# on the same clock demand arrives on), so no real-vs-sim mismatch remains.
UNIFIED_TIME_SCALE_DEFAULT = 8.0    # sim-sec per real sec (a 24h day in ~3 hr)
UNIFIED_MAX_WAIT_SIM_SEC = 900.0    # expiry grace in SIM-seconds (15 sim-min)
SEC_PER_HOUR = 3600.0


class SimulationSession:
    """Headless, fixed-timestep wrapper around one running simulation.

    Construction wires the spine and seeds occupancy (homes start "full");
    each tick() advances exactly 1/tick_rate seconds of real time. All
    randomness is seed-driven upstream (building seeds -> generate_trips),
    so two sessions over identical networks stay in lockstep forever.
    """

    def __init__(self, network, *,
                 trip_limit=DEMO_TRIP_LIMIT,
                 start_hour=DEMO_START_HOUR,
                 hours_per_second=DEMO_HOURS_PER_SEC,
                 max_vehicles=TRIPS_AT_ONCE_DEFAULT,
                 max_wait_seconds=DEMO_MAX_WAIT_SEC,
                 tick_rate=DEFAULT_TICK_RATE,
                 unified=False,
                 time_scale=UNIFIED_TIME_SCALE_DEFAULT,
                 unified_max_wait_sim_sec=UNIFIED_MAX_WAIT_SIM_SEC):
        if not network.buildings:
            raise ValueError("network has no buildings -- nothing generates trips")
        self.tick_dt = 1.0 / float(tick_rate)
        if self.tick_dt > MAX_SIM_STEP_SEC:
            raise ValueError(f"tick_rate {tick_rate} gives dt {self.tick_dt:.3f}s "
                             f"> MAX_SIM_STEP_SEC {MAX_SIM_STEP_SEC}s")
        self.network = network
        self.max_vehicles = max_vehicles
        self.tick_count = 0
        # Real (wall-equivalent) seconds elapsed, advancing by exactly tick_dt
        # per tick. This is the clock the spawn queue's wait/expiry runs on --
        # deliberately separate from scheduler.time (accelerated sim-hours).
        self.sim_real_time = 0.0

        # Unified single-clock mode (opt-in). In unified mode ONE clock drives
        # everything: the demand clock is pinned to `time_scale` (sim-sec/real-
        # sec), the physics is sub-stepped to stay stable, and the spawn queue's
        # wait/expiry is timed in that same sim-time. Default (unified=False)
        # leaves the decoupled model bit-for-bit unchanged.
        self.unified = unified
        self.time_scale = float(time_scale)
        self.last_substeps = 1   # physics sub-steps run on the most recent tick
        if unified:
            # One clock: the demand clock advances at time_scale sim-sec/real-sec.
            hours_per_second = self.time_scale / SEC_PER_HOUR
            max_wait_seconds = unified_max_wait_sim_sec   # now SIM-seconds

        self.traffic = TrafficSimulation(network)
        self.traffic.prepare_routes()

        def day_trips(day_index):
            # day_index 0 = Monday; 5/6 = Sat/Sun (no work on weekends). Each
            # day gets its own deterministic rng so days vary but replay the
            # same. The scheduler calls this once per day, forever.
            weekend = (day_index % 7) >= 5
            return generate_trips(network, day_index=day_index,
                                  limit=trip_limit, weekend=weekend)

        self.scheduler = TripScheduler(day_trips, start_hour=start_hour,
                                       hours_per_second=hours_per_second)
        self.spawn_queue = SpawnQueue(max_wait_seconds=max_wait_seconds)

        # Seed occupancy: homes start "full" (cars parked), everything else
        # empty; arrivals/departures move the counts from there.
        self.building_occupancy = {}
        for b in network.buildings.values():
            bt = BUILDING_TYPES.get(b.building_type)
            self.building_occupancy[b.id] = (
                bt.capacity if (bt and bt.category == RESIDENTIAL) else 0)

    # ------------------------------------------------------------------
    # The fixed-timestep loop
    # ------------------------------------------------------------------

    def tick(self):
        """Advance the simulation by exactly one fixed timestep."""
        self._step(self.tick_dt)
        self.tick_count += 1

    def run(self, ticks):
        """Advance `ticks` fixed timesteps (a blocking batch run)."""
        for _ in range(ticks):
            self.tick()

    def _step(self, dt):
        """One simulation step, in the strict pipeline order the editor uses:
        cull -> release -> expire -> drain -> advance."""
        # Advance the real-time clock first, so the spawn queue's wait/expiry
        # (below) is timed in real seconds regardless of the demand clock's
        # acceleration. tick_dt is fixed, so this stays deterministic.
        self.sim_real_time += dt

        # 1. CULL: finished cars free up slots and credit their destination
        #    building's occupancy (+1), capped at capacity (the demo flow
        #    isn't conservation-exact).
        for v in self.traffic.cull_arrived():
            bid = v.dest_building_id
            building = self.network.buildings.get(bid) if bid is not None else None
            if building is not None:
                bt = BUILDING_TYPES.get(building.building_type)
                cap = bt.capacity if bt else self.building_occupancy.get(bid, 0) + 1
                self.building_occupancy[bid] = min(
                    cap, self.building_occupancy.get(bid, 0) + 1)

        # 2. RELEASE: the scheduler hands each due trip to the queue with its
        #    route resolved ONCE here; a trip with no path is dropped now and
        #    never retried (so retries never re-run pathfinding).
        def release(trip):
            path = self.traffic.resolve_route(trip.origin_node_id,
                                              trip.dest_node_id)
            if path is None:
                self.spawn_queue.dropped_no_path += 1
                return
            self.spawn_queue.enqueue(trip, path, self._wait_now())
        self.scheduler.update(dt, release)

        # 3. EXPIRE: trips that waited too long are dropped. No occupancy
        #    credit -- the attempt failed, so the origin stays "full". The wait
        #    clock (_wait_now) is REAL seconds in the decoupled default and
        #    SIM seconds in unified mode; either way grace matches the clock the
        #    road actually absorbs cars on.
        self.spawn_queue.expire(self._wait_now())

        # 4. DRAIN: spawn under the concurrency cap + the visible-rate budget.
        #    A clearance-blocked origin is retried (BLOCKED), a vanished route
        #    is dropped (INVALID); a car that leaves drops origin occupancy.
        free_slots = max(0, self.max_vehicles - len(self.traffic.vehicles))

        def do_spawn(trip, path):
            if not self.traffic.route_valid(path):
                return SpawnResult.INVALID
            v = self.traffic.spawn_on_route(path, dest_node_id=trip.dest_node_id,
                                            dest_building_id=trip.dest_building_id)
            return SpawnResult.SPAWNED if v is not None else SpawnResult.BLOCKED

        for trip in self.spawn_queue.drain(dt, free_slots, do_spawn):
            if trip.origin_building_id is not None:
                self.building_occupancy[trip.origin_building_id] = max(
                    0, self.building_occupancy.get(trip.origin_building_id, 0) - 1)

        # 5. ADVANCE the vehicle simulation (sub-stepped in unified mode).
        self._advance_physics(dt)

    def _wait_now(self):
        """The clock the spawn queue's wait/expiry runs on. Decoupled default:
        real elapsed seconds. Unified: the single sim clock, in sim-seconds
        (scheduler.time is sim-hours), so grace and road service share units."""
        if self.unified:
            return self.scheduler.time * SEC_PER_HOUR
        return self.sim_real_time

    def _advance_physics(self, dt):
        """Advance vehicle motion by `dt` of real time.

        Decoupled default: one update, motion in real seconds (fixed speed).
        Unified: sim time advances time_scale*dt this tick; run the physics in
        ceil(time_scale) tick-sized sub-steps so each advance stays ~= a normal
        tick (never the 264 ft/tick that scaling dt directly would produce),
        keeping car-following and junction gating valid. Sub-step count scales
        with time_scale -- the compute cost of the single fast clock."""
        if not self.unified:
            self.traffic.update(dt)
            self.last_substeps = 1
            return
        dt_sim = self.time_scale * dt          # sim-seconds elapsed this tick
        n = max(1, math.ceil(self.time_scale))
        sub = dt_sim / n                       # ~= tick_dt, so ~= real motion/step
        for _ in range(n):
            self.traffic.update(sub)
        self.last_substeps = n

    # ------------------------------------------------------------------
    # State out (what a client renders; what the tests compare)
    # ------------------------------------------------------------------

    def snapshot(self):
        """Plain-data view of the dynamic simulation state at this tick.
        Everything a client needs to draw a frame (paired with the static
        map geometry it already holds); also the equality key the
        determinism guard compares between runs."""
        return {
            "tick": self.tick_count,
            "time": self.scheduler.time,
            "day": self.scheduler.day,
            "day_name": self.scheduler.day_name,
            "clock": self.scheduler.time_label,
            "vehicles": [
                {
                    "id": v.vid,
                    "pos": v.pos,
                    "heading": v.heading,
                    "speed": v.current_speed,
                    "state": v.state,
                    "dest_node": v.dest_node_id,
                    "dest_building": v.dest_building_id,
                }
                for v in self.traffic.vehicles
            ],
            "queue_depth": self.spawn_queue.depth,
            "released": self.scheduler.released,
            "expired": self.spawn_queue.expired,
            "dropped_no_path": self.spawn_queue.dropped_no_path,
            "occupancy": dict(self.building_occupancy),
        }
