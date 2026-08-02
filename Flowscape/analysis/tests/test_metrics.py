"""
Metric tests: capacity, V/C, and level of service computed from a snapshot with
known per-road volume, cross-checked against a hand calculation and the shipped
standards. Static snapshots (no measured volume) must yield None / empty maps.
"""

import pytest

from analysis import default_registry
from analysis.engine import Pipeline
from analysis.metrics import standards
from analysis.snapshot.models import Snapshot, RoadSnapshot, SnapshotMeta


def _runtime_snapshot(roads):
    meta = SnapshotMeta(source_kind="runtime", is_running=True,
                        sim_time_hours=8.0, tick=1000)
    return Snapshot(roads=tuple(roads), nodes=(), buildings=(), vehicles=(),
                    meta=meta)


def _road(rid, *, lf=1, lr=0, vol=None, fclass=None):
    return RoadSnapshot(id=rid, length_ft=500.0, lanes_forward=lf,
                        lanes_reverse=lr, start_node_id=rid, end_node_id=rid + 1,
                        functional_class=fclass, observed_volume_vph=vol)


def _run(roads):
    return Pipeline(default_registry()).run(_runtime_snapshot(roads))


def test_capacity_is_total_lanes_times_per_lane_standard():
    # 1 fwd + 1 rev local road, no functional class -> default per-lane capacity.
    res = _run([_road(1, lf=1, lr=1, vol=100.0)])
    cap = res.metrics["road_capacity"].detail["per_road"][1]
    assert cap == 2 * standards.DEFAULT_CAPACITY_PER_LANE_VPH


def test_capacity_uses_functional_class_when_present():
    res = _run([_road(1, lf=2, lr=0, vol=100.0, fclass="arterial")])
    cap = res.metrics["road_capacity"].detail["per_road"][1]
    assert cap == 2 * standards.CAPACITY_PER_LANE_VPH["arterial"]


def test_vc_ratio_matches_hand_calc():
    # volume 1200 over capacity 800 (1 lane default) -> V/C 1.5.
    res = _run([_road(1, lf=1, lr=0, vol=1200.0)])
    entry = res.metrics["vc_ratio"].detail["per_road"][1]
    assert entry["vc"] == pytest.approx(1200.0 / standards.DEFAULT_CAPACITY_PER_LANE_VPH)
    assert entry["volume"] == 1200.0
    assert entry["capacity"] == standards.DEFAULT_CAPACITY_PER_LANE_VPH
    # Network roll-up is the worst V/C.
    assert res.metrics["vc_ratio"].value == pytest.approx(entry["vc"])


def test_los_letter_from_bands():
    # V/C 0.5 -> A; V/C 1.5 -> F. Two roads, worst LOS is F.
    res = _run([_road(1, lf=1, lr=0, vol=400.0),     # 400/800 = 0.5 -> A
                _road(2, lf=1, lr=0, vol=1200.0)])    # 1200/800 = 1.5 -> F
    los = res.metrics["level_of_service"].detail["per_road"]
    assert los[1] == "A"
    assert los[2] == "F"
    assert res.metrics["level_of_service"].value == "F"


def test_road_without_measured_volume_is_absent_from_vc():
    res = _run([_road(1, lf=1, lr=0, vol=None)])
    assert res.metrics["vc_ratio"].detail["per_road"] == {}
    assert res.metrics["vc_ratio"].value is None
    assert res.metrics["level_of_service"].value is None


def test_static_snapshot_yields_no_traffic_metrics():
    # No volume anywhere (mirrors a static editor map) -> V/C and LOS undefined,
    # but capacity (a static property) is still computed.
    static = Snapshot(
        roads=(_road(1, lf=1, lr=0, vol=None),), nodes=(), buildings=(),
        vehicles=(), meta=SnapshotMeta(source_kind="static", is_running=False))
    res = Pipeline(default_registry()).run(static)
    assert res.metrics["vc_ratio"].value is None
    assert res.metrics["road_capacity"].detail["per_road"][1] > 0
