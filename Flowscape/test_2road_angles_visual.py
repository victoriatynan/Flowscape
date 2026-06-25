"""
Headless visual + assertion sweep of a 2-road continuation node across many
arm angles, rendered through the REAL RoadRenderer (same path as
test_intersections_visual).

  - Saves one PNG per angle into test_output/angle_sweep_2road/ for eyeballing.
  - Asserts the lane-marking CONNECTORS drawn through each bend never cross
    one another. The edge-pairing bug (matching b's mouth to a's by nearest
    endpoint) made an edge connector slash across the center line at bends;
    matching by physical side fixed it. This guards against that regressing.

Whatever connectors a node draws (0 for sharp folds today, 3 for an equal-
width urban bend) must stay mutually non-crossing, so the invariant also
holds if the fold regime later starts drawing connectors.

Run:  python3 test_2road_angles_visual.py   (exit 1 if any connectors cross)
"""

import math
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from road_editor import (RoadNetwork, Camera, RoadRenderer,
                          CANVAS_WIDTH, CANVAS_HEIGHT)

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "test_output", "angle_sweep_2road")


def two_road_node(arm_angle_deg, length=170.0, preset_a="urban", preset_b="urban"):
    """One shared center node with two roads: arm A points due west,
    arm B is placed so the visible angle between the two arms == arm_angle_deg."""
    net = RoadNetwork()
    c = net.add_node(0.0, 0.0)
    a_out = net.add_node(-length, 0.0)
    bdir = math.radians(180.0 - arm_angle_deg)
    b_out = net.add_node(length * math.cos(bdir), length * math.sin(bdir))
    ra = net.add_road(a_out.id, c.id)
    rb = net.add_road(c.id, b_out.id)
    ra.data["profile"] = {"preset": preset_a}
    rb.data["profile"] = {"preset": preset_b}
    return net, c.id


def _make_renderer(net, surface, font):
    camera = Camera()
    camera.zoom = 1.2
    xs = [n.x for n in net.nodes.values()]
    ys = [n.y for n in net.nodes.values()]
    cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    s = camera._scale()
    camera.offset_x = cx - (CANVAS_WIDTH / 2.0) / s
    camera.offset_y = cy - (CANVAS_HEIGHT / 2.0) / s
    return RoadRenderer(surface, font, camera)


def render(name, net, surface, font):
    renderer = _make_renderer(net, surface, font)
    renderer.draw(net, None, None, None, False, None, None, None, None,
                  "select_tool", debug=False)
    path = os.path.join(OUTPUT_DIR, f"{name}.png")
    pygame.image.save(surface, path)
    return path


def _segments_cross(a1, a2, b1, b2):
    """True only for a PROPER crossing (strict sign change on both sides), so
    connectors that merely share/touch an endpoint don't count."""
    def cross(o, p, q):
        return (q[1] - o[1]) * (p[0] - o[0]) - (p[1] - o[1]) * (q[0] - o[0])
    d1 = cross(b1, b2, a1)
    d2 = cross(b1, b2, a2)
    d3 = cross(a1, a2, b1)
    d4 = cross(a1, a2, b2)
    return (d1 > 0) != (d2 > 0) and (d3 > 0) != (d4 > 0)


def _polylines_cross(p, q):
    for i in range(len(p) - 1):
        for j in range(len(q) - 1):
            if _segments_cross(p[i], p[i + 1], q[j], q[j + 1]):
                return True
    return False


def _capture(renderer, draw_fn):
    """Run draw_fn() while intercepting _draw_thick_polyline; return every
    screen-space polyline it strokes."""
    captured = []
    orig = renderer._draw_thick_polyline

    def recording(color, screen_pts, width):
        captured.append(list(screen_pts))
        return orig(color, screen_pts, width)

    renderer._draw_thick_polyline = recording
    draw_fn()
    renderer._draw_thick_polyline = orig
    return captured


def connectors_for(net, node_id, surface, font):
    """Capture the continuation-marking CONNECTOR polylines (>=90 deg bends)."""
    renderer = _make_renderer(net, surface, font)
    return _capture(renderer, lambda: renderer.draw_continuation_markings(net, node_id))


def markings_for(net, road, surface, font):
    """Capture one road's painted lane-marking polylines (already trimmed back
    to the node mouth)."""
    renderer = _make_renderer(net, surface, font)
    geom = net.geometry_for_road(road)
    return _capture(renderer, lambda: renderer.draw_road_markings(net, road, geom))


def check_no_crossing(net, node_id, surface, font):
    """Two invariants, both of which the overlapping-fold / mis-paired-bend
    bugs violated:
      1. the bend's connector polylines never cross each other, and
      2. the two roads' own trimmed markings never cross each other (the
         fold guard: folds draw 0 connectors, so this is what catches a
         fold that overlapped instead of trimming back)."""
    failures = []
    lines = connectors_for(net, node_id, surface, font)
    for i in range(len(lines)):
        for j in range(i + 1, len(lines)):
            if _polylines_cross(lines[i], lines[j]):
                failures.append(("connector", i, j))

    roads = [r for r in net.roads_for_node(node_id) if not r.is_preview]
    if len(roads) == 2:
        ma = markings_for(net, roads[0], surface, font)
        mb = markings_for(net, roads[1], surface, font)
        for pa in ma:
            for pb in mb:
                if _polylines_cross(pa, pb):
                    failures.append(("road-markings", roads[0].id, roads[1].id))
                    break
            else:
                continue
            break

    return len(lines), failures


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    pygame.init()
    pygame.display.set_mode((CANVAS_WIDTH, CANVAS_HEIGHT))
    font = pygame.font.SysFont("monospace", 13)
    surface = pygame.Surface((CANVAS_WIDTH, CANVAS_HEIGHT))

    cases = []
    for ang in (180, 150, 120, 90, 75, 60, 45, 30):
        cases.append((f"equal_{ang:03d}", two_road_node(ang)))
    # Sharp folds on a long road exercise the UNCAPPED rounded-bend arc (the
    # 170ft cases above hit the road-length cap on the tangent pullback).
    cases.append(("equal_030_long", two_road_node(30, length=420.0)))
    cases.append(("equal_045_long", two_road_node(45, length=420.0)))
    cases.append(("mismatch_180", two_road_node(180, preset_a="residential", preset_b="highway")))
    cases.append(("mismatch_120", two_road_node(120, preset_a="residential", preset_b="highway")))

    all_failures = []
    for name, (net, cid) in cases:
        surface.fill((0, 0, 0))
        path = render(name, net, surface, font)
        n_lines, failures = check_no_crossing(net, cid, surface, font)
        status = "FAIL" if failures else "ok"
        print(f"[{status}] {name}: {n_lines} connector(s), "
              f"{len(failures)} crossing(s) -> {os.path.basename(path)}")
        for kind, x, y in failures:
            if kind == "connector":
                print(f"       connectors {x} and {y} cross")
            else:
                print(f"       roads {x} and {y} markings cross at the node")
        all_failures.extend((name, f) for f in failures)

    pygame.quit()
    if all_failures:
        print(f"\n{len(all_failures)} crossing(s): lane lines intersect at a "
              f"2-road node.")
        sys.exit(1)
    print("\nAll scenarios passed: no lane lines cross at any 2-road node.")


if __name__ == "__main__":
    main()
