"""
Web API guards (WEB_MIGRATION_PLAN.md Phase 3).

Exercises the FastAPI server end-to-end through TestClient (in-process ASGI,
no network, no browser) and holds it to the plan's invariants:

  - NO PYGAME: the whole API stack imports and serves without pygame.
  - BACKEND AUTHORITY: every edit happens server-side, is undoable, and
    stops a running simulation (whose cached routes would dangle).
  - DETERMINISM: ticking the sim through the API gives exactly the state a
    direct SimulationSession produces for the same map and tick count.
  - SCHEMA-DRIVEN UI: control/building schemas are served, and control
    edits are validated against the schema server-side.

Plain asserts, runnable directly: python test_api_server.py
"""

import json
import os
import sys

from fastapi.testclient import TestClient

from api_server import create_app, WorldState
from map_data import MAPS_DIR, map_to_dict
from sim_session import SimulationSession
from test_city import create_test_city


def _client(network=None):
    world = WorldState(network)
    app = create_app(world)
    return TestClient(app), world


def _jsonable(obj):
    """Normalize tuples/int-keys the way JSON transport does, so direct
    snapshots compare equal to API responses."""
    return json.loads(json.dumps(obj))


def test_no_pygame_in_api_stack():
    client, world = _client(create_test_city())
    with client:
        assert client.get("/api/health").json()["status"] == "ok"
        assert client.get("/api/map").status_code == 200
        assert client.get("/api/geometry").status_code == 200
    assert "pygame" not in sys.modules, \
        "pygame was imported somewhere in the API stack"
    print("ok: API serves map + geometry with pygame never imported")


def test_map_roundtrip():
    client_a, world_a = _client(create_test_city())
    client_b, world_b = _client()          # starts empty
    with client_a, client_b:
        exported = client_a.get("/api/map").json()
        assert exported["buildings"], "test city should have buildings"
        put = client_b.put("/api/map", json=exported)
        assert put.status_code == 200
        assert put.json()["warnings"] == []
        assert client_b.get("/api/map").json() == exported
    print("ok: map exports and reimports identically over the API")


def test_edits_are_undoable():
    client, world = _client()
    with client:
        n1 = client.post("/api/edit/node", json={"x": 0, "y": 0}).json()["node"]
        n2 = client.post("/api/edit/node", json={"x": 300, "y": 0}).json()["node"]
        r = client.post("/api/edit/road", json={
            "start_node_id": n1["id"], "end_node_id": n2["id"]}).json()["road"]
        assert client.post(f"/api/edit/node/{n1['id']}/move",
                           json={"x": 50, "y": 25}).json()["ok"]
        snap_after = map_to_dict(world.network)

        # Walk all the way back: move, road, node, node.
        for _ in range(4):
            assert client.post("/api/edit/undo").json()["ok"]
        assert client.post("/api/edit/undo").json()["ok"] is False
        assert world.network.nodes == {} and world.network.roads == {}

        # And forward again to the exact same world.
        for _ in range(4):
            assert client.post("/api/edit/redo").json()["ok"]
        assert map_to_dict(world.network) == snap_after
        assert world.network.nodes[n1["id"]].pos == (50, 25)
        assert r["id"] in world.network.roads
    print("ok: node/road/move edits undo and redo exactly")


def test_delete_node_cascades_and_restores():
    client, world = _client(create_test_city())
    with client:
        before = map_to_dict(world.network)
        # Pick a node with several roads (a grid intersection).
        nid = max(world.network.nodes,
                  key=lambda n: len(world.network.roads_for_node(n)))
        removed = client.delete(f"/api/edit/node/{nid}").json()
        assert removed["ok"] and len(removed["removed_roads"]) >= 2
        assert nid not in world.network.nodes
        for rid in removed["removed_roads"]:
            assert rid not in world.network.roads
        assert client.post("/api/edit/undo").json()["ok"]
        assert map_to_dict(world.network) == before
    print("ok: node delete cascades roads/building links and undoes exactly")


def test_building_lifecycle_with_driveway():
    client, world = _client()
    with client:
        n1 = client.post("/api/edit/node", json={"x": 0, "y": 0}).json()["node"]
        n2 = client.post("/api/edit/node", json={"x": 300, "y": 0}).json()["node"]
        client.post("/api/edit/road", json={"start_node_id": n1["id"],
                                            "end_node_id": n2["id"]})
        b = client.post("/api/edit/building", json={
            "x": 40, "y": 60, "main_node_id": n1["id"],
            "building_type": "Small House"}).json()["building"]
        # Model B: entrance node + driveway road exist; main node now yields.
        assert b["entrance_node_id"] in world.network.nodes
        assert b["driveway_road_id"] in world.network.roads
        assert world.network.nodes[n1["id"]].data["control"] == "yield"
        with_building = map_to_dict(world.network)

        deleted = client.delete(f"/api/edit/building/{b['id']}").json()
        assert deleted["removed_nodes"] == [b["entrance_node_id"]]
        assert deleted["removed_roads"] == [b["driveway_road_id"]]
        assert client.post("/api/edit/undo").json()["ok"]     # delete undone
        assert map_to_dict(world.network) == with_building
        assert client.post("/api/edit/undo").json()["ok"]     # create undone
        assert world.network.buildings == {}
        assert b["entrance_node_id"] not in world.network.nodes
        assert "control" not in (world.network.nodes[n1["id"]].data or {})

        bad = client.post("/api/edit/building", json={
            "x": 0, "y": 0, "main_node_id": n1["id"],
            "building_type": "Nonsense Tower"})
        assert bad.status_code == 400
    print("ok: building+driveway create/delete/undo track the editor lifecycle")


def test_continuous_road_drawing_is_one_undo():
    """Road tool into empty space: the backend creates the endpoint node +
    road as ONE compound command, so a single undo removes both."""
    client, world = _client()
    with client:
        n1 = client.post("/api/edit/node", json={"x": 0, "y": 0}).json()["node"]
        resp = client.post("/api/edit/road", json={
            "start_node_id": n1["id"], "end_pos": [300.0, 40.0]}).json()
        created = resp["created_node"]
        assert created is not None and (created["x"], created["y"]) == (300.0, 40.0)
        assert resp["road"]["end_node_id"] == created["id"]
        assert created["id"] in world.network.nodes
        assert resp["road"]["id"] in world.network.roads

        assert client.post("/api/edit/undo").json()["ok"]
        assert created["id"] not in world.network.nodes, "one undo removes the node"
        assert resp["road"]["id"] not in world.network.roads, "...and the road"
        assert client.post("/api/edit/redo").json()["ok"]
        assert created["id"] in world.network.nodes
        assert resp["road"]["id"] in world.network.roads

        # Exactly one endpoint form is required.
        assert client.post("/api/edit/road", json={
            "start_node_id": n1["id"]}).status_code == 400
        assert client.post("/api/edit/road", json={
            "start_node_id": n1["id"], "end_node_id": created["id"],
            "end_pos": [1, 1]}).status_code == 400
    print("ok: drawing a road into empty space is one compound undo step")


def test_road_curve_and_profile_edits():
    client, world = _client()
    with client:
        n1 = client.post("/api/edit/node", json={"x": 0, "y": 0}).json()["node"]
        n2 = client.post("/api/edit/node", json={"x": 300, "y": 0}).json()["node"]
        rid = client.post("/api/edit/road", json={
            "start_node_id": n1["id"], "end_node_id": n2["id"]}).json()["road"]["id"]

        # Curve: drop the control point at (150, 80) -> offset (0, 80) from
        # the chord midpoint, echoed back in the geometry payload.
        resp = client.post(f"/api/edit/road/{rid}/curve",
                           json={"control_x": 150, "control_y": 80}).json()
        assert resp["curve_offset"] == [0.0, 80.0]
        geo = client.get("/api/geometry").json()
        road_geo = next(g for g in geo["roads"] if g["id"] == rid)
        assert road_geo["control_point"] == [150.0, 80.0]

        # Profile: switch to highway + 3 forward lanes; lanes served update.
        client.post(f"/api/edit/road/{rid}/profile",
                    json={"preset": "highway", "lane_count_forward": 3})
        assert world.network.roads[rid].data["profile"] == {
            "preset": "highway", "lane_count_forward": 3}
        geo = client.get("/api/geometry").json()
        road_geo = next(g for g in geo["roads"] if g["id"] == rid)
        assert road_geo["lanes_forward"] == 3
        assert road_geo["lanes_reverse"] == 2      # highway preset default
        assert road_geo["profile_data"]["preset"] == "highway"
        # Multi-lane: same-direction separators are DASHED (many short
        # cream runs), so the marking count grows well past the boundary
        # count -- and dashes sit between lanes, never through their centers.
        assert len(road_geo["markings"]) > 6

        # Both edits undo cleanly (profile first, then curve).
        client.post("/api/edit/undo")
        assert (world.network.roads[rid].data or {}).get("profile") is None
        client.post("/api/edit/undo")
        assert tuple(world.network.roads[rid].curve_offset) == (0.0, 0.0)

        assert client.post(f"/api/edit/road/{rid}/profile",
                           json={"preset": "hoverlane"}).status_code == 400
        presets = client.get("/api/schema/road-presets").json()
        assert "highway" in presets["order"]
        assert presets["presets"]["driveway"]["lane_width"] == 5.0
    print("ok: road curve + profile edits are applied, served, and undoable")


def test_api_tick_matches_direct_session():
    client, world = _client(create_test_city())
    with client:
        start = client.post("/api/sim/start", json={"paused": True})
        assert start.status_code == 200 and start.json()["paused"]
        api_snap = client.post("/api/sim/tick", json={"ticks": 600}).json()

    direct = SimulationSession(create_test_city())
    direct.run(600)
    expected = _jsonable(direct.snapshot())
    assert api_snap == expected
    assert api_snap["released"] > 0 or api_snap["tick"] == 600
    print("ok: 600 API ticks == 600 direct SimulationSession ticks")


def test_edit_stops_running_sim():
    client, world = _client(create_test_city())
    with client:
        client.post("/api/sim/start", json={"paused": True})
        assert client.get("/api/sim/state").json()["running"]
        client.post("/api/edit/node", json={"x": 9999, "y": 9999})
        assert client.get("/api/sim/state").json() == {"running": False}
        # And sim control on a stopped sim answers 409, not a crash.
        assert client.post("/api/sim/pause").status_code == 409
        assert client.post("/api/sim/tick", json={"ticks": 1}).status_code == 409
    print("ok: any edit stops the running sim (no dangling routes)")


def test_sim_start_requires_buildings():
    client, world = _client()      # empty network
    with client:
        resp = client.post("/api/sim/start", json={})
        assert resp.status_code == 400
    print("ok: starting the sim on a building-less map is a 400")


def test_schemas_and_control_validation():
    client, world = _client()
    with client:
        ctrl = client.get("/api/schema/intersection-control").json()
        assert "stop_sign" in ctrl["implemented"]
        keys = [s["key"] for s in ctrl["settings"]["stop_sign"]]
        assert keys == ["stop_duration"]

        bts = client.get("/api/schema/building-types").json()
        assert bts["order"][0] == "Small House"
        assert bts["types"]["High School"]["capacity"] > 0

        nid = client.post("/api/edit/node",
                          json={"x": 0, "y": 0}).json()["node"]["id"]
        ok = client.post(f"/api/edit/node/{nid}/control", json={
            "control": "stop_sign", "settings": {"stop_duration": 2.0}})
        assert ok.status_code == 200
        assert world.network.nodes[nid].data["stop_duration"] == 2.0
        bad_kind = client.post(f"/api/edit/node/{nid}/control",
                               json={"control": "hovercraft"})
        assert bad_kind.status_code == 400
        bad_key = client.post(f"/api/edit/node/{nid}/control", json={
            "control": "stop_sign", "settings": {"warp_factor": 9}})
        assert bad_key.status_code == 400
        assert client.post("/api/edit/undo").json()["ok"]
        assert "control" not in (world.network.nodes[nid].data or {})
    print("ok: schemas served; control edits validated and undoable")


def test_geometry_endpoint_shape():
    client, world = _client(create_test_city())
    with client:
        geo = client.get("/api/geometry").json()
    assert geo["roads"] and geo["nodes"] and geo["buildings"] and geo["lanes"]
    road = geo["roads"][0]
    assert len(road["centerline"]) >= 2 and len(road["polygon"]) >= 4
    assert road["total_width"] > 0
    lane = geo["lanes"][0]
    assert len(lane["lane_id"]) == 3 and len(lane["points"]) >= 2
    b = geo["buildings"][0]
    assert b["size_ft"] > 0 and b["connection_node_ids"]

    # Junction surfaces: the grid's 3+/4-way nodes must arrive as polygons
    # with fillet edge-line curves; driveway junctions raise the count well
    # past the bare 4-way interior. Dead-end driveway entrances become caps.
    assert geo["junctions"], "test city must produce junction surfaces"
    kinds = {j["kind"] for j in geo["junctions"]}
    assert "junction" in kinds
    j = next(j for j in geo["junctions"] if j["kind"] == "junction")
    assert len(j["polygon"]) >= 6 and j["mouth_width"] > 0
    assert j["edge_lines"] and j["edge_lines"][0]["color"].startswith("#")
    assert geo["caps"] and all(c["radius"] > 0 for c in geo["caps"])

    # Lane markings come from the profile's boundary layout: the default
    # urban profile paints an amber center boundary + cream edge lines,
    # and never a divider through a lane center.
    marked = [r for r in geo["roads"] if r["markings"]]
    assert marked, "roads must serve lane markings"
    r = marked[0]
    colors = {m["color"] for m in r["markings"]}
    assert "#efac28" in colors, "center boundary (amber) missing"
    assert "#efd8a1" in colors, "edge lines (cream) missing"
    assert r["marking_width"] > 0

    # Trimmed mouths: roads meeting a junction-surface node stop SHORT of
    # it — no served centerline endpoint may sit on such a node (the
    # junction polygon bridges the gap).
    import math
    surface_pos = [(n["x"], n["y"]) for n in geo["nodes"]
                   if n["id"] in {j["node_id"] for j in geo["junctions"]}]
    for r in geo["roads"]:
        for end in (r["centerline"][0], r["centerline"][-1]):
            for nx, ny in surface_pos:
                assert math.hypot(end[0] - nx, end[1] - ny) > 0.5, \
                    f"road {r['id']} centerline still touches a surface node"
    print("ok: geometry endpoint serves trimmed roads + junction surfaces + caps")


def test_map_files_save_load_jailed():
    client, world = _client(create_test_city())
    fname = "test_api_tmp_map.json"
    path = os.path.join(MAPS_DIR, fname)
    try:
        with client:
            saved = client.post("/api/map/save",
                                json={"filename": "../" + fname}).json()
            assert saved["filename"] == fname      # jailed to MAPS_DIR
            assert fname in client.get("/api/map/files").json()["files"]
            exported = client.get("/api/map").json()
            loaded = client.post("/api/map/load", json={"filename": fname})
            assert loaded.status_code == 200
            assert client.get("/api/map").json() == exported
            missing = client.post("/api/map/load",
                                  json={"filename": "does_not_exist"})
            assert missing.status_code == 404
    finally:
        if os.path.isfile(path):
            os.remove(path)
    print("ok: map files save/list/load inside MAPS_DIR only")


def test_analysis_endpoint():
    client, world = _client(create_test_city())
    with client:
        a = client.get("/api/analysis").json()
        assert a["buildings"]["total"] == 29
        assert a["buildings"]["by_category"]["Residential"] == 22
        assert a["buildings"]["population"] > 0 and a["buildings"]["jobs"] > 0
        # Exact deterministic demand: same run twice -> same numbers.
        assert a["demand"]["daily_trips"] > 0
        assert a == client.get("/api/analysis").json()
        assert a["network"]["roads"] == 78
        assert a["network"]["intersections"] > 0
        assert a["network"]["lane_miles"] > 0
        # A fully connected city with all categories -> no warnings.
        assert a["warnings"] == []

        # Detach a building's driveway entirely -> a warning appears
        # (analysis itself never mutates; we mutate via the edit API).
        bid = next(iter(world.network.buildings))
        for dw in world.network.buildings[bid].data.get("driveways", []):
            client.delete(f"/api/edit/node/{dw['entrance']}")
        warns = client.get("/api/analysis").json()["warnings"]
        assert any(f"{world.network.buildings[bid].building_type} {bid} "
                   in w for w in warns), warns

    # Empty world: zeros, no crash.
    client2, _ = _client()
    with client2:
        a = client2.get("/api/analysis").json()
        assert a["buildings"]["total"] == 0 and a["demand"]["daily_trips"] == 0
    print("ok: analysis serves exact demand, network totals, and warnings")


def test_websocket_streams_state():
    client, world = _client(create_test_city())
    with client:
        with client.websocket_connect("/ws/sim") as ws:
            first = ws.receive_json()
            assert first == {"running": False}
        client.post("/api/sim/start", json={"paused": True})
        client.post("/api/sim/tick", json={"ticks": 60})
        with client.websocket_connect("/ws/sim") as ws:
            msg = ws.receive_json()
            assert msg["running"] and msg["paused"]
            assert msg["tick"] == 60
            assert "vehicles" in msg and "clock" in msg
    print("ok: websocket streams the current snapshot on connect")


if __name__ == "__main__":
    test_no_pygame_in_api_stack()   # MUST run first (checks sys.modules)
    test_map_roundtrip()
    test_edits_are_undoable()
    test_delete_node_cascades_and_restores()
    test_building_lifecycle_with_driveway()
    test_continuous_road_drawing_is_one_undo()
    test_road_curve_and_profile_edits()
    test_api_tick_matches_direct_session()
    test_edit_stops_running_sim()
    test_sim_start_requires_buildings()
    test_schemas_and_control_validation()
    test_geometry_endpoint_shape()
    test_map_files_save_load_jailed()
    test_analysis_endpoint()
    test_websocket_streams_state()
    print("\napi-server: all tests passed")
