"""
Visual intersection test (headless).

Renders a set of intersection scenarios through the REAL RoadRenderer to
PNG files (test_output/), so the junction surfaces can be inspected by eye.

Also asserts programmatically that no circular asphalt patch is drawn at
any intersection node (3+ connected roads): pygame.draw.circle is wrapped
to record every circle filled with COLOR_ROAD_SURFACE, and each one must
correspond to a dead-end cap (node with exactly one road), never an
intersection.

Run:  python3 test_intersections_visual.py
"""

import math
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

import road_editor
from road_editor import (RoadNetwork, Camera, RoadRenderer, COLOR_ROAD_SURFACE,
                          CANVAS_WIDTH, CANVAS_HEIGHT)

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_output")


# ----------------------------------------------------------------------
# Scenario builders: each returns a populated RoadNetwork.
# Coordinates are world-space feet; junction node at (0, 0).
# ----------------------------------------------------------------------

def _spoke_network(angles_deg, length=160.0, presets=None, curve_offsets=None):
    """Junction at origin with one road per angle, radiating outward."""
    net = RoadNetwork()
    center = net.add_node(0.0, 0.0)
    for i, ang in enumerate(angles_deg):
        rad = math.radians(ang)
        outer = net.add_node(length * math.cos(rad), length * math.sin(rad))
        offset = curve_offsets[i] if curve_offsets else (0.0, 0.0)
        road = net.add_road(center.id, outer.id, curve_offset=offset)
        if presets:
            road.data["profile"] = {"preset": presets[i % len(presets)]}
    return net


def scenario_4way_cross():
    return _spoke_network([0, 90, 180, 270])


def scenario_3way_t():
    return _spoke_network([0, 90, 180])


def scenario_y_acute():
    return _spoke_network([90, 200, 340])


def scenario_5way():
    return _spoke_network([0, 72, 144, 216, 288])


def scenario_acute_30():
    """3-way with a sharp 30-degree wedge between two of the roads."""
    return _spoke_network([0, 30, 180], length=240.0)


def scenario_skewed_4way():
    return _spoke_network([10, 80, 195, 290])


def scenario_curved_roads():
    return _spoke_network([0, 90, 180, 270],
                           curve_offsets=[(0, 40), (40, 0), (0, -40), (-40, 0)])


def scenario_mixed_profiles():
    return _spoke_network([0, 90, 180, 270],
                           presets=["highway", "residential", "urban", "expressway"])


def scenario_two_intersections_and_dead_end():
    """Two 3-way intersections sharing a road, plus a dead-end stub (the
    dead end SHOULD get a circular cap; the intersections must not)."""
    net = RoadNetwork()
    a = net.add_node(-120.0, 0.0)
    b = net.add_node(120.0, 0.0)
    net.add_road(a.id, b.id)
    for node, angle in ((a, 135), (a, 225), (b, 45), (b, 315)):
        rad = math.radians(angle)
        outer = net.add_node(node.x + 150 * math.cos(rad), node.y + 150 * math.sin(rad))
        net.add_road(node.id, outer.id)
    # Dead-end stub off node b's north road end -- leave one isolated road.
    stub_a = net.add_node(0.0, -160.0)
    stub_b = net.add_node(0.0, -240.0)
    net.add_road(stub_a.id, stub_b.id)
    return net


SCENARIOS = [
    ("4way_cross", scenario_4way_cross),
    ("3way_t", scenario_3way_t),
    ("y_acute", scenario_y_acute),
    ("5way", scenario_5way),
    ("acute_30", scenario_acute_30),
    ("skewed_4way", scenario_skewed_4way),
    ("curved_roads", scenario_curved_roads),
    ("mixed_profiles", scenario_mixed_profiles),
    ("two_junctions_dead_end", scenario_two_intersections_and_dead_end),
]


# ----------------------------------------------------------------------
# Asphalt-circle detector: wraps pygame.draw.circle during the render and
# records every filled circle in the road-surface color.
# ----------------------------------------------------------------------

class CircleRecorder:
    def __init__(self):
        self.asphalt_circles = []  # [(center_screen, radius), ...]
        self._orig = pygame.draw.circle

    def __enter__(self):
        recorder = self

        def recording_circle(surface, color, center, radius, width=0, **kwargs):
            try:
                rgb = tuple(color)[:3]
            except TypeError:
                rgb = color
            if width == 0 and rgb == COLOR_ROAD_SURFACE:
                recorder.asphalt_circles.append((center, radius))
            return recorder._orig(surface, color, center, radius, width, **kwargs)

        pygame.draw.circle = recording_circle
        # The renderer module captured pygame at import; patching the
        # attribute on the shared pygame.draw module covers it too.
        return self

    def __exit__(self, *exc):
        pygame.draw.circle = self._orig
        return False


def render_scenario(name, net, surface, font):
    camera = Camera()
    camera.zoom = 1.2
    # Center the world origin-ish bounding box of all nodes on the canvas.
    xs = [n.x for n in net.nodes.values()]
    ys = [n.y for n in net.nodes.values()]
    cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    s = camera._scale()
    camera.offset_x = cx - (CANVAS_WIDTH / 2.0) / s
    camera.offset_y = cy - (CANVAS_HEIGHT / 2.0) / s

    renderer = RoadRenderer(surface, font, camera)

    with CircleRecorder() as rec:
        renderer.draw(net, None, None, None, False, None, None, None, None,
                       "select_tool", debug=False)

    # Every asphalt circle must be a dead-end cap: its screen position must
    # match a node with exactly ONE connected road. Any asphalt circle at an
    # intersection node (>= 3 roads) -- or anywhere else -- is a failure.
    failures = []
    for center, radius in rec.asphalt_circles:
        matched_dead_end = False
        for node in net.nodes.values():
            sx, sy = camera.world_to_screen(node.pos)
            if math.hypot(sx - center[0], sy - center[1]) < 2.0:
                n_roads = len(net.roads_for_node(node.id))
                if n_roads == 1:
                    matched_dead_end = True
                else:
                    failures.append(
                        f"asphalt circle (r={radius:.1f}px) drawn at node {node.id} "
                        f"with {n_roads} roads")
                break
        if not matched_dead_end and not failures:
            failures.append(f"asphalt circle (r={radius:.1f}px) at {center} "
                            f"matches no dead-end node")

    path = os.path.join(OUTPUT_DIR, f"{name}.png")
    pygame.image.save(surface, path)
    return path, rec.asphalt_circles, failures


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    pygame.init()
    pygame.display.set_mode((CANVAS_WIDTH, CANVAS_HEIGHT))
    font = pygame.font.SysFont("monospace", 13)
    surface = pygame.Surface((CANVAS_WIDTH, CANVAS_HEIGHT))

    all_failures = []
    for name, builder in SCENARIOS:
        net = builder()
        path, circles, failures = render_scenario(name, net, surface, font)
        n_intersections = sum(1 for nid in net.nodes if net.is_intersection(nid))
        status = "FAIL" if failures else "ok"
        print(f"[{status}] {name}: {n_intersections} intersection(s), "
              f"{len(circles)} asphalt circle(s) drawn -> {path}")
        for f in failures:
            print(f"       {f}")
        all_failures.extend((name, f) for f in failures)

    pygame.quit()
    if all_failures:
        print(f"\n{len(all_failures)} failure(s): circular asphalt at intersections detected.")
        sys.exit(1)
    print("\nAll scenarios passed: no circular asphalt patches at any intersection.")


if __name__ == "__main__":
    main()
