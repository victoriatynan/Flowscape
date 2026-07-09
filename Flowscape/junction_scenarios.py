"""
Junction stress-test scenario networks (pure data; no rendering).

Shared by the geometry diagnostics (check_fillet_direction.py,
check_taper.py) and test_junction_surfaces.py. Extracted from the retired
pygame visual sweeps so the scenarios outlive the renderer: today the
junction surfaces they exercise are built by road_geometry.
build_node_surfaces() and inspected in the browser.
"""

import math

from road_network import RoadNetwork


def spoke_network(angles_deg, length=160.0, presets=None, curve_offsets=None):
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


def segment_network(segments):
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


def _two_intersections_and_dead_end():
    """Two 3-way intersections sharing a road, plus a dead-end stub (the
    dead end SHOULD get a circular cap; the intersections must not)."""
    net = RoadNetwork()
    a = net.add_node(-120.0, 0.0)
    b = net.add_node(120.0, 0.0)
    net.add_road(a.id, b.id)
    for node, angle in ((a, 135), (a, 225), (b, 45), (b, 315)):
        rad = math.radians(angle)
        outer = net.add_node(node.x + 150 * math.cos(rad),
                             node.y + 150 * math.sin(rad))
        net.add_road(node.id, outer.id)
    stub_a = net.add_node(0.0, -160.0)
    stub_b = net.add_node(0.0, -240.0)
    net.add_road(stub_a.id, stub_b.id)
    return net


# The core junction shapes (formerly test_intersections_visual.SCENARIOS).
SCENARIOS = [
    ("4way_cross", lambda: spoke_network([0, 90, 180, 270])),
    ("3way_t", lambda: spoke_network([0, 90, 180])),
    ("y_acute", lambda: spoke_network([90, 200, 340])),
    ("5way", lambda: spoke_network([0, 72, 144, 216, 288])),
    ("acute_30", lambda: spoke_network([0, 30, 180], length=240.0)),
    ("skewed_4way", lambda: spoke_network([10, 80, 195, 290])),
    ("curved_roads", lambda: spoke_network(
        [0, 90, 180, 270],
        curve_offsets=[(0, 40), (40, 0), (0, -40), (-40, 0)])),
    ("mixed_profiles", lambda: spoke_network(
        [0, 90, 180, 270],
        presets=["highway", "residential", "urban", "expressway"])),
    ("two_junctions_dead_end", _two_intersections_and_dead_end),
]

# Extra stress scenarios beyond the core set: very acute wedges, acute pairs
# combined with asymmetric profiles, near-parallel double pairs.
EXTRA = [
    ("acute_20", lambda: spoke_network([0, 20, 180], length=300.0)),
    ("acute_15", lambda: spoke_network([0, 15, 180], length=340.0)),
    ("acute_10", lambda: spoke_network([0, 10, 180], length=400.0)),
    ("acute_double_x", lambda: spoke_network([0, 15, 180, 195], length=340.0)),
    ("acute_15_mixed", lambda: spoke_network(
        [0, 15, 180], length=340.0,
        presets=["highway", "residential", "expressway"])),
    ("acute_4way_mixed", lambda: spoke_network(
        [0, 25, 120, 250], length=300.0,
        presets=["expressway", "residential", "urban", "highway"])),
    ("acute_5way_fan", lambda: spoke_network([0, 18, 36, 54, 200], length=380.0)),
    ("reflex_fan_340", lambda: spoke_network([0, 10, 20], length=420.0)),
    ("acute_curved", lambda: spoke_network(
        [0, 25, 180], length=300.0,
        curve_offsets=[(0, 60), (0, -60), (0, 0)])),
    ("acute_curved_in", lambda: spoke_network(
        [0, 25, 180], length=300.0,
        curve_offsets=[(0, -50), (0, 50), (0, 0)])),
]

# Width-transition (taper) scenarios: 2-road continuation nodes joining
# roads of different profile widths (formerly check_taper.SCENARIOS).
TAPER_SCENARIOS = [
    ("straight", lambda: segment_network([
        ((-220.0, 0.0), (0.0, 0.0), "highway", (0.0, 0.0)),
        ((0.0, 0.0), (220.0, 0.0), "residential", (0.0, 0.0)),
    ])),
    ("bent", lambda: segment_network([
        ((-220.0, 0.0), (0.0, 0.0), "highway", (0.0, 0.0)),
        ((0.0, 0.0), (170.0, 130.0), "residential", (0.0, 0.0)),
    ])),
    ("curved", lambda: segment_network([
        ((-220.0, 0.0), (0.0, 0.0), "expressway", (0.0, 40.0)),
        ((0.0, 0.0), (220.0, 0.0), "urban", (0.0, -40.0)),
    ])),
    ("narrow_between", lambda: segment_network([
        ((-260.0, 0.0), (-60.0, 0.0), "highway", (0.0, 0.0)),
        ((-60.0, 0.0), (60.0, 0.0), "residential", (0.0, 0.0)),
        ((60.0, 0.0), (260.0, 0.0), "expressway", (0.0, 0.0)),
    ])),
    ("hairpin", lambda: segment_network([
        ((-220.0, 0.0), (0.0, 0.0), "highway", (0.0, 0.0)),
        ((0.0, 0.0), (-200.0, 70.0), "residential", (0.0, 0.0)),
    ])),
    ("bend_90", lambda: segment_network([
        ((-220.0, 0.0), (0.0, 0.0), "highway", (0.0, 0.0)),
        ((0.0, 0.0), (10.0, 200.0), "residential", (0.0, 0.0)),
    ])),
]
