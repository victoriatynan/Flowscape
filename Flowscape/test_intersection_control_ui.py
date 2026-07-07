"""
Tests for editor-configurable intersection control + the reusable UI widgets.

Covers the full path: the Inspector reports an action -> the controller writes
node.data and rebuilds -> the factory instantiates the right controller; the
settings stepper; save/load persistence; and the generic widget behaviors
(dropdown disabled items, scroll clamping, confirm dialog) the framework rests
on.
"""

import os
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from road_editor import RoadNetwork, InputController, Camera
from map_data import save_map, load_map
from intersection_control import (StopSignController, ReservationController,
                                  IntersectionController, control_settings_schema,
                                  CONTROL_TYPE_ORDER, CONTROL_TYPE_IMPLEMENTED)
from inspector_panel import InspectorPanel
from ui_widgets import Dropdown, ScrollContainer, ConfirmDialog


def _four_way():
    """A network with one 4-road junction (center) + four dead-end spokes."""
    net = RoadNetwork()
    c = net.add_node(0, 0)
    for dx, dy in ((-100, 0), (100, 0), (0, -100), (0, 100)):
        s = net.add_node(dx, dy)
        net.add_road(c.id, s.id)
    return net, c


def _controller(net):
    return InputController(net, Camera())


def _font():
    pygame.font.init()
    return pygame.font.SysFont("monospace", 14)


def test_setting_control_type_rebuilds_the_right_controller():
    net, center = _four_way()
    ctrl = _controller(net)
    assert net.is_intersection(center.id)

    ctrl.set_node_control(center, "stop_sign")
    assert center.data["control"] == "stop_sign"
    assert isinstance(ctrl.traffic.intersections.controller_for(center.id),
                      StopSignController)

    ctrl.set_node_control(center, "reservation")
    assert isinstance(ctrl.traffic.intersections.controller_for(center.id),
                      ReservationController)

    ctrl.set_node_control(center, "uncontrolled")
    c = ctrl.traffic.intersections.controller_for(center.id)
    assert type(c) is IntersectionController
    print("ok: control type writes node.data and rebuilds via the factory")


def test_stop_duration_setting_applies():
    net, center = _four_way()
    ctrl = _controller(net)
    ctrl.set_node_control(center, "stop_sign")

    schema = control_settings_schema("stop_sign")
    assert [f.key for f in schema] == ["stop_duration"]

    ctrl.set_node_control_setting(center, "stop_duration", 4.5)
    controller = ctrl.traffic.intersections.controller_for(center.id)
    assert controller.stop_duration == 4.5
    print("ok: stop-duration setting flows to the live controller")


def test_control_config_round_trips_through_save_load():
    net, center = _four_way()
    center.data["control"] = "stop_sign"
    center.data["stop_duration"] = 3.5

    path = os.path.join(tempfile.mkdtemp(), "m.json")
    save_map(net, path)
    fresh = RoadNetwork()
    load_map(fresh, path)
    loaded = fresh.nodes[center.id]
    assert loaded.data.get("control") == "stop_sign"
    assert loaded.data.get("stop_duration") == 3.5
    print("ok: control type + settings persist with the map")


def test_inspector_reports_control_and_setting_actions():
    net, center = _four_way()
    surface = pygame.Surface((300, 700))
    font = _font()
    insp = InspectorPanel(font, font)
    viewport = pygame.Rect(0, 0, 280, 700)

    # First draw: lays out the Control Type dropdown box.
    insp.draw(surface, viewport, net, center)
    box_center = insp.control_dd._box.center
    assert insp.handle_click(box_center) == ("consumed", None)  # opens dropdown
    assert insp.control_dd.is_open

    # Redraw so the open popup's item rects exist, then pick "Stop Sign".
    insp.draw(surface, viewport, net, center)
    stop_rect = next(r for v, r, en in insp.control_dd._item_rects if v == "stop_sign")
    assert insp.handle_click(stop_rect.center) == ("set_control", "stop_sign")

    # With stop_sign active, the stepper's + button reports a clamped setting.
    center.data["control"] = "stop_sign"
    insp.draw(surface, viewport, net, center)
    plus = insp._steppers["stop_duration"]._plus
    action = insp.handle_click(plus.center)
    assert action[0] == "set_setting" and action[1] == "stop_duration"
    assert action[2] == 2.5            # default 2.0 + step 0.5
    print("ok: inspector reports control + setting actions from clicks")


def test_dropdown_skips_disabled_future_types():
    # Disabled (future) types are present but not selectable. Roundabout is
    # the one kind still genuinely unimplemented (traffic_light graduated to a
    # real controller -- see test_traffic_light.py).
    options = [(k, k, k in CONTROL_TYPE_IMPLEMENTED) for k in CONTROL_TYPE_ORDER]
    dd = Dropdown(options, "reservation")
    dd.is_open = True
    surface = pygame.Surface((200, 400))
    dd._box = pygame.Rect(0, 0, 160, 24)
    dd.draw_popup(surface, _font())

    rb_rect = next(r for v, r, en in dd._item_rects if v == "roundabout")
    assert dd.handle_click(rb_rect.center) == ("consumed", None)  # disabled -> ignored
    assert dd.value == "reservation" and dd.is_open                # unchanged, stays open
    ss_rect = next(r for v, r, en in dd._item_rects if v == "stop_sign")
    assert dd.handle_click(ss_rect.center) == ("select", "stop_sign")
    print("ok: dropdown refuses disabled types, accepts implemented ones")


def test_scroll_container_clamps():
    sc = ScrollContainer()
    surface = pygame.Surface((200, 200))
    vp = pygame.Rect(0, 0, 100, 100)
    sc.begin(surface, vp)
    sc.end(surface, 300)               # content 300 > viewport 100 -> max scroll 200
    assert sc.handle_wheel(-5)         # scroll down
    assert 0 < sc.scroll <= 200
    for _ in range(50):
        sc.handle_wheel(-5)
    assert sc.scroll == 200            # clamped at the bottom
    for _ in range(50):
        sc.handle_wheel(5)
    assert sc.scroll == 0              # clamped at the top
    # Content shorter than the viewport: nothing to scroll.
    sc.begin(surface, vp)
    sc.end(surface, 50)
    assert not sc.handle_wheel(-5)
    print("ok: scroll container clamps to [0, max] and no-ops when it fits")


def test_confirm_dialog_returns_outcomes_and_gates_action():
    surface = pygame.Surface((600, 400))
    font = _font()
    dlg = ConfirmDialog("Delete object", "Delete node 0?")
    dlg.draw(surface, surface.get_rect(), font, font)
    assert dlg.handle_click(dlg._confirm._rect.center) == "confirm"
    assert dlg.handle_click(dlg._cancel._rect.center) == "cancel"
    assert dlg.handle_click((1, 1)) is None        # outside buttons -> no-op (modal)

    # The controller runs the action only on confirm.
    net, center = _four_way()
    ctrl = _controller(net)
    ctrl.selected_node = center
    ctrl.request_delete_selected()
    assert ctrl.modal is not None
    ctrl.resolve_modal("cancel")
    assert center.id in net.nodes and ctrl.modal is None     # cancel kept it

    ctrl.selected_node = center
    ctrl.request_delete_selected()
    ctrl.resolve_modal("confirm")
    assert center.id not in net.nodes                         # confirm deleted it
    print("ok: confirm dialog gates the destructive action")


if __name__ == "__main__":
    pygame.init()
    test_setting_control_type_rebuilds_the_right_controller()
    test_stop_duration_setting_applies()
    test_control_config_round_trips_through_save_load()
    test_inspector_reports_control_and_setting_actions()
    test_dropdown_skips_disabled_future_types()
    test_scroll_container_clamps()
    test_confirm_dialog_returns_outcomes_and_gates_action()
    print("\nintersection-control UI: all tests passed")
