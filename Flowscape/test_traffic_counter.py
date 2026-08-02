"""
Tests for the simulation-derived traffic volume counter (traffic_counter.py).

Unit tests drive the counter with lightweight fake vehicles so the traversal
logging, rolling-window pruning, and veh/hr conversion are exercised in
isolation; an integration test then confirms a real SimulationSession surfaces
per-road volumes through its snapshot.
"""

from traffic_counter import TrafficCounter


class FakeVehicle:
    """Minimal stand-in: the counter only reads `.vid` and `.current_lane`,
    whose [0] is the road id."""
    def __init__(self, vid, road_id, direction="F", lane=0):
        self.vid = vid
        self.current_lane = (road_id, direction, lane)


def test_logs_first_sighting_of_each_vehicle():
    c = TrafficCounter(window_hours=1.0)
    c.record([FakeVehicle(1, road_id=10), FakeVehicle(2, road_id=10)], now=0.0)
    assert c.counts(0.0) == {10: 2}


def test_logs_only_on_road_change_not_every_tick():
    c = TrafficCounter(window_hours=1.0)
    v = FakeVehicle(1, road_id=10)
    for t in (0.0, 0.01, 0.02):          # same road three ticks running
        c.record([v], now=t)
    assert c.counts(0.02) == {10: 1}     # one entry, not three

    v.current_lane = (20, "F", 0)        # moved onto road 20
    c.record([v], now=0.03)
    assert c.counts(0.03) == {10: 1, 20: 1}


def test_direction_does_not_split_a_road():
    c = TrafficCounter(window_hours=1.0)
    # Two vehicles on the same road, opposite directions -> both count to road 10.
    c.record([FakeVehicle(1, 10, "F"), FakeVehicle(2, 10, "R")], now=0.0)
    assert c.counts(0.0) == {10: 2}


def test_window_prunes_old_entries():
    c = TrafficCounter(window_hours=1.0)
    c.record([FakeVehicle(1, 10)], now=0.0)          # at t=0
    c.record([FakeVehicle(2, 10)], now=0.5)          # at t=0.5
    # At t=1.2 the window is (0.2, 1.2]: the t=0 entry has aged out, t=0.5 survives.
    assert c.counts(1.2) == {10: 1}


def test_volume_per_hour_is_count_over_window():
    c = TrafficCounter(window_hours=0.5)             # half-hour window
    for vid in range(1, 5):                          # 4 distinct vehicles, road 10
        c.record([FakeVehicle(vid, 10)], now=0.1)
    # 4 traversals in a 0.5h window -> 8 veh/hr.
    assert c.volume_per_hour(0.1) == {10: 8.0}


def test_forgets_departed_vehicles():
    c = TrafficCounter(window_hours=1.0)
    c.record([FakeVehicle(1, 10), FakeVehicle(2, 10)], now=0.0)
    c.record([FakeVehicle(1, 10)], now=0.1)          # vehicle 2 gone (arrived)
    assert 2 not in c._last_road
    assert 1 in c._last_road


# --- integration: a real session surfaces per-road volume -------------------

def test_session_snapshot_exposes_road_volumes():
    from test_city import create_test_city
    from sim_session import SimulationSession

    session = SimulationSession(create_test_city(), volume_window_hours=1.0)
    session.run(2000)
    volumes = session.snapshot()["road_volumes"]

    assert isinstance(volumes, dict)
    valid_road_ids = set(session.network.roads)
    assert volumes                                    # some traffic moved
    for road_id, vph in volumes.items():
        assert road_id in valid_road_ids
        assert vph > 0


def test_session_volume_is_deterministic():
    from test_city import create_test_city
    from sim_session import SimulationSession

    a = SimulationSession(create_test_city())
    b = SimulationSession(create_test_city())
    a.run(1500)
    b.run(1500)
    assert a.snapshot()["road_volumes"] == b.snapshot()["road_volumes"]
