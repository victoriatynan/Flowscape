"""
Spawn-clearance gate test (SPAWNER concern, not decision/dynamics).

Vehicles accelerate from rest, so a car that just departed is still sitting
near its lane's start point a second later. Without a gate, a second trip
released from the same origin lands on top of it (overlap < VEHICLE_LENGTH).
TrafficSimulation only places a car when the departing lane's start is clear by
SPAWN_CLEARANCE_FT; otherwise the trip is dropped (spawn returns None).

These tests assert (1) two same-origin trips released a moment apart never end
up closer than a vehicle length on a shared lane, and (2) once the leader has
cleared the start region, the next trip is allowed through again.
"""

import math

from test_city import create_test_city
from traffic_sim import (TrafficSimulation, VEHICLE_LENGTH_FT,
                         SPAWN_CLEARANCE_FT)


def _make_sim():
    sim = TrafficSimulation(create_test_city())
    sim.prepare_routes()
    return sim


def _find_trip_pair(sim):
    """Pick an (origin, dest) with a lane path, so spawn_trip succeeds on a
    clear network. Deterministic: lowest origin id, lowest reachable dest."""
    ids = sorted(sim.network.nodes)
    for origin in ids:
        for dest in ids:
            if dest == origin:
                continue
            if sim.spawn_trip(origin, dest) is not None:
                sim.reset()
                sim.prepare_routes()
                return origin, dest
    raise AssertionError("no routable node pair in the test city")


def _min_same_lane_distance(sim):
    """Smallest Euclidean gap between any two vehicles sharing a current lane."""
    worst = math.inf
    cars = sim.vehicles
    for i in range(len(cars)):
        for j in range(i + 1, len(cars)):
            if cars[i].current_lane != cars[j].current_lane:
                continue
            d = math.hypot(cars[i].pos[0] - cars[j].pos[0],
                           cars[i].pos[1] - cars[j].pos[1])
            worst = min(worst, d)
    return worst


def test_back_to_back_spawn_is_gated():
    """Releasing a second trip from the same origin ~1.25 s after the first --
    while the first car has crept only a few feet from rest -- must NOT stack a
    car on top of it. The repro from the bug report."""
    sim = _make_sim()
    origin, dest = _find_trip_pair(sim)

    first = sim.spawn_trip(origin, dest)
    assert first is not None

    # Let the leader accelerate from rest for ~1.25 s; it covers only ~6 ft.
    for _ in range(75):
        sim.update(1.0 / 60.0)

    crept = math.hypot(first.pos[0] - first.segments[0]["points"][0][0],
                       first.pos[1] - first.segments[0]["points"][0][1])
    assert crept < SPAWN_CLEARANCE_FT, (
        f"leader moved {crept:.1f} ft -- too far to exercise the gate")

    # The gate must refuse the second trip: the start is still occupied.
    second = sim.spawn_trip(origin, dest)
    assert second is None, "second trip should have been gated, not placed"

    assert _min_same_lane_distance(sim) >= VEHICLE_LENGTH_FT


def test_spawn_never_places_a_car_on_top_of_another():
    """Hammer the same origin every few frames while traffic flows. Each car
    the gate actually places must be clear of every existing car -- so a fresh
    spawn never lands on a same-lane leader closer than a vehicle length. (This
    is the spawner's contract; in-traffic spacing belongs to the decision
    layer's car-following rule and is checked elsewhere.)"""
    sim = _make_sim()
    origin, dest = _find_trip_pair(sim)

    placed = 0
    for step in range(600):
        if step % 20 == 0:
            before = list(sim.vehicles)
            car = sim.spawn_trip(origin, dest)
            if car is not None:
                placed += 1
                nearest = min((math.hypot(car.pos[0] - o.pos[0],
                                          car.pos[1] - o.pos[1])
                               for o in before), default=math.inf)
                assert nearest >= SPAWN_CLEARANCE_FT, (
                    f"spawn at step {step} placed a car {nearest:.1f} ft from "
                    f"another (< {SPAWN_CLEARANCE_FT} ft clearance)")
                assert _min_same_lane_distance(sim) >= VEHICLE_LENGTH_FT
        sim.update(1.0 / 60.0)

    assert placed > 1, "test never exercised a successful gated spawn"


def test_gate_reopens_once_leader_clears():
    """The gate is not a permanent block: once the leader has driven well past
    SPAWN_CLEARANCE_FT from the start, a fresh trip is allowed through."""
    sim = _make_sim()
    origin, dest = _find_trip_pair(sim)

    first = sim.spawn_trip(origin, dest)
    assert first is not None

    # Drive until the leader has left the start region with margin to spare.
    start = first.segments[0]["points"][0]
    for _ in range(600):
        sim.update(1.0 / 60.0)
        if math.hypot(first.pos[0] - start[0],
                      first.pos[1] - start[1]) > SPAWN_CLEARANCE_FT + VEHICLE_LENGTH_FT:
            break

    second = sim.spawn_trip(origin, dest)
    assert second is not None, "gate should reopen once the start is clear"
    assert _min_same_lane_distance(sim) >= VEHICLE_LENGTH_FT


if __name__ == "__main__":
    test_back_to_back_spawn_is_gated()
    test_spawn_never_places_a_car_on_top_of_another()
    test_gate_reopens_once_leader_clears()
    print("spawn-clearance gate: all tests passed")
