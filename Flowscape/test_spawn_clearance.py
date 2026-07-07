"""
Spawn-clearance gate test (SPAWNER concern, not decision/dynamics).

Vehicles accelerate from rest, so a car that just departed is still near its
lane's start a second later. Placing another on top of it would overlap
(< VEHICLE_LENGTH). The spawner instead fills the departing lane nose-to-tail:
each new car takes the first slot (stepping back by SPAWN_CLEARANCE_FT) that is
clear of other cars -- a staggered SPAWN ZONE that lets one entrance/driveway
emit a burst without overlap. When the whole departing lane is occupied, the
spawn is refused (returns None).

These tests assert the safety invariant is preserved -- no two spawned cars end
up closer than a vehicle length on a shared lane -- while the zone staggers
back-to-back releases instead of blocking them, and still hard-gates a full lane.
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


def test_back_to_back_spawns_stagger_without_overlap():
    """Releasing a second trip from the same origin while the first is still near
    the start no longer STACKS a car on it -- with the spawn zone the second
    takes the next clear slot further along the departing lane. Both are placed,
    and (the safety invariant the gate protects) they stay at least a vehicle
    length apart. This is the repro from the original bug report, now handled by
    staggering instead of dropping."""
    sim = _make_sim()
    origin, dest = _find_trip_pair(sim)

    first = sim.spawn_trip(origin, dest)
    assert first is not None

    # Let the leader accelerate from rest for ~1.25 s; it covers only ~6 ft.
    for _ in range(75):
        sim.update(1.0 / 60.0)

    second = sim.spawn_trip(origin, dest)
    assert second is not None and second is not first, (
        "the second trip should stagger into the next clear slot, not be dropped")
    assert _min_same_lane_distance(sim) >= VEHICLE_LENGTH_FT, "and never overlap"


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


def test_departing_lane_gates_when_full():
    """The zone is still a hard gate: fill the departing lane nose-to-tail and a
    further spawn is refused (None) rather than overlapping; a slot reopens once
    the cars advance and the queue shifts forward."""
    sim = _make_sim()
    origin, dest = _find_trip_pair(sim)

    # Fill the departing lane without advancing anyone.
    placed = 0
    while sim.spawn_trip(origin, dest) is not None:
        placed += 1
        assert placed < 100, "lane never fills -- the gate isn't limiting spawns"
    assert placed >= 2, "the zone fits several cars nose-to-tail before it's full"
    assert _min_same_lane_distance(sim) >= VEHICLE_LENGTH_FT, "no overlap when full"
    assert sim.spawn_trip(origin, dest) is None, "a full departing lane gates spawns"

    # A slot reopens when a car leaves the lane: drop one and a spawn succeeds.
    sim.vehicles.pop()
    assert sim.spawn_trip(origin, dest) is not None, "a freed slot admits a new car"
    assert _min_same_lane_distance(sim) >= VEHICLE_LENGTH_FT


if __name__ == "__main__":
    test_back_to_back_spawns_stagger_without_overlap()
    test_spawn_never_places_a_car_on_top_of_another()
    test_departing_lane_gates_when_full()
    print("spawn-clearance / zone: all tests passed")
