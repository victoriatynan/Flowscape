"""
Drag-as-single-undo-step test.

A mouse drag mutates objects every frame for smooth visual feedback, but must
collapse into ONE undo step (Photoshop / level-editor behavior). These tests
drive the InputController through realistic down/motion/up sequences and assert
the undo history contains exactly one Move command per drag -- never one per
motion frame -- and that undo/redo, no-op clicks, and Escape all behave.
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


if __name__ == "__main__":
    pygame.init()
    test_drag_creates_exactly_one_command()
    test_undo_then_redo_round_trip()
    test_click_without_movement_records_nothing()
    test_escape_cancels_drag_and_reverts()
    test_control_point_drag_is_one_command()
    test_new_drag_clears_redo_branch()
    print("\ndrag-undo: all tests passed")
