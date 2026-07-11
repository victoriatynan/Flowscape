"""
Headless fixed-timestep session tests (WEB_MIGRATION_PLAN.md Phase 2 guard).

The acceptance criteria for the headless backend:
  1. NO PYGAME: building and running a SimulationSession never imports
     pygame (no window, no display, no SDL -- not even the dummy driver).
  2. DETERMINISM: two sessions over identical networks stay in lockstep,
     snapshot-for-snapshot, tick-for-tick.
  3. HARNESS EQUIVALENCE: the session's tick pipeline produces exactly the
     state that driving the same components directly with the same fixed dt
     produces (the editor's cull -> release -> expire -> drain -> advance
     order, which the existing headless tests exercise piecewise).
  4. BATCHING INSENSITIVE: run(a); run(b) == run(a+b) -- real-time pacing
     and broadcast cadence can never affect simulation results.

Plain asserts, runnable directly: python test_sim_session.py
(Deliberately no SDL_VIDEODRIVER needed.)
"""

import sys

from destinations import BUILDING_TYPES, RESIDENTIAL
from sim_clock import TripScheduler
from spawn_queue import SpawnQueue, SpawnResult
from sim_session import (SimulationSession, DEMO_TRIP_LIMIT, DEMO_START_HOUR,
                         DEMO_HOURS_PER_SEC, TRIPS_AT_ONCE_DEFAULT,
                         MAX_SIM_STEP_SEC)
from test_city import create_test_city, generate_trips
from traffic_sim import TrafficSimulation

TICKS = 1800   # 30 real seconds at 60 Hz = 3 sim hours from the 06:30 start


def test_headless_means_no_pygame():
    """The whole session stack must be importable and runnable without
    pygame ever being loaded."""
    session = SimulationSession(create_test_city())
    session.run(60)
    assert "pygame" not in sys.modules, \
        "pygame was imported somewhere in the headless session stack"
    print("ok: session builds and runs without pygame in sys.modules")


def test_fixed_tick_determinism():
    """Same network + same settings -> identical snapshots, forever."""
    a = SimulationSession(create_test_city())
    b = SimulationSession(create_test_city())
    seen_vehicles = 0
    for i in range(TICKS):
        a.tick()
        b.tick()
        if i % 120 == 0:
            sa, sb = a.snapshot(), b.snapshot()
            assert sa == sb, f"sessions diverged at tick {i}"
            seen_vehicles = max(seen_vehicles, len(sa["vehicles"]))
    final_a, final_b = a.snapshot(), b.snapshot()
    assert final_a == final_b
    # The run must actually exercise the pipeline, or this guard is vacuous.
    assert final_a["released"] > 0, "no trips released -- test window too short"
    assert seen_vehicles > 0, "no vehicles ever spawned -- nothing was compared"
    print(f"ok: two sessions in lockstep for {TICKS} ticks "
          f"(released={final_a['released']}, peak cars={seen_vehicles})")


def test_matches_direct_harness_wiring():
    """The session must equal hand-wiring the same components and stepping
    them with the same fixed dt in the editor's pipeline order. Guards the
    session's _step against drifting from the reference semantics."""
    session = SimulationSession(create_test_city())

    # Reference: the same spine, wired by hand (the editor's update_traffic
    # order), stepped with the session's own fixed dt.
    net = create_test_city()
    traffic = TrafficSimulation(net)
    traffic.prepare_routes()

    def day_trips(day_index):
        weekend = (day_index % 7) >= 5
        return generate_trips(net, day_index=day_index,
                              limit=DEMO_TRIP_LIMIT, weekend=weekend)

    scheduler = TripScheduler(day_trips, start_hour=DEMO_START_HOUR,
                              hours_per_second=DEMO_HOURS_PER_SEC)
    queue = SpawnQueue()
    occupancy = {}
    for bld in net.buildings.values():
        bt = BUILDING_TYPES.get(bld.building_type)
        occupancy[bld.id] = bt.capacity if (bt and bt.category == RESIDENTIAL) else 0

    dt = session.tick_dt
    real_time = 0.0   # mirrors SimulationSession.sim_real_time (real seconds)
    for i in range(TICKS):
        session.tick()
        real_time += dt   # advance first, matching _step's order

        for v in traffic.cull_arrived():
            bid = v.dest_building_id
            building = net.buildings.get(bid) if bid is not None else None
            if building is not None:
                bt = BUILDING_TYPES.get(building.building_type)
                cap = bt.capacity if bt else occupancy.get(bid, 0) + 1
                occupancy[bid] = min(cap, occupancy.get(bid, 0) + 1)

        def release(trip):
            path = traffic.resolve_route(trip.origin_node_id, trip.dest_node_id)
            if path is None:
                queue.dropped_no_path += 1
                return
            queue.enqueue(trip, path, real_time)
        scheduler.update(dt, release)

        queue.expire(real_time)

        free_slots = max(0, TRIPS_AT_ONCE_DEFAULT - len(traffic.vehicles))

        def do_spawn(trip, path):
            if not traffic.route_valid(path):
                return SpawnResult.INVALID
            v = traffic.spawn_on_route(path, dest_node_id=trip.dest_node_id,
                                       dest_building_id=trip.dest_building_id)
            return SpawnResult.SPAWNED if v is not None else SpawnResult.BLOCKED

        for trip in queue.drain(dt, free_slots, do_spawn):
            if trip.origin_building_id is not None:
                occupancy[trip.origin_building_id] = max(
                    0, occupancy.get(trip.origin_building_id, 0) - 1)

        traffic.update(dt)

    snap = session.snapshot()
    assert snap["time"] == scheduler.time
    assert snap["released"] == scheduler.released
    assert snap["queue_depth"] == queue.depth
    assert snap["expired"] == queue.expired
    assert snap["dropped_no_path"] == queue.dropped_no_path
    assert snap["occupancy"] == occupancy
    ref_vehicles = [{"id": v.vid, "pos": v.pos, "heading": v.heading,
                     "speed": v.current_speed,
                     "state": v.state, "dest_node": v.dest_node_id,
                     "dest_building": v.dest_building_id}
                    for v in traffic.vehicles]
    assert snap["vehicles"] == ref_vehicles
    assert snap["released"] > 0
    print(f"ok: session matches the hand-wired fixed-dt harness for {TICKS} ticks")


def test_batching_cannot_change_results():
    """run(a); run(b) must equal run(a+b): pacing/broadcast cadence can
    never influence simulation state."""
    a = SimulationSession(create_test_city())
    b = SimulationSession(create_test_city())
    a.run(300)
    a.run(500)
    a.run(1)
    b.run(801)
    assert a.snapshot() == b.snapshot()
    print("ok: tick batching is invisible to simulation state")


def test_tick_rate_is_validated():
    """A tick slower than the step clamp would batch trip releases -- the
    session must refuse it rather than silently behave differently."""
    try:
        SimulationSession(create_test_city(), tick_rate=5)   # dt 0.2 > 0.1 clamp
    except ValueError as e:
        assert str(MAX_SIM_STEP_SEC) in str(e)
        print("ok: too-slow tick rate is rejected up front")
        return
    raise AssertionError("tick_rate below the step clamp was accepted")


def test_empty_network_is_rejected():
    from road_network import RoadNetwork
    try:
        SimulationSession(RoadNetwork())
    except ValueError:
        print("ok: a network with no buildings is rejected up front")
        return
    raise AssertionError("building-less network was accepted")


if __name__ == "__main__":
    test_headless_means_no_pygame()   # MUST run first (checks sys.modules)
    test_fixed_tick_determinism()
    test_matches_direct_harness_wiring()
    test_batching_cannot_change_results()
    test_tick_rate_is_validated()
    test_empty_network_is_rejected()
    print("\nsim-session: all tests passed")
