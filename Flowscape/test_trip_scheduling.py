"""
Trip scheduling tests (Phase 2a: arrival-based departures + the Vehicle Spawn
Queue).

Two halves:
  1. Demand side -- departures are back-computed from a desired ARRIVAL window
     minus a lightweight Euclidean travel-time estimate plus a small jitter, so
     distant trips leave earlier. Generation stays deterministic.
  2. Spawn-queue side -- released trips wait and drain under a concurrency cap
     and a token-bucket rate. A blocked origin is retried (not dropped), an
     invalid route is dropped, expiry bounds the backlog and never credits
     occupancy, and the cap/rate/FIFO budget is respected.

Plus a small end-to-end check that route-resolve-once + spawn-from-path works on
the real simulation and that the clearance gate surfaces as a retryable block.
"""

import math

import destinations as d
from destinations import generate_trips, _estimate_travel_hours
from spawn_queue import SpawnQueue, SpawnResult
from traffic_sim import TrafficSimulation
from test_city import create_test_city


# ----------------------------------------------------------------------
# Demand side: departure = desired_arrival - est_travel + jitter
# ----------------------------------------------------------------------
class _Pt:
    """Minimal stand-in for a Building (just needs x/y) for travel estimates."""
    def __init__(self, x, y):
        self.x = x
        self.y = y


def test_travel_estimate_monotonic_and_floored():
    near = _estimate_travel_hours(_Pt(0, 0), _Pt(10, 0))
    far = _estimate_travel_hours(_Pt(0, 0), _Pt(100000, 0))
    assert far > near, "farther destination must estimate a longer travel time"
    # Very close trips are floored so they still spread a little.
    assert near == d.MIN_TRAVEL_SIM_HR
    # The estimate is distance / average speed.
    expect = 100000.0 / d.AVG_SPEED_FT_PER_HR
    assert math.isclose(far, expect, rel_tol=1e-9)
    print("ok: travel estimate grows with distance and respects the floor")


def test_departures_are_back_computed_from_arrival():
    net = create_test_city()
    trips = generate_trips(net, day_index=0)
    assert trips
    for t in trips:
        # Fields are populated for scheduling/debug.
        assert t.activity != ""
        assert 0.0 <= t.desired_arrival <= 24.0
        assert t.est_travel >= d.MIN_TRAVEL_SIM_HR
        # departure = arrival - travel + offset, clamped to >= 0.
        assert 0.0 <= t.depart_hour <= t.desired_arrival + d.DEPART_OFFSET_SIM_HR + 1e-9
        # Within the jitter band of the ideal back-computed time.
        ideal = t.desired_arrival - t.est_travel
        assert abs(t.depart_hour - ideal) <= d.DEPART_OFFSET_SIM_HR + 1e-9 or t.depart_hour == 0.0
    # Still sorted by departure (the scheduler relies on this).
    assert all(trips[i].depart_hour <= trips[i + 1].depart_hour
               for i in range(len(trips) - 1))
    print("ok: departures back-computed from arrival, clamped, and sorted")


def test_generation_still_deterministic():
    net = create_test_city()
    a = generate_trips(net, day_index=0)
    b = generate_trips(net, day_index=0)
    key = lambda L: [(t.origin_node_id, t.dest_node_id, round(t.depart_hour, 6),
                      round(t.desired_arrival, 6), round(t.est_travel, 6))
                     for t in L]
    assert key(a) == key(b)
    print("ok: arrival-based generation is still deterministic")


# ----------------------------------------------------------------------
# Spawn queue
# ----------------------------------------------------------------------
def _trip(name):
    return name   # opaque to the queue; just an identity


def _spawner(blocked=(), invalid=()):
    """A drain callback that reports each trip's outcome by name."""
    def spawn(trip, path):
        if trip in invalid:
            return SpawnResult.INVALID
        if trip in blocked:
            return SpawnResult.BLOCKED
        return SpawnResult.SPAWNED
    return spawn


def test_drain_respects_capacity():
    q = SpawnQueue(rate_per_sec=1000, token_cap=1000, max_wait_hours=10)
    for i in range(5):
        q.enqueue(_trip(i), path=[i], now=0.0)
    spawned = q.drain(dt_seconds=1.0, free_slots=2, spawn=_spawner())
    assert spawned == [0, 1]          # only 2 slots free
    assert q.depth == 3               # rest wait, in order
    print("ok: drain never exceeds the concurrency cap")


def test_drain_respects_rate():
    q = SpawnQueue(rate_per_sec=1.0, token_cap=1.0, max_wait_hours=10)
    for i in range(5):
        q.enqueue(_trip(i), path=[i], now=0.0)
    # Half a token: nothing visible yet.
    assert q.drain(dt_seconds=0.5, free_slots=100, spawn=_spawner()) == []
    assert q.depth == 5
    # Accumulates to a full token -> exactly one becomes visible.
    assert q.drain(dt_seconds=0.5, free_slots=100, spawn=_spawner()) == [0]
    assert q.depth == 4
    print("ok: drain meters departures by the token-bucket rate")


def test_blocked_is_retried_not_dropped():
    q = SpawnQueue(rate_per_sec=1000, token_cap=1000, max_wait_hours=10)
    for n in ("a", "b", "c"):
        q.enqueue(_trip(n), path=[n], now=0.0)
    spawned = q.drain(dt_seconds=1.0, free_slots=100, spawn=_spawner(blocked={"b"}))
    assert spawned == ["a", "c"]      # no head-of-line blocking
    assert q.depth == 1               # "b" stays pending
    # Next frame, once unblocked, it spawns.
    assert q.drain(dt_seconds=1.0, free_slots=100, spawn=_spawner()) == ["b"]
    assert q.depth == 0
    print("ok: a blocked origin is retried, not dropped or head-of-line-blocking")


def test_invalid_is_dropped():
    q = SpawnQueue(rate_per_sec=1000, token_cap=1000, max_wait_hours=10)
    for n in ("a", "b"):
        q.enqueue(_trip(n), path=[n], now=0.0)
    spawned = q.drain(dt_seconds=1.0, free_slots=100, spawn=_spawner(invalid={"a"}))
    assert spawned == ["b"]
    assert q.depth == 0               # "a" dropped, not retained
    print("ok: an invalid (vanished) route is dropped")


def test_expire_bounds_backlog_without_crediting():
    q = SpawnQueue(rate_per_sec=1000, token_cap=1000, max_wait_hours=1.0)
    for i in range(3):
        q.enqueue(_trip(i), path=[i], now=0.0)
    assert q.expire(now=0.5) == []    # still within the wait window
    expired = q.expire(now=2.0)       # all waited > 1.0h
    assert set(expired) == {0, 1, 2}
    assert q.depth == 0
    assert q.expired == 3             # tallied; occupancy is the caller's concern
    print("ok: expiry bounds the backlog (and is occupancy-neutral here)")


def test_fifo_order_preserved_across_frames():
    q = SpawnQueue(rate_per_sec=1000, token_cap=1000, max_wait_hours=10)
    for i in range(3):
        q.enqueue(_trip(i), path=[i], now=0.0)
    assert q.drain(1.0, free_slots=1, spawn=_spawner()) == [0]
    assert q.drain(1.0, free_slots=1, spawn=_spawner()) == [1]
    assert q.drain(1.0, free_slots=1, spawn=_spawner()) == [2]
    print("ok: pending trips drain in FIFO order across frames")


# ----------------------------------------------------------------------
# End-to-end: resolve once, spawn from the path, clearance surfaces as a block
# ----------------------------------------------------------------------
def test_resolve_once_then_spawn_and_clearance_block():
    sim = TrafficSimulation(create_test_city())
    sim.prepare_routes()
    t = generate_trips(sim.network, day_index=0)[0]

    path = sim.resolve_route(t.origin_node_id, t.dest_node_id)
    assert path is not None and sim.route_valid(path)

    v1 = sim.spawn_on_route(path, dest_node_id=t.dest_node_id,
                            dest_building_id=t.dest_building_id)
    assert v1 is not None
    assert v1.dest_building_id == t.dest_building_id
    # A second car on the SAME just-used start is blocked by the clearance gate
    # -> None, which the queue treats as a retry (not a drop).
    v2 = sim.spawn_on_route(path, dest_node_id=t.dest_node_id)
    assert v2 is None
    print("ok: route resolved once, spawned from path; clearance surfaces as a block")


def test_unreachable_route_resolves_to_none():
    from road_editor import RoadNetwork
    net = RoadNetwork()
    a = net.add_node(0, 0)
    b = net.add_node(100, 0)
    net.add_road(a.id, b.id)
    c = net.add_node(0, 500)
    e = net.add_node(100, 500)
    net.add_road(c.id, e.id)           # a separate, disconnected segment
    sim = TrafficSimulation(net)
    sim.prepare_routes()
    assert sim.resolve_route(a.id, e.id) is None   # no path across the gap
    print("ok: an unreachable pair resolves to None (dropped at release)")


if __name__ == "__main__":
    test_travel_estimate_monotonic_and_floored()
    test_departures_are_back_computed_from_arrival()
    test_generation_still_deterministic()
    test_drain_respects_capacity()
    test_drain_respects_rate()
    test_blocked_is_retried_not_dropped()
    test_invalid_is_dropped()
    test_expire_bounds_backlog_without_crediting()
    test_fifo_order_preserved_across_frames()
    test_resolve_once_then_spawn_and_clearance_block()
    test_unreachable_route_resolves_to_none()
    print("\ntrip-scheduling: all tests passed")
