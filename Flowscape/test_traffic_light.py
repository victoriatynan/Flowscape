"""
Traffic light tests (TL-a: axis-based 2-phase signal).

TrafficLightController is a POLICY layer on top of ReservationController, same
shape as stop signs and yields: it decides WHEN a movement may be attempted (is
its approach's phase green right now?) and delegates the actual conflict
exclusion to the unchanged reservation base, so a wrong phase assignment can
only make traffic wait longer, never cause a crash.

These tests cover:
  1. Registration (traffic_light is no longer a disabled placeholder).
  2. Axis-based phase assignment from real junction geometry (opposite
     approaches share a phase).
  3. The phase clock: green -> yellow -> all-red -> next phase's green, gating
     can_enter()/would_permit() correctly at each state.
  4. TL-c: geometry-aware movements_conflict -- opposing through traffic and
     opposing turns flow concurrently; a permissive left yields to the
     opposing through movement; a stale cross-axis reservation still conflicts
     (safety fallback).
  5. Editor integration: selecting "traffic_light" rebuilds the right
     controller and its settings apply, exactly like stop sign / yield.
  6. Placeholder signal-head art (tools/make_placeholder_traffic_light_icons.py)
     renders as a rotated sprite per approach, falling back to a plain colored
     circle if the art is ever missing.
"""

import os
import types

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from road_editor import RoadNetwork, InputController, Camera
from intersection_control import (TrafficLightController, CONTROL_TRAFFIC_LIGHT,
                                  CONTROLLER_TYPES, control_settings_schema,
                                  TL_GREEN, TL_YELLOW, TL_ALL_RED, TL_STATE_COLORS,
                                  TL_ICON_PATHS, Movement)
from lane_graph import TURN_STRAIGHT, TURN_LEFT


def _four_way():
    """A network with one 4-road junction (center) + four dead-end spokes,
    returning (network, center_node, {direction: road}) so axis pairing can
    be asserted directly against real geometry."""
    net = RoadNetwork()
    c = net.add_node(0, 0)
    roads = {}
    for direction, (dx, dy) in (("W", (-100, 0)), ("E", (100, 0)),
                                ("S", (0, -100)), ("N", (0, 100))):
        s = net.add_node(dx, dy)
        roads[direction] = net.add_road(c.id, s.id)
    return net, c, roads


def _approaching_vehicle(cur, nxt, node_id, dist=20.0):
    """A minimal stand-in for a vehicle approaching `node_id`, whose movement
    is (cur -> nxt), straight-classified, sitting `dist` feet from the line."""
    v = types.SimpleNamespace()
    v.current_lane, v.next_lane = cur, nxt
    v.seg_index, v.seg_s, v.pos = 0, 0.0, (0.0, 0.0)
    v.segments = [{"kind": "lane", "length": dist},
                  {"kind": "connection", "node_id": node_id,
                   "lane_id": nxt, "turn_type": TURN_STRAIGHT}]
    return v


def test_traffic_light_is_registered():
    assert CONTROLLER_TYPES.get(CONTROL_TRAFFIC_LIGHT) is TrafficLightController
    schema = control_settings_schema(CONTROL_TRAFFIC_LIGHT)
    assert [f.key for f in schema] == [
        "cycle_length", "green_duration", "yellow_duration",
        "all_red_duration", "initial_phase",
    ]
    print("ok: traffic_light is registered with its settings schema")


def test_axis_phase_groups_pair_opposite_roads():
    net, c, roads = _four_way()
    tl = TrafficLightController(c.id, net)

    n_phase = tl._road_phase[roads["N"].id]
    s_phase = tl._road_phase[roads["S"].id]
    e_phase = tl._road_phase[roads["E"].id]
    w_phase = tl._road_phase[roads["W"].id]

    assert n_phase == s_phase, "N-S share a phase (opposite approaches)"
    assert e_phase == w_phase, "E-W share a phase (opposite approaches)"
    assert n_phase != e_phase, "the two axes are different phases"
    print("ok: axis grouping pairs opposite approaches from real geometry")


def test_phase_cycles_through_green_yellow_all_red():
    net, c, roads = _four_way()
    tl = TrafficLightController(c.id, net, green_duration=1.0,
                                yellow_duration=0.5, all_red_duration=0.5,
                                initial_phase=0)
    ns = _approaching_vehicle(("mN", "F", 0), ("mS", "F", 0), c.id)
    ew = _approaching_vehicle(("mE", "F", 0), ("mW", "F", 0), c.id)
    ns.current_lane = (roads["N"].id, "F", 0)
    ew.current_lane = (roads["E"].id, "F", 0)

    # Phase 0 is whichever axis the geometry assigned index 0 to.
    phase0_road = next(d for d in ("N", "E") if tl._road_phase[roads[d].id] == 0)
    green_vehicle = ns if phase0_road == "N" else ew
    red_vehicle = ew if phase0_road == "N" else ns

    tl.begin_step([], 0.01)   # resolves initial_phase, starts green
    assert tl._state == TL_GREEN
    assert tl.would_permit(green_vehicle), "phase-0 axis is green"
    assert not tl.would_permit(red_vehicle), "the other axis is red"
    assert not tl.can_enter(red_vehicle)
    assert tl.can_enter(green_vehicle)

    tl.begin_step([], 1.0)    # advance past green_duration -> yellow
    assert tl._state == TL_YELLOW
    assert not tl.would_permit(green_vehicle), "yellow denies new entries"
    assert not tl.would_permit(red_vehicle)

    tl.begin_step([], 0.5)    # advance past yellow_duration -> all-red
    assert tl._state == TL_ALL_RED
    assert not tl.would_permit(green_vehicle)
    assert not tl.would_permit(red_vehicle)

    tl.begin_step([], 0.5)    # advance past all_red_duration -> next phase green
    assert tl._state == TL_GREEN
    assert tl.would_permit(red_vehicle), "the other axis is green now"
    assert not tl.would_permit(green_vehicle), "the first axis is red now"
    print("ok: phase clock cycles green -> yellow -> all-red -> next green")


def test_movements_conflict_is_geometry_aware():
    net, c, roads = _four_way()
    tl = TrafficLightController(c.id, net)

    n_straight = Movement((roads["N"].id, "F", 0), ("out", "F", 0), TURN_STRAIGHT)
    s_straight = Movement((roads["S"].id, "F", 0), ("out", "F", 0), TURN_STRAIGHT)
    assert not tl.movements_conflict(n_straight, s_straight), (
        "opposing through traffic (same axis) passes side by side")

    n_left = Movement((roads["N"].id, "F", 0), ("outW", "F", 0), TURN_LEFT)
    assert tl.movements_conflict(n_left, s_straight), (
        "a permissive left crosses the opposing lane -- must yield")

    s_left = Movement((roads["S"].id, "F", 0), ("outE", "F", 0), TURN_LEFT)
    assert not tl.movements_conflict(n_left, s_left), (
        "opposing left turns curve away from each other")

    n_left_lane2 = Movement((roads["N"].id, "F", 1), ("outW", "F", 0), TURN_LEFT)
    assert not tl.movements_conflict(n_straight, n_left_lane2), (
        "lanes fanning out of the SAME approach never cross")

    e_straight = Movement((roads["E"].id, "F", 0), ("out", "F", 0), TURN_STRAIGHT)
    assert tl.movements_conflict(n_straight, e_straight), (
        "different axes always conflict -- safety fallback for a stale "
        "reservation still clearing when the phase flips")
    print("ok: movements_conflict is geometry-aware: permissive lefts yield, "
          "opposing through/turns flow concurrently, cross-axis stays conservative")


def test_visual_layers_show_a_lamp_per_approach():
    net, c, roads = _four_way()
    tl = TrafficLightController(c.id, net, green_duration=1.0,
                                yellow_duration=0.5, all_red_duration=0.5,
                                initial_phase=0)
    tl.begin_step([], 0.01)

    # The placeholder icons (tools/make_placeholder_traffic_light_icons.py)
    # exist, so lamps render as rotated sprites, not plain circles.
    layers = tl.visual_layers(net)
    lamps = [l for l in layers if l["shape"] == "sprite"]
    assert len(lamps) == 4, "one lamp per approach road"

    phase0_road = next(d for d in ("N", "E") if tl._road_phase[roads[d].id] == 0)
    phase1_road = "E" if phase0_road == "N" else "N"
    # Lamps are placed just beyond the junction, back along each road's own
    # direction, so a phase-0 approach's lamp sits closer to that road's far
    # node than any other lamp -- find it by nearest position instead of
    # depending on layer order.
    def lamp_near(road_dir):
        rx, ry = net.nodes[roads[road_dir].end_node_id].pos
        return min(lamps, key=lambda l: (l["pos"][0] - rx) ** 2 + (l["pos"][1] - ry) ** 2)

    assert lamp_near(phase0_road)["image"] == TL_ICON_PATHS[TL_GREEN]
    assert lamp_near(phase1_road)["image"] == TL_ICON_PATHS[TL_ALL_RED]

    tl.begin_step([], 1.0)   # -> yellow
    layers = tl.visual_layers(net)
    lamps = [l for l in layers if l["shape"] == "sprite"]
    assert lamp_near(phase0_road)["image"] == TL_ICON_PATHS[TL_YELLOW]
    print("ok: one signal-head sprite lamp per approach, colored by its own phase state")


def test_visual_layers_fall_back_to_a_plain_circle_without_art():
    # Graceful degradation, same convention as get_icon()/vehicle_sprite_path():
    # missing art falls back to a plain colored marker, never an error.
    net, c, roads = _four_way()
    tl = TrafficLightController(c.id, net, green_duration=1.0)
    tl.begin_step([], 0.01)

    real_paths = dict(TL_ICON_PATHS)
    TL_ICON_PATHS.update({k: "/no/such/file.png" for k in TL_ICON_PATHS})
    try:
        layers = tl.visual_layers(net)
    finally:
        TL_ICON_PATHS.update(real_paths)

    lamps = [l for l in layers if l["shape"] == "circle" and l.get("radius") == 5.0]
    assert len(lamps) == 4, "falls back to a plain circle lamp per approach"
    print("ok: missing signal-head art falls back to a plain colored circle")


def test_setting_control_type_rebuilds_traffic_light():
    net, c, roads = _four_way()
    ctrl = InputController(net, Camera())
    ctrl.set_node_control(c, CONTROL_TRAFFIC_LIGHT)

    tl = ctrl.traffic.intersections.controller_for(c.id)
    assert isinstance(tl, TrafficLightController)

    ctrl.set_node_control_setting(c, "green_duration", 40.0)
    tl = ctrl.traffic.intersections.controller_for(c.id)
    assert tl.green_duration == 40.0

    ctrl.set_node_control_setting(c, "initial_phase", 1)
    tl = ctrl.traffic.intersections.controller_for(c.id)
    tl.begin_step([], 0.01)   # resolves the (rebuilt controller's) initial_phase
    assert tl._phase == 1, "initial_phase setting reaches the live controller"
    print("ok: selecting Traffic Light in the editor rebuilds it, settings apply")


if __name__ == "__main__":
    test_traffic_light_is_registered()
    test_axis_phase_groups_pair_opposite_roads()
    test_phase_cycles_through_green_yellow_all_red()
    test_movements_conflict_is_geometry_aware()
    test_visual_layers_show_a_lamp_per_approach()
    test_visual_layers_fall_back_to_a_plain_circle_without_art()
    test_setting_control_type_rebuilds_traffic_light()
    print("\ntraffic light: all tests passed")
