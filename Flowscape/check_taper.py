"""Diagnostic: width-transition (taper) surfaces at 2-road continuation
nodes joining roads of different widths.

Checks, for every taper drawn:
1. NO LOOP -- neither S-curve edge polyline self-intersects, and the two
   edges never cross each other.
2. FULL WIDTH -- the wider road's mouth chord is its full profile width
   (the wide road never necks down before the node).

Renders each scenario to test_output/taper_<name>.png for eyeballing.
"""

import math
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

import road_editor
from road_editor import (RoadNetwork, Camera, RoadRenderer,
                          CANVAS_WIDTH, CANVAS_HEIGHT)
from road_style import get_road_profile
from check_fillet_direction import _polyline_self_intersects

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_output")


def _net(segments):
    """segments: [((x1,y1),(x2,y2), preset, curve_offset), ...] sharing
    coincident endpoints via position lookup."""
    net = RoadNetwork()
    nodes = {}

    def node_at(p):
        if p not in nodes:
            nodes[p] = net.add_node(*p)
        return nodes[p]

    for p1, p2, preset, offset in segments:
        road = net.add_road(node_at(p1).id, node_at(p2).id, curve_offset=offset)
        road.data["profile"] = {"preset": preset}
    return net


SCENARIOS = [
    ("straight", lambda: _net([
        ((-220.0, 0.0), (0.0, 0.0), "highway", (0.0, 0.0)),
        ((0.0, 0.0), (220.0, 0.0), "residential", (0.0, 0.0)),
    ])),
    ("bent", lambda: _net([
        ((-220.0, 0.0), (0.0, 0.0), "highway", (0.0, 0.0)),
        ((0.0, 0.0), (170.0, 130.0), "residential", (0.0, 0.0)),
    ])),
    ("curved", lambda: _net([
        ((-220.0, 0.0), (0.0, 0.0), "expressway", (0.0, 40.0)),
        ((0.0, 0.0), (220.0, 0.0), "urban", (0.0, -40.0)),
    ])),
    ("narrow_between", lambda: _net([
        ((-260.0, 0.0), (-60.0, 0.0), "highway", (0.0, 0.0)),
        ((-60.0, 0.0), (60.0, 0.0), "residential", (0.0, 0.0)),
        ((60.0, 0.0), (260.0, 0.0), "expressway", (0.0, 0.0)),
    ])),
    ("hairpin", lambda: _net([
        ((-220.0, 0.0), (0.0, 0.0), "highway", (0.0, 0.0)),
        ((0.0, 0.0), (-200.0, 70.0), "residential", (0.0, 0.0)),
    ])),
    ("bend_90", lambda: _net([
        ((-220.0, 0.0), (0.0, 0.0), "highway", (0.0, 0.0)),
        ((0.0, 0.0), (10.0, 200.0), "residential", (0.0, 0.0)),
    ])),
]


def main():
    pygame.init()
    pygame.display.set_mode((CANVAS_WIDTH, CANVAS_HEIGHT))
    font = pygame.font.SysFont("monospace", 13)
    surface = pygame.Surface((CANVAS_WIDTH, CANVAS_HEIGHT))

    total = 0
    all_violations = []
    for name, builder in SCENARIOS:
        net = builder()
        captured = []
        orig = road_editor._build_taper_polygon

        def capture(entries, _captured=captured):
            _captured.append(entries)
            return orig(entries)

        road_editor._build_taper_polygon = capture
        try:
            camera = Camera()
            camera.zoom = 2.0
            xs = [n.x for n in net.nodes.values()]
            ys = [n.y for n in net.nodes.values()]
            cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
            s = camera._scale()
            camera.offset_x = cx - (CANVAS_WIDTH / 2.0) / s
            camera.offset_y = cy - (CANVAS_HEIGHT / 2.0) / s
            renderer = RoadRenderer(surface, font, camera)
            renderer.draw(net, None, None, None, False, None, None, None, None,
                           "select_tool", debug=False)
            pygame.image.save(surface, os.path.join(OUTPUT_DIR, f"taper_{name}.png"))
        finally:
            road_editor._build_taper_polygon = orig

        violations = []
        for entries in captured:
            total += 1
            a, b = entries
            edges = []
            for p, q in ((a, b), (b, a)):
                curve = road_editor._taper_curve(p["left"], p["outward"],
                                                  q["right"], q["outward"], samples=24)
                edges.append([p["left"]] + curve + [q["right"]])
            for side, edge in zip(("left", "right"), edges):
                hit = _polyline_self_intersects(edge)
                if hit is not None:
                    violations.append(f"taper_{name}: {side} edge SELF-INTERSECTS "
                                      f"near ({hit[0]:.1f}, {hit[1]:.1f})")
            for s1 in range(len(edges[0]) - 1):
                for s2 in range(len(edges[1]) - 1):
                    hit = road_editor._segment_intersection(
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

    pygame.quit()
    print(f"\n{total} tapers checked, {len(all_violations)} violation(s).")
    return 1 if all_violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
