"""
Milestone 2 / Milestone 3 additive-plugin tests.

These plugins were added on the existing engine with no core change, so the
tests only exercise the new verticals against hand-computed values and the
shipped standards:

  M2 (traffic operations)
    * vehicle_miles_traveled  -- volume x length, network roll-up
    * excess_capacity         -- flags under-utilized roads, graded
    * right_size_road         -- proposes a road diet for flagged roads only

  M3 (horizontal geometry / access management)
    * curve_advisory_speed    -- point-mass safe speed on a curve
    * curve_speed_advisory    -- fires when advisory < design speed, graded
    * curve_warning_treatment -- proposes fixes for flagged curves only
    * block_length            -- intersection spacing (both ends intersections)
    * short_block_spacing     -- flags blocks under the minimum spacing, graded
    * consolidate_access      -- proposes consolidation for flagged blocks only
    * intersection_density    -- intersections per centerline mile
"""

import math

import pytest

from analysis import default_registry
from analysis.engine import Pipeline
from analysis.metrics import standards
from analysis.snapshot.models import (Snapshot, RoadSnapshot, NodeSnapshot,
                                      SnapshotMeta)


# --- helpers ----------------------------------------------------------------

def _road(rid, *, lf=1, lr=0, vol=None, fclass=None, length_ft=500.0,
          radius=None, ds=None, start=None, end=None):
    return RoadSnapshot(
        id=rid, length_ft=length_ft, lanes_forward=lf, lanes_reverse=lr,
        start_node_id=rid if start is None else start,
        end_node_id=(rid + 1) if end is None else end,
        functional_class=fclass, design_speed=ds,
        observed_volume_vph=vol, governing_curve_radius_ft=radius)


def _node(nid, *, intersection):
    return NodeSnapshot(id=nid, is_intersection=intersection,
                        control_type=None, position=(0.0, 0.0))


def _run(roads, nodes=(), kind="runtime"):
    meta = SnapshotMeta(source_kind=kind, is_running=(kind == "runtime"),
                        sim_time_hours=8.0 if kind == "runtime" else None,
                        tick=1000 if kind == "runtime" else None)
    snap = Snapshot(roads=tuple(roads), nodes=tuple(nodes), buildings=(),
                    vehicles=(), meta=meta)
    return Pipeline(default_registry()).run(snap)


CAP = standards.DEFAULT_CAPACITY_PER_LANE_VPH   # 1-lane default capacity


# --- M2: vehicle_miles_traveled ---------------------------------------------

def test_vmt_is_volume_times_length_in_miles():
    # 600 veh/hr over a 5280 ft (1 mi) road -> 600 veh-mi/hr.
    res = _run([_road(1, vol=600.0, length_ft=5280.0)])
    entry = res.metrics["vehicle_miles_traveled"].detail["per_road"][1]
    assert entry["vmt"] == pytest.approx(600.0)
    assert entry["length_mi"] == pytest.approx(1.0)
    assert res.metrics["vehicle_miles_traveled"].value == pytest.approx(600.0)


def test_vmt_network_total_sums_roads():
    res = _run([_road(1, vol=600.0, length_ft=5280.0),
                _road(2, vol=300.0, length_ft=2640.0)])   # 300 * 0.5 = 150
    assert res.metrics["vehicle_miles_traveled"].value == pytest.approx(750.0)


def test_vmt_absent_without_measured_volume():
    res = _run([_road(1, vol=None)])
    assert res.metrics["vehicle_miles_traveled"].detail["per_road"] == {}
    assert res.metrics["vehicle_miles_traveled"].value is None


# --- M2: excess_capacity finding + right_size_road recommendation -----------

def test_excess_capacity_flags_only_under_utilized_roads():
    # road 1: V/C 0.5 (healthy); road 2: V/C 0.25 (low); road 3: V/C 0.10 (high).
    res = _run([_road(1, vol=0.50 * CAP),
                _road(2, vol=0.25 * CAP),
                _road(3, vol=0.10 * CAP)])
    finding = res.findings["excess_capacity"]
    flagged = {e["road_id"]: e["severity"] for e in finding.evidence}
    assert set(flagged) == {2, 3}                 # road 1 (0.5) not flagged
    assert flagged[2] == "low"
    assert flagged[3] == "high"
    # Most under-utilized first, and the network severity is the worst.
    assert finding.evidence[0]["road_id"] == 3
    assert finding.severity == "high"


def test_excess_capacity_all_clear_and_no_recommendation():
    res = _run([_road(1, vol=0.8 * CAP)])
    assert res.findings["excess_capacity"].evidence == []
    assert res.findings["excess_capacity"].severity == "none"
    assert res.recommendations["right_size_road"].items == []


def test_right_size_targets_only_flagged_roads():
    res = _run([_road(1, vol=0.8 * CAP), _road(2, vol=0.1 * CAP)])
    rec = res.recommendations["right_size_road"]
    assert {it["road_id"] for it in rec.items} == {2}
    assert rec.items[0]["supporting_evidence"]["road_id"] == 2


def test_excess_capacity_ignores_unmeasured_roads():
    # A static (no-volume) road is not evidence of low demand -> never flagged.
    res = _run([_road(1, vol=None)])
    assert res.findings["excess_capacity"].evidence == []


# --- M3: curve_advisory_speed + finding + recommendation --------------------

def test_curve_advisory_speed_matches_point_mass():
    res = _run([_road(1, radius=500.0)])
    entry = res.metrics["curve_advisory_speed"].detail["per_road"][1]
    expected = math.sqrt(15.0 * 500.0 * (standards.MAX_SUPERELEVATION
                                         + standards.SIDE_FRICTION_FACTOR))
    assert entry["advisory_mph"] == pytest.approx(expected)


def test_straight_road_has_no_advisory_speed():
    res = _run([_road(1, radius=None)])
    assert res.metrics["curve_advisory_speed"].detail["per_road"] == {}
    assert res.metrics["curve_advisory_speed"].value is None


def test_curve_speed_advisory_fires_on_sharp_curve():
    # A tight radius: advisory speed well under the default design speed.
    res = _run([_road(1, radius=100.0)])
    finding = res.findings["curve_speed_advisory"]
    assert finding.flagged is True
    e = finding.evidence[0]
    assert e["road_id"] == 1
    assert e["reduction_mph"] > 0
    # A gentle curve on the same default speed clears the finding + recommends nothing.
    res2 = _run([_road(2, radius=5000.0)])
    assert res2.findings["curve_speed_advisory"].evidence == []
    assert res2.recommendations["curve_warning_treatment"].items == []


def test_curve_warning_treatment_targets_flagged_curves():
    res = _run([_road(1, radius=100.0), _road(2, radius=5000.0)])
    rec = res.recommendations["curve_warning_treatment"]
    assert {it["road_id"] for it in rec.items} == {1}
    assert {it["title"] for it in rec.items} == {
        "Increase the curve radius", "Post curve warning + advisory speed"}


# --- M3: block_length + short_block_spacing + consolidate_access -------------

def _block(rid, length_ft, a, b):
    return _road(rid, length_ft=length_ft, start=a, end=b)


def test_block_length_only_counts_intersection_bounded_roads():
    nodes = [_node(1, intersection=True), _node(2, intersection=True),
             _node(3, intersection=False)]
    roads = [_block(10, 400.0, 1, 2),      # both ends intersections -> a block
             _block(11, 250.0, 2, 3)]      # one end not an intersection -> skip
    res = _run(roads, nodes)
    per_road = res.observations["block_length"].detail["per_road"]
    assert set(per_road) == {10}
    assert per_road[10] == 400.0
    assert res.observations["block_length"].value == 400.0


def test_short_block_spacing_grades_and_recommends():
    nodes = [_node(1, intersection=True), _node(2, intersection=True),
             _node(3, intersection=True)]
    # block 10: 400 ft (>= 300 min, clear); block 11: 100 ft (<= half min, high).
    roads = [_block(10, 400.0, 1, 2), _block(11, 100.0, 2, 3)]
    res = _run(roads, nodes)
    finding = res.findings["short_block_spacing"]
    flagged = {e["road_id"]: e["severity"] for e in finding.evidence}
    assert set(flagged) == {11}
    assert flagged[11] == "high"
    rec = res.recommendations["consolidate_access"]
    assert {it["road_id"] for it in rec.items} == {11}


def test_short_block_all_clear_when_spacing_adequate():
    nodes = [_node(1, intersection=True), _node(2, intersection=True)]
    res = _run([_block(10, 800.0, 1, 2)], nodes)
    assert res.findings["short_block_spacing"].evidence == []
    assert res.recommendations["consolidate_access"].items == []


# --- M3: intersection_density -----------------------------------------------

def test_intersection_density_per_mile():
    nodes = [_node(1, intersection=True), _node(2, intersection=True),
             _node(3, intersection=False)]
    # Two intersections over a total 5280 ft (1 mi) of road -> 2.0 per mile.
    res = _run([_road(1, length_ft=5280.0, start=1, end=2)], nodes)
    assert res.metrics["intersection_density"].value == pytest.approx(2.0)


def test_intersection_density_none_on_empty_network():
    res = _run([], [])
    assert res.metrics["intersection_density"].value is None


# --- standards swap: a data change moves results, no plugin change ------------

def test_side_friction_swap_changes_advisory_speed(monkeypatch):
    base = _run([_road(1, radius=500.0)]).metrics[
        "curve_advisory_speed"].value
    monkeypatch.setattr(standards, "SIDE_FRICTION_FACTOR",
                        standards.SIDE_FRICTION_FACTOR * 4)
    higher = _run([_road(1, radius=500.0)]).metrics[
        "curve_advisory_speed"].value
    assert higher == pytest.approx(base * 2)      # sqrt(4x) = 2x


def test_min_spacing_swap_changes_short_block(monkeypatch):
    nodes = [_node(1, intersection=True), _node(2, intersection=True)]
    roads = [_block(10, 400.0, 1, 2)]             # 400 ft block, clears 300 default
    assert _run(roads, nodes).findings["short_block_spacing"].evidence == []
    monkeypatch.setattr(standards, "MIN_INTERSECTION_SPACING_FT", 500.0)
    assert _run(roads, nodes).findings["short_block_spacing"].flagged is True
