"""
Lane-change tests.

A held-up car (slowed by a close leader) should merge into an adjacent
same-direction lane that has fewer cars ahead AND can still reach its
destination -- gliding across smoothly, never teleporting, and re-routing so the
remaining path still ends at the same node. These tests drive the real
TrafficSimulation on the 2+2 arterial test map, plus a few pure-policy/geometry
unit checks.
"""

import math

from traffic_sim import (TrafficSimulation, create_lane_test_map, STATE_BLOCKED,
                         lane_polyline, lane_arrival_node, _point_at_arc,
                         _polyline_length)
from vehicle_perception import compute_perception
from vehicle_decision import compute_decisions, DecisionContext
from vehicle_lane_change import (adjacent_lane_ids, cars_ahead, _held_up,
                                 choose_lane_change, build_merge_polyline,
                                 MERGE_LEN_FT)

DT = 0.05


def _arterial_sim():
    """Sim on the 2+2 arterial; routes prepared. n1->n4 runs along the
    multi-lane arterial (n1->n2->n3->n4)."""
    net = create_lane_test_map()
    sim = TrafficSimulation(net)
    sim.prepare_routes()
    # Dead-end nodes by construction: n1=id1 ... n4=id4 (add order in the map).
    ids = sorted(net.nodes.keys())
    return net, sim, ids


def _spawn(sim, start_id, dest_id):
    v, _msg = sim.spawn_vehicle(start_id, dest_id)
    assert v is not None, f"spawn {start_id}->{dest_id} failed: {_msg}"
    return v


def _park(vehicle, arc):
    """Freeze `vehicle` as a stopped obstacle `arc` feet along its first lane."""
    vehicle.cruise_speed = 0.0
    vehicle.desired_speed = 0.0
    vehicle.current_speed = 0.0
    vehicle.seg_s = arc
    seg = vehicle.segments[0]
    vehicle.pos = _point_at_arc(seg["points"], arc)
    vehicle.position_along_lane = arc / seg["length"]


def _partial_step(sim):
    """A full driver-model step EXCEPT the lane-change pass, so a test can reach
    a held-up state and then inspect the lane-change policy directly (without it
    having already fired)."""
    sim.intersections.begin_step(sim.vehicles, DT)
    for v in sim.vehicles:
        v.move(DT, sim._valid_edges, sim.intersections)
    compute_perception(sim.vehicles)
    compute_decisions(sim.vehicles, DecisionContext(sim.intersections))
    for v in sim.vehicles:
        v.integrate_dynamics(DT)


def test_held_up_car_merges_to_emptier_lane():
    net, sim, ids = _arterial_sim()
    n1, n4 = ids[0], ids[3]

    leader = _spawn(sim, n1, n4)
    _park(leader, 120.0)                       # stopped obstacle in lane 0
    follower = _spawn(sim, n1, n4)
    start_lane = follower.current_lane
    assert start_lane[2] == 0, start_lane      # both spawn on inner lane 0

    changed_to = None
    max_jump = 0.0
    for _ in range(2000):
        prev = follower.pos
        sim.update(DT)
        jump = math.hypot(follower.pos[0] - prev[0], follower.pos[1] - prev[1])
        max_jump = max(max_jump, jump)
        if follower.current_lane[2] != start_lane[2] and changed_to is None:
            changed_to = follower.current_lane
        if follower.state != "moving":
            break

    assert changed_to is not None, "held-up follower never changed lanes"
    assert changed_to[:2] == start_lane[:2][:1] + (start_lane[1],)  # same road+dir
    assert changed_to[2] == 1, f"expected merge to lane 1, got {changed_to}"
    assert follower.state != STATE_BLOCKED, "follower got blocked after merging"

    # No teleport: the largest single-frame move stays within a couple of
    # frames' worth of forward travel (no lateral jump across the lane gap).
    assert max_jump < 2.0 * follower.cruise_speed * DT, f"jumpy: {max_jump:.1f} ft"

    # Route validity: the recomputed path still ends at the destination node.
    assert lane_arrival_node(net, follower.path[-1]) == n4
    print("ok: held-up car merges to the emptier lane, smoothly, route intact")


def test_no_change_without_a_leader():
    net, sim, ids = _arterial_sim()
    n1, n4 = ids[0], ids[3]
    solo = _spawn(sim, n1, n4)
    start_lane = solo.current_lane
    for _ in range(400):
        sim.update(DT)
        if solo.state != "moving":
            break
        # While on the first (multi-lane) road it must never lane-shop with a
        # clear road ahead.
        if solo.current_lane[0] == start_lane[0]:
            assert solo.current_lane[2] == start_lane[2], "changed with no leader"
    print("ok: a free-flowing car with no leader never changes lanes")


def test_unreachable_adjacent_lane_is_skipped():
    """Reachability gate: even when held up with an emptier neighbour, no change
    if the neighbour can't reach the destination."""
    net, sim, ids = _arterial_sim()
    n1, n4 = ids[0], ids[3]
    leader = _spawn(sim, n1, n4)
    _park(leader, 120.0)
    follower = _spawn(sim, n1, n4)

    for _ in range(2000):
        _partial_step(sim)                     # no lane-change pass yet
        if _held_up(follower):
            break
    assert _held_up(follower), "test setup never reached a held-up state"

    goal_lanes = set()  # not used by the stub
    # Real router -> a target exists; stub router (always None) -> skipped.
    real = choose_lane_change(follower, net, sim._edges,
                              __import__("traffic_sim").lanes_arriving_node(net, n4),
                              sim.vehicles, __import__("traffic_sim").find_lane_path)
    assert real is not None and real[2] == 1, real
    none_router = choose_lane_change(follower, net, sim._edges, goal_lanes,
                                     sim.vehicles, lambda e, s, g: None)
    assert none_router is None, "unreachable neighbour must be skipped"
    print("ok: an unreachable adjacent lane is never chosen")


def test_adjacency_and_counting_helpers():
    net, sim, ids = _arterial_sim()
    n1, n4 = ids[0], ids[3]
    v = _spawn(sim, n1, n4)
    lane0 = v.current_lane
    adj = adjacent_lane_ids(net, lane0)
    assert adj == [(lane0[0], lane0[1], 1)], adj        # only lane 1 (no -1)
    # An inner lane on a single-lane road has no neighbours.
    assert adjacent_lane_ids(net, (lane0[0], lane0[1], 5)) == []
    # cars_ahead counts only same-lane vehicles ahead of the ref arc.
    _park(v, 100.0)
    assert cars_ahead(sim.vehicles, lane0, 50.0) == 1
    assert cars_ahead(sim.vehicles, lane0, 150.0) == 0
    print("ok: adjacency + car-counting helpers behave")


def test_merge_polyline_is_smooth_and_lands_on_new_lane():
    cur = [(0.0, 0.0), (100.0, 0.0)]
    new = [(0.0, 10.0), (100.0, 10.0)]         # parallel lane, 10 ft over
    out = build_merge_polyline(cur, new, start_arc=0.0, merge_len=20.0, step=2.0)

    assert math.hypot(out[0][0], out[0][1]) < 1e-6        # starts on current lane
    assert out[-1] == (100.0, 10.0)                       # ends on new lane end
    ys = [p[1] for p in out]
    assert all(b >= a - 1e-9 for a, b in zip(ys, ys[1:])), "lateral move reversed"
    assert ys[-1] == 10.0 and max(ys) <= 10.0 + 1e-6
    # No single-step jump bigger than ~the sampling step (no teleport).
    steps = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(out, out[1:])]
    assert max(steps) < 4.0, f"merge has a jump: {max(steps):.2f}"
    # Crossing is essentially complete by the end of the merge window.
    crossed = next(p for p in out if p[0] >= 20.0)
    assert crossed[1] > 9.0, f"not merged by merge_len: {crossed}"
    print("ok: merge polyline is smooth and lands on the new lane")


if __name__ == "__main__":
    test_held_up_car_merges_to_emptier_lane()
    test_no_change_without_a_leader()
    test_unreachable_adjacent_lane_is_skipped()
    test_adjacency_and_counting_helpers()
    test_merge_polyline_is_smooth_and_lands_on_new_lane()
    print("\nlane-change: all tests passed")
