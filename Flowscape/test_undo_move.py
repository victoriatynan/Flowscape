"""
Drag-as-single-undo-step test.

A mouse drag mutates objects every frame for smooth visual feedback, but must
collapse into ONE undo step (Photoshop / level-editor behavior). These tests
drive the InputController through realistic down/motion/up sequences and assert
the undo history contains exactly one Move command per drag -- never one per
motion frame -- and that undo/redo, no-op clicks, and Escape all behave. Covers
nodes, road curve control points, and building footprints (same pattern, all
three share _begin_*_move/_commit_move/_cancel_move).
"""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from road_editor import InputController, RoadNetwork, Camera


class _UpEvent:
    """Minimal stand-in for a left-button MOUSEBUTTONUP event."""
    button = 1


def _make_controller():
    net = RoadNetwork()
    a = net.add_node(0.0, 0.0)
    b = net.add_node(100.0, 0.0)
    net.add_road(a.id, b.id)
    cam = Camera()  # zoom = 1.0
    return InputController(net, cam), net, a, b


def _drag_node(ctrl, node, path):
    """Grab `node` at its current pos and move it through `path` (a list of
    world points), finishing with a mouse-up. Mirrors how the main loop feeds
    motion events to the controller."""
    start = (node.x, node.y)
    ctrl._select_tool_left_down(start)
    for world_pos in path:
        ctrl._handle_mouse_motion(world_pos, (0, 0))
    ctrl._handle_mouse_up(_UpEvent(), path[-1] if path else start, (0, 0))


def _building_grab_point(building):
    """A point on the building's footprint that isn't also the entrance node
    (add_building_with_driveway places the entrance AT the footprint center,
    so a click dead-center would grab that node instead -- same node-before-
    building priority real clicks near a building's edge don't run into)."""
    return (building.x + 13, building.y)


def _drag_building(ctrl, building, path):
    """Same as _drag_node, but for a building footprint: grabs it from an
    off-center point on its footprint (see _building_grab_point) and drags
    through `path`."""
    ctrl._select_tool_left_down(_building_grab_point(building))
    for world_pos in path:
        ctrl._handle_mouse_motion(world_pos, (0, 0))
    ctrl._handle_mouse_up(_UpEvent(), path[-1] if path else _building_grab_point(building), (0, 0))


def test_drag_creates_exactly_one_command():
    ctrl, net, a, b = _make_controller()
    assert not ctrl.undo_stack.can_undo()

    # Drag node A through MANY intermediate frames.
    _drag_node(ctrl, a, [(10, 0), (20, 5), (33, 9), (40, 12), (50, 20)])

    assert len(ctrl.undo_stack._undo) == 1, "one drag must be one command"
    assert (a.x, a.y) == (50, 20)
    print("ok: many motion frames -> single command, final pos correct")


def test_undo_then_redo_round_trip():
    ctrl, net, a, b = _make_controller()
    _drag_node(ctrl, a, [(10, 0), (30, 10), (60, 25)])

    ctrl.undo()
    assert (a.x, a.y) == (0.0, 0.0), "undo restores original position"
    assert ctrl.undo_stack.can_redo()

    ctrl.redo()
    assert (a.x, a.y) == (60, 25), "redo reapplies the full drag"
    print("ok: undo restores start, redo reapplies end")


def test_click_without_movement_records_nothing():
    ctrl, net, a, b = _make_controller()
    # Press and release on the node with no motion in between.
    ctrl._select_tool_left_down((a.x, a.y))
    ctrl._handle_mouse_up(_UpEvent(), (a.x, a.y), (0, 0))

    assert not ctrl.undo_stack.can_undo(), "a click must not create history"
    assert (a.x, a.y) == (0.0, 0.0)
    print("ok: zero-movement click creates no command")


def test_escape_cancels_drag_and_reverts():
    ctrl, net, a, b = _make_controller()
    ctrl._select_tool_left_down((a.x, a.y))
    ctrl._handle_mouse_motion((40, 30), (0, 0))   # mid-drag
    assert (a.x, a.y) == (40, 30)

    # Escape aborts: revert to start, record nothing, and a trailing mouse-up
    # must not resurrect a command.
    ctrl._cancel_move()
    ctrl._handle_mouse_up(_UpEvent(), (40, 30), (0, 0))

    assert (a.x, a.y) == (0.0, 0.0), "cancel reverts to original"
    assert not ctrl.undo_stack.can_undo(), "cancel records nothing"
    print("ok: Escape reverts drag and records no command")


def test_control_point_drag_is_one_command():
    ctrl, net, a, b = _make_controller()
    road = net.roads[next(iter(net.roads))]
    ctrl.selected_road = road
    before = road.curve_offset

    cp = net.control_point_for_road(road)
    ctrl._select_tool_left_down(cp)  # grabs the control point
    assert ctrl.dragging_control_point
    for world_pos in [(50, 10), (50, 25), (50, 40)]:
        ctrl._handle_mouse_motion(world_pos, (0, 0))
    ctrl._handle_mouse_up(_UpEvent(), (50, 40), (0, 0))

    assert len(ctrl.undo_stack._undo) == 1, "curve drag -> one command"
    bent = road.curve_offset
    assert bent != before
    ctrl.undo()
    assert road.curve_offset == before, "undo restores the original curve"
    print("ok: control-point drag is a single, reversible command")


def test_new_drag_clears_redo_branch():
    ctrl, net, a, b = _make_controller()
    _drag_node(ctrl, a, [(10, 0), (40, 0)])
    ctrl.undo()
    assert ctrl.undo_stack.can_redo()

    # A fresh drag must discard the redo branch (linear history).
    _drag_node(ctrl, b, [(100, 10), (100, 40)])
    assert not ctrl.undo_stack.can_redo(), "new edit clears redo"
    print("ok: a new drag clears the redo branch")


def test_building_drag_creates_exactly_one_command():
    ctrl, net, a, b = _make_controller()
    building = net.add_building_with_driveway((0.0, -45.0), a.id, ctrl.active_building_type)

    _drag_building(ctrl, building, [(5, -40), (15, -30), (30, -20)])

    assert len(ctrl.undo_stack._undo) == 1, "one building drag must be one command"
    assert (building.x, building.y) == (30, -20)
    print("ok: building drag -> single command, final pos correct")


def test_building_click_without_movement_selects_it():
    ctrl, net, a, b = _make_controller()
    building = net.add_building_with_driveway((0.0, -45.0), a.id, ctrl.active_building_type)
    grab = _building_grab_point(building)

    ctrl._select_tool_left_down(grab)
    ctrl._handle_mouse_up(_UpEvent(), grab, (0, 0))

    assert not ctrl.undo_stack.can_undo(), "a click must not create history"
    assert ctrl.selected_building is building
    assert (building.x, building.y) == (0.0, -45.0)
    print("ok: zero-movement click on a building selects it, records nothing")


def test_building_drag_undo_redo_round_trip():
    ctrl, net, a, b = _make_controller()
    building = net.add_building_with_driveway((0.0, -45.0), a.id, ctrl.active_building_type)
    start = (building.x, building.y)

    _drag_building(ctrl, building, [(10, -40), (25, -30)])
    ctrl.undo()
    assert (building.x, building.y) == start, "undo restores original position"

    ctrl.redo()
    assert (building.x, building.y) == (25, -30), "redo reapplies the full drag"
    print("ok: building drag undo/redo round-trips")


def test_escape_cancels_building_drag_and_reverts():
    ctrl, net, a, b = _make_controller()
    building = net.add_building_with_driveway((0.0, -45.0), a.id, ctrl.active_building_type)
    start = (building.x, building.y)

    ctrl._select_tool_left_down(_building_grab_point(building))
    ctrl._handle_mouse_motion((40, -10), (0, 0))
    assert (building.x, building.y) == (40, -10)

    ctrl._cancel_move()
    ctrl._handle_mouse_up(_UpEvent(), (40, -10), (0, 0))

    assert (building.x, building.y) == start, "cancel reverts to original"
    assert not ctrl.undo_stack.can_undo(), "cancel records nothing"
    print("ok: Escape reverts a building drag and records no command")


if __name__ == "__main__":
    pygame.init()
    test_drag_creates_exactly_one_command()
    test_undo_then_redo_round_trip()
    test_click_without_movement_records_nothing()
    test_escape_cancels_drag_and_reverts()
    test_control_point_drag_is_one_command()
    test_new_drag_clears_redo_branch()
    test_building_drag_creates_exactly_one_command()
    test_building_click_without_movement_selects_it()
    test_building_drag_undo_redo_round_trip()
    test_escape_cancels_building_drag_and_reverts()
    print("\ndrag-undo: all tests passed")
