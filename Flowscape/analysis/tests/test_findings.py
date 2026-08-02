"""
Finding + recommendation tests: OverCapacity flags exactly the roads at/above
the practical-capacity threshold with the right severity and traceable
evidence, and AddCapacity proposes improvements only for flagged roads.
"""

from analysis import default_registry
from analysis.engine import Pipeline
from analysis.metrics import standards
from analysis.snapshot.models import Snapshot, RoadSnapshot, SnapshotMeta

CAP = standards.DEFAULT_CAPACITY_PER_LANE_VPH   # 1-lane default capacity


def _road(rid, vol):
    return RoadSnapshot(id=rid, length_ft=500.0, lanes_forward=1, lanes_reverse=0,
                        start_node_id=rid, end_node_id=rid + 1,
                        observed_volume_vph=vol)


def _run(roads):
    meta = SnapshotMeta(source_kind="runtime", is_running=True,
                        sim_time_hours=8.0, tick=1000)
    snap = Snapshot(roads=tuple(roads), nodes=(), buildings=(), vehicles=(),
                    meta=meta)
    return Pipeline(default_registry()).run(snap)


def test_flags_only_roads_at_or_above_threshold():
    # road 1: V/C 0.5 (healthy); road 2: V/C 0.95 (moderate); road 3: V/C 2.0 (high).
    res = _run([_road(1, 0.50 * CAP), _road(2, 0.95 * CAP), _road(3, 2.0 * CAP)])
    finding = res.findings["over_capacity"]
    flagged = {e["road_id"]: e["severity"] for e in finding.evidence}
    assert set(flagged) == {2, 3}                 # road 1 (below threshold) excluded
    assert flagged[2] == "moderate"
    assert flagged[3] == "high"
    # Worst-first ordering and network severity.
    assert finding.evidence[0]["road_id"] == 3
    assert finding.severity == "high"
    assert finding.flagged is True


def test_evidence_is_traceable():
    res = _run([_road(1, 2.0 * CAP)])
    e = res.findings["over_capacity"].evidence[0]
    assert e["road_id"] == 1
    assert e["capacity_vph"] == CAP
    assert e["volume_vph"] == 2.0 * CAP
    assert e["vc"] == 2.0


def test_all_clear_when_nothing_over_capacity():
    res = _run([_road(1, 0.3 * CAP), _road(2, 0.5 * CAP)])
    finding = res.findings["over_capacity"]
    assert finding.evidence == []
    assert finding.flagged is False
    assert finding.severity == "none"
    # And no recommendations are produced.
    assert res.recommendations["add_capacity"].items == []


def test_recommendations_target_flagged_roads():
    res = _run([_road(1, 0.4 * CAP), _road(2, 1.5 * CAP)])
    rec = res.recommendations["add_capacity"]
    road_ids = {it["road_id"] for it in rec.items}
    assert road_ids == {2}                        # only the flagged road
    titles = {it["title"] for it in rec.items}
    assert titles == {"Add a through lane", "Reduce upstream demand"}
    # Every proposal carries the evidence it addresses.
    for it in rec.items:
        assert it["supporting_evidence"]["road_id"] == 2
