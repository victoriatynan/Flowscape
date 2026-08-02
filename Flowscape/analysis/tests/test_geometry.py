"""
Milestone 3 -- horizontal geometric design (stopping sight distance) tests.

Covers the whole geometry vertical against hand-computed values:
  * geometry_math   -- analytic governing radius + deflection from Bezier points
  * snapshot        -- radius/deflection extracted at the builder boundary
  * observation     -- horizontal_curvature per-road + sharpest roll-up
  * metrics         -- required_ssd (AASHTO, no grade) + available_ssd (sightline)
  * finding         -- ssd_deficiency fires/clears, graded by the standards bands
  * recommendation  -- improve_sight_distance proposes the three horizontal levers
  * standards swap  -- changing a standard changes results with no plugin change
"""

import math

import pytest

from road_network import RoadNetwork

from analysis import default_registry
from analysis.engine import Pipeline
from analysis.metrics import standards
from analysis.snapshot import StaticSource, build_snapshot
from analysis.snapshot.geometry_math import (governing_curve_radius_ft,
                                             horizontal_deflection_deg)
from analysis.snapshot.models import Snapshot, RoadSnapshot, SnapshotMeta


# --- helpers ----------------------------------------------------------------

def _road(rid, *, radius=None, defl=0.0, ds=None, fc=None):
    """A geometry-only RoadSnapshot; traffic fields left at their defaults."""
    return RoadSnapshot(id=rid, length_ft=500.0, lanes_forward=1, lanes_reverse=1,
                        start_node_id=rid, end_node_id=rid + 1,
                        functional_class=fc, design_speed=ds,
                        governing_curve_radius_ft=radius,
                        horizontal_deflection_angle_deg=defl)


def _run(roads, kind="static"):
    meta = SnapshotMeta(source_kind=kind, is_running=(kind == "runtime"))
    snap = Snapshot(roads=tuple(roads), nodes=(), buildings=(), vehicles=(),
                    meta=meta)
    return Pipeline(default_registry()).run(snap)


# --- geometry_math (pure analytic) ------------------------------------------

def test_straight_road_has_no_radius():
    # Control point on the chord -> no curvature.
    assert governing_curve_radius_ft((0, 0), (50, 0), (100, 0)) is None
    assert governing_curve_radius_ft((0, 0), (70, 0), (100, 0)) is None
    assert horizontal_deflection_deg((0, 0), (50, 0), (100, 0)) == 0.0


def test_symmetric_curve_radius_is_exact():
    # For P0=(0,0), P1=(50,h), P2=(100,0) the governing radius is 2500/h.
    for h, expect in [(25, 100.0), (50, 50.0), (100, 25.0)]:
        r = governing_curve_radius_ft((0, 0), (50, h), (100, 0))
        assert r == pytest.approx(expect, rel=1e-9)


def test_deflection_angle():
    # Tangents (50,50) and (50,-50) meet at 90 degrees.
    assert horizontal_deflection_deg((0, 0), (50, 50), (100, 0)) == pytest.approx(90.0)


# --- builder extraction on a real network -----------------------------------

def _curved_network(curve_offset):
    net = RoadNetwork()
    a = net.add_node(0.0, 0.0)
    b = net.add_node(100.0, 0.0)
    net.add_road(a.id, b.id, curve_offset=curve_offset)
    return net


def test_builder_extracts_radius_and_deflection():
    # curve_offset (0, 25) -> control point (50, 25) -> radius 100 ft.
    snap = build_snapshot(StaticSource(_curved_network((0.0, 25.0))))
    road = snap.roads[0]
    assert road.governing_curve_radius_ft == pytest.approx(100.0, abs=1e-6)
    assert road.horizontal_deflection_angle_deg > 0.0


def test_builder_straight_road_radius_is_none():
    snap = build_snapshot(StaticSource(_curved_network((0.0, 0.0))))
    road = snap.roads[0]
    assert road.governing_curve_radius_ft is None
    assert road.horizontal_deflection_angle_deg == pytest.approx(0.0)


# --- observation ------------------------------------------------------------

def test_horizontal_curvature_reports_per_road_and_sharpest():
    res = _run([_road(1, radius=100.0, defl=53.0),
                _road(2, radius=400.0, defl=12.0),
                _road(3, radius=None)])
    per_road = res.observations["horizontal_curvature"].detail["per_road"]
    assert per_road[1]["radius_ft"] == 100.0
    assert per_road[3]["radius_ft"] is None
    # Sharpest (smallest finite) radius on the network.
    assert res.observations["horizontal_curvature"].value == 100.0


def test_horizontal_curvature_all_straight_is_none():
    res = _run([_road(1, radius=None), _road(2, radius=None)])
    assert res.observations["horizontal_curvature"].value is None


# --- metrics ----------------------------------------------------------------

def test_required_ssd_matches_hand_calc_and_default_speed():
    # No design_speed, no class -> global default (30 mph).
    res = _run([_road(1, radius=100.0)])
    entry = res.metrics["required_ssd"].detail["per_road"][1]
    v = standards.DEFAULT_DESIGN_SPEED_MPH
    hand = 1.47 * v * standards.PERCEPTION_REACTION_S + \
        (v * v) / (30.0 * (standards.DECELERATION_FPS2 / standards.GRAVITY_FPS2))
    assert entry["design_speed_mph"] == v
    assert entry["required_ft"] == pytest.approx(hand)


def test_required_ssd_uses_class_default_when_no_design_speed():
    res = _run([_road(1, radius=100.0, fc="arterial")])
    entry = res.metrics["required_ssd"].detail["per_road"][1]
    assert entry["design_speed_mph"] == standards.DESIGN_SPEED_BY_CLASS["arterial"]


def test_available_ssd_matches_sightline_formula():
    res = _run([_road(1, radius=100.0)])
    entry = res.metrics["available_ssd"].detail["per_road"][1]
    m = standards.DEFAULT_LATERAL_CLEARANCE_FT
    hand = 100.0 / (90.0 / math.pi) * math.degrees(math.acos((100.0 - m) / 100.0))
    assert entry["available_ft"] == pytest.approx(hand)
    assert entry["radius_ft"] == 100.0


def test_available_ssd_absent_for_straight_road():
    res = _run([_road(1, radius=None)])
    assert res.metrics["available_ssd"].detail["per_road"] == {}
    assert res.metrics["available_ssd"].value is None


# --- finding ----------------------------------------------------------------

def test_ssd_deficiency_flags_sharp_curve():
    # R=100 at 30 mph: available ~90 ft << required ~196 ft -> deficient (high).
    res = _run([_road(1, radius=100.0)])
    f = res.findings["ssd_deficiency"]
    assert f.flagged
    assert f.severity == "high"
    e = f.evidence[0]
    assert e["road_id"] == 1
    assert e["margin_ft"] < 0
    assert e["available_ft"] < e["required_ft"]
    assert e["radius_ft"] == 100.0


def test_ssd_deficiency_clears_on_flat_curve():
    # A very large radius provides ample sight distance -> nothing flagged.
    res = _run([_road(1, radius=2000.0)])
    f = res.findings["ssd_deficiency"]
    assert not f.flagged
    assert f.severity == "none"


def test_ssd_deficiency_ignores_straight_roads():
    res = _run([_road(1, radius=None)])
    assert res.findings["ssd_deficiency"].flagged is False


def test_ssd_severity_bands():
    # Directly exercise the standards grading around the band edges.
    assert standards.ssd_severity(200.0, 200.0) == "none"
    assert standards.ssd_severity(200.0, 210.0) == "none"      # surplus
    assert standards.ssd_severity(200.0, 185.0) == "low"       # 7.5% deficit
    assert standards.ssd_severity(200.0, 175.0) == "moderate"  # 12.5%
    assert standards.ssd_severity(200.0, 140.0) == "high"      # 30%


# --- recommendation ---------------------------------------------------------

def test_recommendation_proposes_three_levers_per_flagged_road():
    res = _run([_road(1, radius=100.0)])
    rec = res.recommendations["improve_sight_distance"]
    assert len(rec.items) == 3
    titles = {i["title"] for i in rec.items}
    assert any("radius" in t for t in titles)
    assert any("design speed" in t for t in titles)
    assert any("obstruction" in t for t in titles)
    assert all(i["road_id"] == 1 for i in rec.items)


def test_recommendation_empty_when_no_deficiency():
    res = _run([_road(1, radius=2000.0)])
    assert res.recommendations["improve_sight_distance"].items == []


# --- standards swap (principle 5) -------------------------------------------

def test_design_speed_default_swap_changes_required_ssd(monkeypatch):
    base = _run([_road(1, radius=100.0)]).metrics["required_ssd"].value
    monkeypatch.setattr(standards, "DEFAULT_DESIGN_SPEED_MPH", 50)
    faster = _run([_road(1, radius=100.0)]).metrics["required_ssd"].value
    assert faster > base                    # higher design speed -> longer SSD


def test_lateral_clearance_swap_changes_available_ssd(monkeypatch):
    base = _run([_road(1, radius=100.0)]).metrics["available_ssd"].value
    monkeypatch.setattr(standards, "DEFAULT_LATERAL_CLEARANCE_FT", 20.0)
    wider = _run([_road(1, radius=100.0)]).metrics["available_ssd"].value
    assert wider > base                     # more clearance -> more sight distance
