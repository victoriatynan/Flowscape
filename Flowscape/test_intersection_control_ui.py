"""
Editor-configurable intersection control tests.

Covers the full configuration path at the domain level: an edit writes
node.data -> IntersectionControl.rebuild() -> the factory instantiates the
right controller with its settings applied -- plus save/load persistence.
This is the exact sequence both editors perform (the web API's
/api/edit/node/{id}/control endpoint and, formerly, the pygame inspector).

(Re-based per WEB_MIGRATION_PLAN.md Phase 6: the pygame widget tests --
dropdown, scroll container, confirm dialog, inspector click-routing --
retired with the pygame UI. Their surface is now the schema-driven web
inspector, guarded by test_api_server.py's schema/validation tests and
browser verification; delete confirmation is client UX on top of the
undoable API.)
"""

import os
import tempfile

from intersection_control import (StopSignController, ReservationController,
                                  IntersectionController, control_settings_schema,
                                  CONTROL_TYPE_ORDER, CONTROL_TYPE_IMPLEMENTED)
from map_data import save_map, load_map
from road_network import RoadNetwork
from traffic_sim import TrafficSimulation


def _four_way():
    """A network with one 4-road junction (center) + four dead-end spokes."""
    net = RoadNetwork()
    c = net.add_node(0, 0)
    for dx, dy in ((-100, 0), (100, 0), (0, -100), (0, 100)):
        s = net.add_node(dx, dy)
        net.add_road(c.id, s.id)
    return net, c


def _set_control(sim, node, kind, **settings):
    """The configuration sequence every editor performs: write node.data,
    rebuild, and the factory re-instantiates the controller."""
    node.data["control"] = kind
    node.data.update(settings)
    sim.intersections.rebuild()


def test_setting_control_type_rebuilds_the_right_controller():
    net, center = _four_way()
    sim = TrafficSimulation(net)
    assert net.is_intersection(center.id)

    _set_control(sim, center, "stop_sign")
    assert center.data["control"] == "stop_sign"
    assert isinstance(sim.intersections.controller_for(center.id),
                      StopSignController)

    _set_control(sim, center, "reservation")
    assert isinstance(sim.intersections.controller_for(center.id),
                      ReservationController)

    _set_control(sim, center, "uncontrolled")
    c = sim.intersections.controller_for(center.id)
    assert type(c) is IntersectionController
    print("ok: control type writes node.data and rebuilds via the factory")


def test_stop_duration_setting_applies():
    net, center = _four_way()
    sim = TrafficSimulation(net)

    schema = control_settings_schema("stop_sign")
    assert [f.key for f in schema] == ["stop_duration"]

    _set_control(sim, center, "stop_sign", stop_duration=4.5)
    controller = sim.intersections.controller_for(center.id)
    assert controller.stop_duration == 4.5
    print("ok: stop-duration setting flows to the live controller")


def test_unimplemented_types_are_flagged():
    """The schema exposes which kinds are selectable; UIs (web inspector,
    formerly the pygame dropdown) disable the rest. Roundabout is the one
    kind still genuinely unimplemented."""
    assert "roundabout" in CONTROL_TYPE_ORDER
    assert "roundabout" not in CONTROL_TYPE_IMPLEMENTED
    assert "stop_sign" in CONTROL_TYPE_IMPLEMENTED
    print("ok: implemented/unimplemented control kinds are distinguishable")


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


if __name__ == "__main__":
    test_setting_control_type_rebuilds_the_right_controller()
    test_stop_duration_setting_applies()
    test_unimplemented_types_are_flagged()
    test_control_config_round_trips_through_save_load()
    print("\nintersection-control: all tests passed")
