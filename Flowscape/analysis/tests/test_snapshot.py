"""
Snapshot tests: immutability, unit normalization, and static-vs-runtime parity.
"""

import dataclasses

import pytest

from road_network import RoadNetwork
from test_city import create_test_city
from sim_session import SimulationSession

from analysis.snapshot import (StaticSource, RuntimeSource, build_snapshot,
                               Snapshot)
from analysis.snapshot.builder import FT_PER_S_TO_MPH, _vehicle_snapshot


def _line_network(length_ft=100.0):
    """Two nodes a known distance apart, joined by one straight road."""
    net = RoadNetwork()
    a = net.add_node(0.0, 0.0)
    b = net.add_node(length_ft, 0.0)
    net.add_road(a.id, b.id)
    return net, a, b


# --- immutability -----------------------------------------------------------

def test_snapshot_is_frozen():
    snap = build_snapshot(StaticSource(_line_network()[0]))
    assert isinstance(snap, Snapshot)
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.roads = ()
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.roads[0].length_ft = 5.0


def test_snapshot_is_hashable():
    snap = build_snapshot(StaticSource(_line_network()[0]))
    assert isinstance(hash(snap), int)


# --- unit normalization -----------------------------------------------------

def test_straight_road_length_is_true_feet():
    net, _, _ = _line_network(length_ft=140.0)
    snap = build_snapshot(StaticSource(net))
    assert len(snap.roads) == 1
    assert snap.roads[0].length_ft == pytest.approx(140.0, abs=1e-6)


def test_speed_normalized_ft_per_s_to_mph():
    # 10 ft/s ~= 6.818 mph.
    vs = _vehicle_snapshot({"id": 1, "speed": 10.0, "pos": (0.0, 0.0)})
    assert vs.speed_mph == pytest.approx(10.0 * FT_PER_S_TO_MPH)
    assert vs.speed_mph == pytest.approx(6.8181818, abs=1e-5)


# --- static source ----------------------------------------------------------

def test_static_snapshot_has_topology_no_vehicles():
    net = create_test_city()
    snap = build_snapshot(StaticSource(net))
    assert snap.meta.source_kind == "static"
    assert snap.meta.is_running is False
    assert len(snap.roads) > 0 and len(snap.buildings) > 0
    assert snap.vehicles == ()
    assert snap.meta.sim_time_hours is None


# --- runtime source & parity ------------------------------------------------

def test_runtime_snapshot_matches_static_topology():
    net = create_test_city()
    static = build_snapshot(StaticSource(net))

    session = SimulationSession(net)
    session.run(300)                       # advance a few seconds of sim
    runtime = build_snapshot(RuntimeSource(session))

    assert runtime.meta.source_kind == "runtime"
    assert runtime.meta.is_running is True
    assert isinstance(runtime.meta.sim_time_hours, float)
    # Topology is the same network, so counts match exactly.
    assert len(runtime.roads) == len(static.roads)
    assert len(runtime.nodes) == len(static.nodes)
    assert len(runtime.buildings) == len(static.buildings)
    # Vehicles are a tuple of VehicleSnapshot with normalized mph.
    assert isinstance(runtime.vehicles, tuple)
    for v in runtime.vehicles:
        assert v.speed_mph >= 0.0
