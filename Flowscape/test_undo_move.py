"""
Drag-as-single-undo-step test.

A drag mutates objects every frame for smooth visual feedback, but must
collapse into ONE undo step (Photoshop / level-editor behavior). That
invariant lives in undo_history.MoveTransaction: the UI (today the browser
client; formerly the pygame editor) grabs objects into a transaction,
mutates them freely during the drag, and commits exactly one MoveCommand
(or nothing) on release. These tests drive MoveTransaction/UndoStack
through realistic grab/mutate/commit sequences for nodes, road curve
control points, and building footprints -- no UI framework required.

(Re-based from the pygame InputController per WEB_MIGRATION_PLAN.md
Phase 6: the web client commits one API move per drag, guarded by
test_api_server.py; this file guards the underlying transaction law.)
"""

from road_network import RoadNetwork
from undo_history import MoveTransaction, UndoStack


def _network():
    net = RoadNetwork()
    a = net.add_node(0.0, 0.0)
    b = net.add_node(100.0, 0.0)
    net.add_road(a.id, b.id)
    return net, a, b


def _node_accessors(node):
    return (lambda: (node.x, node.y),
            lambda state: setattr(node, "x", state[0]) or setattr(node, "y", state[1]))


def _grab_node(node):
    txn = MoveTransaction()
    read, _ = _node_accessors(node)
    def write(state):
        node.x, node.y = state
    txn.add(lambda: (node.x, node.y), write)
    return txn


def _drag_node(stack, node, path):
    """Grab `node`, move it through `path` (mutating live each frame, as a
    UI does), then commit: at most one command lands on the stack."""
    txn = _grab_node(node)
    for x, y in path:
        node.x, node.y = x, y
    command = txn.build_command()
    if command is not None:
        stack.push(command)


def test_drag_creates_exactly_one_command():
    net, a, b = _network()
    stack = UndoStack()
    _drag_node(stack, a, [(10, 0), (20, 5), (33, 9), (40, 12), (50, 20)])
    assert len(stack._undo) == 1, "one drag must be one command"
    assert (a.x, a.y) == (50, 20)
    print("ok: many motion frames -> single command, final pos correct")


def test_undo_then_redo_round_trip():
    net, a, b = _network()
    stack = UndoStack()
    _drag_node(stack, a, [(10, 0), (30, 10), (60, 25)])

    stack.undo()
    assert (a.x, a.y) == (0.0, 0.0), "undo restores original position"
    assert stack.can_redo()

    stack.redo()
    assert (a.x, a.y) == (60, 25), "redo reapplies the full drag"
    print("ok: undo restores start, redo reapplies end")


def test_click_without_movement_records_nothing():
    net, a, b = _network()
    stack = UndoStack()
    _drag_node(stack, a, [])            # grab + release, no motion
    assert not stack.can_undo(), "a click must not create history"
    assert (a.x, a.y) == (0.0, 0.0)
    print("ok: zero-movement click creates no command")


def test_cancel_reverts_drag_and_records_nothing():
    net, a, b = _network()
    stack = UndoStack()
    txn = _grab_node(a)
    a.x, a.y = 40, 30                   # mid-drag
    assert (a.x, a.y) == (40, 30)

    txn.cancel()                        # Escape
    assert (a.x, a.y) == (0.0, 0.0), "cancel reverts to original"
    assert not stack.can_undo(), "cancel records nothing"
    print("ok: cancel reverts drag and records no command")


def test_control_point_drag_is_one_command():
    net, a, b = _network()
    stack = UndoStack()
    road = net.roads[next(iter(net.roads))]
    before = road.curve_offset

    txn = MoveTransaction()
    def write(offset):
        road.curve_offset = offset
    txn.add(lambda: road.curve_offset, write)
    for control in [(50, 10), (50, 25), (50, 40)]:
        net.set_curve_offset_from_control_point(road, control)
    stack.push(txn.build_command())

    assert len(stack._undo) == 1, "curve drag -> one command"
    bent = road.curve_offset
    assert bent != before
    stack.undo()
    assert road.curve_offset == before, "undo restores the original curve"
    stack.redo()
    assert road.curve_offset == bent, "redo restores the bent curve"
    print("ok: control-point drag is a single, reversible command")


def test_new_drag_clears_redo_branch():
    net, a, b = _network()
    stack = UndoStack()
    _drag_node(stack, a, [(10, 0), (40, 0)])
    stack.undo()
    assert stack.can_redo()

    _drag_node(stack, b, [(100, 10), (100, 40)])
    assert not stack.can_redo(), "new edit clears redo"
    print("ok: a new drag clears the redo branch")


def _building_network():
    net, a, b = _network()
    building = net.add_building_with_driveway((0.0, -45.0), a.id, "Small House")
    return net, a, b, building


def _drag_building(stack, building, path):
    txn = MoveTransaction()
    def write(state):
        building.x, building.y = state
    txn.add(lambda: (building.x, building.y), write)
    for x, y in path:
        building.x, building.y = x, y
    command = txn.build_command()
    if command is not None:
        stack.push(command)


def test_building_drag_creates_exactly_one_command():
    net, a, b, building = _building_network()
    stack = UndoStack()
    _drag_building(stack, building, [(5, -40), (15, -30), (30, -20)])
    assert len(stack._undo) == 1, "one building drag must be one command"
    assert (building.x, building.y) == (30, -20)
    print("ok: building drag -> single command, final pos correct")


def test_building_drag_undo_redo_round_trip():
    net, a, b, building = _building_network()
    stack = UndoStack()
    start = (building.x, building.y)

    _drag_building(stack, building, [(10, -40), (25, -30)])
    stack.undo()
    assert (building.x, building.y) == start, "undo restores original position"

    stack.redo()
    assert (building.x, building.y) == (25, -30), "redo reapplies the full drag"
    print("ok: building drag undo/redo round-trips")


def test_cancel_reverts_building_drag():
    net, a, b, building = _building_network()
    stack = UndoStack()
    start = (building.x, building.y)

    txn = MoveTransaction()
    def write(state):
        building.x, building.y = state
    txn.add(lambda: (building.x, building.y), write)
    building.x, building.y = 40, -10
    txn.cancel()

    assert (building.x, building.y) == start, "cancel reverts to original"
    assert not stack.can_undo(), "cancel records nothing"
    print("ok: cancel reverts a building drag and records no command")


if __name__ == "__main__":
    test_drag_creates_exactly_one_command()
    test_undo_then_redo_round_trip()
    test_click_without_movement_records_nothing()
    test_cancel_reverts_drag_and_records_nothing()
    test_control_point_drag_is_one_command()
    test_new_drag_clears_redo_branch()
    test_building_drag_creates_exactly_one_command()
    test_building_drag_undo_redo_round_trip()
    test_cancel_reverts_building_drag()
    print("\ndrag-undo: all tests passed")
