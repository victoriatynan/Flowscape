"""Diagnostic: width-transition (taper) surfaces at 2-road continuation
nodes joining roads of different widths.

Checks, for every taper the assembly pass builds:
1. NO LOOP: neither S-curve edge polyline self-intersects, and the two
   edges never cross each other.
2. FULL WIDTH: the wider road's mouth chord is its full profile width
   (the wide road never necks down before the node).

Pure geometry -- no rendering (re-based from the pygame renderer per
WEB_MIGRATION_PLAN.md Phase 6; the taper capture now hooks
build_node_surfaces' taper_builder instead of monkey-patching the
renderer). Known pre-existing violations are reported, not asserted.

Run:  python check_taper.py    (exit 1 if any violations)
"""

import math

from check_fillet_direction import _polyline_self_intersects
from junction_scenarios import TAPER_SCENARIOS
from road_geometry import (build_node_surfaces, _build_taper_polygon,
                           _taper_curve, _segment_intersection)
from road_style import get_road_profile


def main():
    total = 0
    all_violations = []
    for name, builder in TAPER_SCENARIOS:
        net = builder()

        captured = []

        def capture(entries, _captured=captured):
            _captured.append(entries)
            return _build_taper_polygon(entries)

        build_node_surfaces(net, taper_builder=capture)

        violations = []
        for entries in captured:
            total += 1
            a, b = entries
            edges = []
            for p, q in ((a, b), (b, a)):
                curve = _taper_curve(p["left"], p["outward"],
                                     q["right"], q["outward"], samples=24)
                edges.append([p["left"]] + curve + [q["right"]])
            for side, edge in zip(("left", "right"), edges):
                hit = _polyline_self_intersects(edge)
                if hit is not None:
                    violations.append(f"taper_{name}: {side} edge SELF-INTERSECTS "
                                      f"near ({hit[0]:.1f}, {hit[1]:.1f})")
            for s1 in range(len(edges[0]) - 1):
                for s2 in range(len(edges[1]) - 1):
                    hit = _segment_intersection(
                        edges[0][s1], edges[0][s1 + 1], edges[1][s2], edges[1][s2 + 1])
                    if hit is not None:
                        violations.append(f"taper_{name}: edges CROSS near "
                                          f"({hit[0]:.1f}, {hit[1]:.1f})")
                        break
                else:
                    continue
                break
            for e in entries:
                mouth = math.hypot(e["left"][0] - e["right"][0],
                                   e["left"][1] - e["right"][1])
                if mouth < 1.0:
                    violations.append(f"taper_{name}: degenerate mouth ({mouth:.2f} ft)")

        # the wider road must not be trimmed past its token setback
        for road in net.roads.values():
            for nid in (road.start_node_id, road.end_node_id):
                roads_here = net.roads_for_node(nid)
                if len(roads_here) != 2:
                    continue
                other = roads_here[0] if roads_here[1].id == road.id else roads_here[1]
                if get_road_profile(road).total_width() > get_road_profile(other).total_width() + 1e-6:
                    trim = net.road_trim_at_node(road, nid)
                    if trim > net.TAPER_WIDE_SETBACK + 1e-6:
                        violations.append(f"taper_{name}: WIDE road {road.id} trimmed "
                                          f"{trim:.1f} ft at node {nid}")

        status = "FAIL" if violations else "ok"
        print(f"[{status}] taper_{name}: {len(captured)} taper(s) drawn")
        for v in violations:
            print(f"       {v}")
        all_violations.extend(violations)

    print(f"\n{total} tapers checked, {len(all_violations)} violation(s).")
    return 1 if all_violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
