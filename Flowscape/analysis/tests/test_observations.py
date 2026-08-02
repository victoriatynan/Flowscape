"""
Observation tests: each of the seven M1 observations returns exact, deterministic
values, cross-checked against the network computed directly.
"""

import pytest

from road_network import RoadNetwork
from road_style import get_road_profile
from routing import _polyline_length
from test_city import create_test_city

from analysis import analyze
from analysis.snapshot import StaticSource, build_snapshot
from analysis.observations import default_observation_registry
from analysis.engine.pipeline import Pipeline


def _values(result):
    return {oid: r.value for oid, r in result.observations.items()}


def test_default_observations_present():
    result = analyze(StaticSource(create_test_city()))
    assert set(result.observations) == {
        "road_count", "intersection_count", "total_road_length",
        "building_count", "vehicle_count", "average_speed",
        "connected_components",
        "traffic_volume",          # M2: simulation-derived per-road volume
        "horizontal_curvature",    # M3: plan-view curve radius + deflection
        "block_length",            # M3: intersection spacing (block length)
        "building_mix",            # M4: convergence-track building population mix
    }


def test_counts_match_network_directly():
    net = create_test_city()
    result = analyze(StaticSource(net))
    vals = _values(result)

    non_preview = [r for r in net.roads.values() if not r.is_preview]
    expected_length = sum(
        _polyline_length(net.geometry_for_road(r)["sampled_points"])
        for r in non_preview)
    expected_intersections = sum(1 for nid in net.nodes
                                 if net.is_intersection(nid))

    assert vals["road_count"] == len(non_preview)
    assert vals["intersection_count"] == expected_intersections
    assert vals["total_road_length"] == pytest.approx(expected_length, abs=1e-6)
    assert vals["building_count"] == len(net.buildings)


def test_building_count_detail_by_type():
    net = create_test_city()
    result = analyze(StaticSource(net))
    by_type = result.observations["building_count"].detail["by_type"]
    assert sum(by_type.values()) == len(net.buildings)


def test_static_has_no_vehicles_and_undefined_speed():
    result = analyze(StaticSource(create_test_city()))
    assert result.observations["vehicle_count"].value == 0
    # Empty-safe: undefined average, never a misleading 0.
    assert result.observations["average_speed"].value is None


def test_connected_components_counts_disconnected_subnetworks():
    net = RoadNetwork()
    # Component 1: a--b
    a = net.add_node(0.0, 0.0)
    b = net.add_node(50.0, 0.0)
    net.add_road(a.id, b.id)
    # Component 2: c--d (disjoint)
    c = net.add_node(0.0, 500.0)
    d = net.add_node(50.0, 500.0)
    net.add_road(c.id, d.id)
    # An isolated node with no road must NOT count as a component.
    net.add_node(999.0, 999.0)

    result = analyze(StaticSource(net))
    assert result.observations["connected_components"].value == 2


def test_empty_network_has_zero_components():
    result = analyze(StaticSource(RoadNetwork()))
    assert result.observations["connected_components"].value == 0
    assert result.observations["road_count"].value == 0


def test_units_are_canonical():
    result = analyze(StaticSource(create_test_city()))
    assert result.observations["total_road_length"].units == "ft"
    assert result.observations["average_speed"].units == "mph"


def test_result_is_json_serializable():
    import json
    result = analyze(StaticSource(create_test_city()))
    # Must round-trip through JSON (the API returns this to the client).
    json.dumps(result.to_dict())


def test_deterministic_across_runs():
    net = create_test_city()
    a = _values(analyze(StaticSource(net)))
    b = _values(analyze(StaticSource(net)))
    assert a == b
