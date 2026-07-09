"""
Junction-surface assembly guards (pure geometry; no rendering).

Re-bases the retired pygame visual sweep's programmatic assertion -- "no
circular asphalt patch is ever drawn at an intersection" -- onto
road_geometry.build_node_surfaces(), which both the (retired) editor
renderer and the web API tessellate from:

  1. CAPS ONLY AT DEAD ENDS: every cap is a node with exactly one road,
     and every dead end gets exactly one cap.
  2. SURFACES AT EVERY MULTI-ROAD NODE: every node with >= 2 non-preview
     roads gets exactly one surface polygon (junction / continuation /
     taper), classified correctly by road count and width.
  3. TRIMS LEAVE ROOM: every trimmed road keeps a drawable centerline.

Run:  python test_junction_surfaces.py
"""

from junction_scenarios import SCENARIOS, EXTRA, TAPER_SCENARIOS
from road_geometry import build_node_surfaces
from road_style import get_road_profile


def _all_scenarios():
    return list(SCENARIOS) + list(EXTRA) + [
        ("taper_" + n, b) for n, b in TAPER_SCENARIOS]


def test_caps_only_at_dead_ends():
    for name, builder in _all_scenarios():
        net = builder()
        surfaces = build_node_surfaces(net)
        dead_ends = {nid for nid in net.nodes
                     if len(net.roads_for_node(nid)) == 1}
        cap_nodes = {c["node_id"] for c in surfaces["caps"]}
        assert cap_nodes == dead_ends, (
            f"{name}: caps {sorted(cap_nodes)} != dead ends {sorted(dead_ends)}")
        for cap in surfaces["caps"]:
            road = net.roads_for_node(cap["node_id"])[0]
            assert cap["radius"] == get_road_profile(road).total_width() / 2.0
    print("ok: circular caps appear at every dead end and nowhere else")


def test_every_multi_road_node_gets_one_surface():
    for name, builder in _all_scenarios():
        net = builder()
        surfaces = build_node_surfaces(net)
        by_node = {}
        for s in surfaces["nodes"]:
            assert s["node_id"] not in by_node, f"{name}: duplicate surface"
            by_node[s["node_id"]] = s
        multi = {nid for nid in net.nodes if len(net.roads_for_node(nid)) >= 2}
        assert set(by_node) == multi, (
            f"{name}: surfaced nodes {sorted(by_node)} != multi-road {sorted(multi)}")
        for nid, s in by_node.items():
            n_roads = len(net.roads_for_node(nid))
            assert len(s["polygon"]) >= 4
            assert s["mouth_width"] > 0
            if n_roads >= 3:
                assert s["kind"] == "junction", f"{name}/node{nid}: {s['kind']}"
            else:
                widths = sorted(get_road_profile(r).total_width()
                                for r in net.roads_for_node(nid))
                expected = ("taper" if widths[1] - widths[0] > 1e-3
                            else "continuation")
                # Sharp folds take the continuation band even with differing
                # widths (see _is_width_taper) -- allow that downgrade only.
                assert s["kind"] == expected or (
                    expected == "taper" and s["kind"] == "continuation"), (
                    f"{name}/node{nid}: kind {s['kind']}, expected {expected}")
    print("ok: every 2+-road node gets exactly one correctly-classified surface")


def test_trims_leave_drawable_roads():
    for name, builder in _all_scenarios():
        net = builder()
        surfaces = build_node_surfaces(net)
        for rid, pts in surfaces["trimmed_points"].items():
            assert len(pts) >= 2, f"{name}: road {rid} trimmed to nothing"
    print("ok: junction trims always leave a drawable centerline")


if __name__ == "__main__":
    test_caps_only_at_dead_ends()
    test_every_multi_road_node_gets_one_surface()
    test_trims_leave_drawable_roads()
    print("\njunction-surfaces: all tests passed")
