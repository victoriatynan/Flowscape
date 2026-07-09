"""
Driveway tests (D1: driveways as narrow roads, model B).

Placing a building no longer attaches it straight onto a road node. Instead it
gets its own DRIVEWAY: an off-road entrance node plus a short, narrow driveway
road into the clicked node (which becomes a junction). Cars then originate at the
entrance -- off the main road -- and the existing routing / spawn / (default
reservation) merge carry them onto the network.

These tests assert the D1 contract:
  1. Placement creates the entrance node + narrow driveway road; the building
     connects to the entrance and remembers both parts.
  2. The clicked node becomes a real junction (driveway + through road(s)).
  3. A trip from the entrance routes onto the road and spawns OFF the main road.
  4. Deleting the building removes its driveway (entrance node cascades to the
     driveway road) with no orphans left behind.
"""

import math
import types

import road_style
from road_geometry import Road
from road_network import RoadNetwork
from traffic_sim import TrafficSimulation
from intersection_control import (YieldController, CONTROL_YIELD,
                                  CONTROLLER_TYPES, YIELD_GAP_FT)
from lane_graph import TURN_STRAIGHT, TURN_LEFT

BUILDING_PLACE_OFFSET = 45.0    # ft: footprint sits this far off its node
BUILDING_TYPE = "Large Apartment"


def _network_with_through_road():
    """A B C through road; return (network, node_b, node_c)."""
    net = RoadNetwork()
    a = net.add_node(0.0, 0.0)
    b = net.add_node(300.0, 0.0)
    c = net.add_node(600.0, 0.0)
    net.add_road(a.id, b.id)
    net.add_road(b.id, c.id)
    return net, b, c


def _place_building(net, node, click_pos, building_type=BUILDING_TYPE):
    """The placement law every editor applies (formerly the pygame Building
    tool, now the web client's ghost + POST): the footprint sits
    BUILDING_PLACE_OFFSET feet off the clicked node, toward the click side,
    and the building gets its model-B driveway into that node."""
    dx, dy = click_pos[0] - node.x, click_pos[1] - node.y
    dist = math.hypot(dx, dy)
    ux, uy = (0.0, -1.0) if dist < 1e-6 else (dx / dist, dy / dist)
    pos = (node.x + ux * BUILDING_PLACE_OFFSET,
           node.y + uy * BUILDING_PLACE_OFFSET)
    return net.add_building_with_driveway(pos, node.id,
                                          building_type=building_type)


def _delete_building(net, building):
    """The delete lifecycle both editors perform: the building goes, and
    each driveway entrance node goes with it (cascading to its road)."""
    net.remove_building(building.id)
    for dw in building.data.get("driveways", []):
        net.remove_node(dw["entrance"])


def test_placement_creates_a_narrow_driveway():
    net, b, c = _network_with_through_road()
    n0, r0, bld0 = len(net.nodes), len(net.roads), len(net.buildings)

    _place_building(net, b, (300.0, 6.0))   # click right beside node B

    assert len(net.nodes) == n0 + 1, "an off-road entrance node is created"
    assert len(net.roads) == r0 + 1, "a driveway road is created"
    assert len(net.buildings) == bld0 + 1

    building = list(net.buildings.values())[-1]
    dwys = building.data.get("driveways", [])
    assert len(dwys) == 1, "one driveway on a plain placement"
    ent, dwy = dwys[0]["entrance"], dwys[0]["road"]
    assert ent in net.nodes and dwy in net.roads, "building remembers its driveway parts"
    assert building.connection_node_ids == [ent], "building originates at the entrance node"

    driveway = net.roads[dwy]
    plain = Road(id=-1, start_node_id=0, end_node_id=1)
    assert driveway.width < plain.width
    assert (road_style.get_road_profile(driveway).total_width()
            < road_style.get_road_profile(plain).total_width()), "driveway is narrower"
    print("ok: placement creates an off-road entrance + narrow driveway road")


def test_clicked_node_becomes_a_junction():
    net, b, c = _network_with_through_road()
    assert len(net.roads_for_node(b.id)) == 2      # just the through road halves
    _place_building(net, b, (300.0, 6.0))
    assert len(net.roads_for_node(b.id)) == 3, (
        "the driveway makes the clicked node a junction (reservation-managed)")
    print("ok: the clicked node becomes a driveway junction")


def test_trip_originates_off_road_through_the_driveway():
    net, b, c = _network_with_through_road()
    _place_building(net, b, (300.0, 6.0))
    building = list(net.buildings.values())[-1]
    ent = building.data["driveways"][0]["entrance"]

    sim = TrafficSimulation(net)
    sim.prepare_routes()
    path = sim.resolve_route(ent, c.id)
    assert path is not None, "a car routes from the driveway onto the road"
    v = sim.spawn_on_route(path, dest_node_id=c.id)
    assert v is not None, "and spawns"
    # The main road runs along y = 0; the driveway spawn must be off it.
    assert abs(v.pos[1]) > 20.0, "the car spawns OFF the main road, at the building"
    print("ok: trips originate off-road via the driveway and merge onto the network")


def test_deleting_the_building_removes_its_driveway():
    net, b, c = _network_with_through_road()
    n0, r0, bld0 = len(net.nodes), len(net.roads), len(net.buildings)
    _place_building(net, b, (300.0, 6.0))
    building = list(net.buildings.values())[-1]
    ent = building.data["driveways"][0]["entrance"]
    dwy = building.data["driveways"][0]["road"]

    _delete_building(net, building)

    assert building.id not in net.buildings
    assert ent not in net.nodes, "the entrance node is removed"
    assert dwy not in net.roads, "the driveway road is removed (cascade)"
    assert (len(net.nodes), len(net.roads), len(net.buildings)) == (n0, r0, bld0), (
        "no orphans: back to the pre-placement counts")
    # The through road and its nodes survive.
    assert b.id in net.nodes and c.id in net.nodes
    print("ok: deleting a building removes exactly its driveway, no orphans")


def _approaching_vehicle(cur, nxt, turn, node_id, dist):
    """A minimal stand-in for a vehicle approaching `node_id`, whose movement is
    (cur -> nxt) classified `turn`, sitting `dist` feet from the junction."""
    v = types.SimpleNamespace()
    v.current_lane, v.next_lane = cur, nxt
    v.seg_index, v.seg_s, v.pos = 0, 0.0, (0.0, 0.0)
    v.segments = [{"kind": "lane", "length": dist},
                  {"kind": "connection", "node_id": node_id,
                   "lane_id": nxt, "turn_type": turn}]
    return v


def test_yield_gives_through_traffic_priority():
    assert CONTROLLER_TYPES.get(CONTROL_YIELD) is YieldController, "yield is registered"
    node = 9
    yc = YieldController(node)
    through = _approaching_vehicle(("mA", "F", 0), ("mC", "F", 0), TURN_STRAIGHT, node, 20.0)
    turn = _approaching_vehicle(("dw", "F", 0), ("mC", "F", 0), TURN_LEFT, node, 20.0)

    # Through car within the gap: it never yields; the turning driveway car does.
    yc.begin_step([through, turn], 0.1)
    assert yc._may_proceed(through), "through (straight) traffic never yields"
    assert not yc._may_proceed(turn), "the turning (driveway) car yields to it"

    # Through car beyond the gap: the driveway car may go.
    far = _approaching_vehicle(("mA", "F", 0), ("mC", "F", 0), TURN_STRAIGHT,
                               node, YIELD_GAP_FT + 30.0)
    yc.begin_step([far, turn], 0.1)
    assert yc._may_proceed(turn), "no priority traffic within the gap -> the driveway goes"
    print("ok: yield gives through-traffic priority; driveway waits for a gap")


def test_driveway_junction_is_yield_controlled():
    net, b, c = _network_with_through_road()
    _place_building(net, b, (300.0, 6.0))
    assert net.nodes[b.id].data.get("control") == CONTROL_YIELD, (
        "the driveway junction yields (through-traffic keeps priority)")
    print("ok: placing a driveway sets its junction to yield")


if __name__ == "__main__":
    test_placement_creates_a_narrow_driveway()
    test_clicked_node_becomes_a_junction()
    test_trip_originates_off_road_through_the_driveway()
    test_deleting_the_building_removes_its_driveway()
    test_yield_gives_through_traffic_priority()
    test_driveway_junction_is_yield_controlled()
    print("\ndriveways: all tests passed")
