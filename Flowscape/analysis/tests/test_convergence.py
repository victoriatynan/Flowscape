"""
M4 convergence-track tests: the legacy /api/analysis endpoint now sources its
building mix and connectivity component membership from platform observations
(building_mix, connected_components) instead of recomputing them inline. These
tests prove:

  1. the two observations reproduce the exact values the endpoint used to compute
     inline, and
  2. the /api/analysis response is byte-identical to a faithful re-run of the
     original inline algorithm (the "byte-compatible" bar).
"""

from fastapi.testclient import TestClient

from api_server import create_app, WorldState
from road_network import RoadNetwork
from destinations import BUILDING_TYPES, RESIDENTIAL, CATEGORIES
from test_city import create_test_city

from analysis import analyze
from analysis.snapshot import StaticSource


def _client(net):
    world = WorldState(net)
    return TestClient(create_app(world)), world


# --- a verbatim copy of the pre-M4 inline algorithm, as the golden oracle ------

def _legacy_buildings_and_warnings(net):
    by_category = {c: 0 for c in CATEGORIES}
    population = 0
    jobs = 0
    for b in net.buildings.values():
        bt = BUILDING_TYPES.get(b.building_type)
        if bt is None:
            continue
        by_category[bt.category] = by_category.get(bt.category, 0) + 1
        if bt.category == RESIDENTIAL:
            population += bt.capacity
        else:
            jobs += bt.capacity

    parent = {nid: nid for nid in net.nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    roads = [r for r in net.roads.values() if not r.is_preview]
    for road in roads:
        if road.start_node_id in parent and road.end_node_id in parent:
            parent[find(road.start_node_id)] = find(road.end_node_id)
    components = {}
    for nid in net.nodes:
        components.setdefault(find(nid), set()).add(nid)
    main_component = max(components.values(), key=len) if components else set()

    warnings = []
    for b in net.buildings.values():
        attached = [n for n in b.connection_node_ids if n in net.nodes]
        if not attached:
            warnings.append(f"{b.building_type} {b.id} has no road connection")
        elif main_component and not any(n in main_component for n in attached):
            warnings.append(f"{b.building_type} {b.id} is disconnected "
                            f"from the main road network")
    non_residential = sum(v for c, v in by_category.items() if c != RESIDENTIAL)
    if by_category.get(RESIDENTIAL, 0) > 0 and non_residential == 0:
        warnings.append("Residential areas have no destinations "
                        "(add commercial/education/recreation buildings)")

    buildings = {"total": len(net.buildings), "by_category": by_category,
                 "population": population, "jobs": jobs}
    return buildings, warnings


# --- observation-level equivalence ---------------------------------------------

def test_building_mix_matches_legacy_rollup():
    net = create_test_city()
    result = analyze(StaticSource(net), only=("building_mix",))
    mix = result.observations["building_mix"].detail
    legacy_buildings, _ = _legacy_buildings_and_warnings(net)

    seeded = {c: 0 for c in CATEGORIES}
    seeded.update(mix["by_category"])
    assert seeded == legacy_buildings["by_category"]
    assert mix["population"] == legacy_buildings["population"]
    assert mix["jobs"] == legacy_buildings["jobs"]
    assert result.observations["building_mix"].value == legacy_buildings["total"]
    # The test city has residents and jobs; the roll-up is not trivially zero.
    assert mix["population"] > 0
    assert mix["jobs"] > 0


def test_connected_components_main_component_picks_largest():
    net = RoadNetwork()
    # Larger component a-b-c ...
    a = net.add_node(0.0, 0.0)
    b = net.add_node(50.0, 0.0)
    c = net.add_node(100.0, 0.0)
    net.add_road(a.id, b.id)
    net.add_road(b.id, c.id)
    # ... vs a smaller disjoint component d-e, plus an isolated node.
    d = net.add_node(0.0, 500.0)
    e = net.add_node(50.0, 500.0)
    net.add_road(d.id, e.id)
    net.add_node(999.0, 999.0)

    result = analyze(StaticSource(net), only=("connected_components",))
    main = set(result.observations["connected_components"].detail["main_component"])
    assert main == {a.id, b.id, c.id}
    # value keeps its road-touched semantics (two road components; isolated node
    # excluded).
    assert result.observations["connected_components"].value == 2


# --- endpoint byte-compatibility ------------------------------------------------

def test_api_analysis_byte_compatible_on_test_city():
    net = create_test_city()
    client, _ = _client(net)
    resp = client.get("/api/analysis")
    assert resp.status_code == 200
    body = resp.json()

    expected_buildings, expected_warnings = _legacy_buildings_and_warnings(net)
    assert body["buildings"] == expected_buildings
    assert body["warnings"] == expected_warnings
    # Category key order must match CATEGORIES (response-shape stability).
    assert list(body["buildings"]["by_category"]) == list(CATEGORIES)
    # Untouched sections still present and well-formed.
    assert set(body["demand"]) == {"daily_trips", "morning_peak_trips",
                                   "evening_peak_trips"}
    assert set(body["network"]) == {"roads", "nodes", "intersections",
                                    "lane_miles"}


def test_api_analysis_empty_network():
    client, _ = _client(RoadNetwork())
    body = client.get("/api/analysis").json()
    assert body["buildings"]["total"] == 0
    assert body["buildings"]["by_category"] == {c: 0 for c in CATEGORIES}
    assert body["warnings"] == []
