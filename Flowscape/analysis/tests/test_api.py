"""
Endpoint test: /api/analysis/v2 runs the platform on demand over static and
runtime state, and does NOT break the legacy /api/analysis endpoint.
"""

from fastapi.testclient import TestClient

from api_server import create_app, WorldState
from map_data import map_to_dict
from test_city import create_test_city


def _client():
    world = WorldState(create_test_city())
    return TestClient(create_app(world)), world


def test_v2_static_run():
    client, _ = _client()
    r = client.get("/api/analysis/v2")
    assert r.status_code == 200
    body = r.json()
    assert body["metadata"]["source_kind"] == "static"
    obs = body["observations"]
    assert obs["road_count"]["value"] > 0
    assert obs["vehicle_count"]["value"] == 0
    assert obs["total_road_length"]["units"] == "ft"


def test_v2_static_has_all_stage_buckets_but_no_traffic_metrics():
    # M2: the four stage buckets are always present. On a static map there is no
    # measured volume, so V/C and LOS are undefined and nothing is flagged --
    # but capacity (a static property) is still computed.
    client, _ = _client()
    body = client.get("/api/analysis/v2").json()
    assert set(body) >= {"observations", "metrics", "findings",
                         "recommendations", "metadata"}
    assert body["observations"]["traffic_volume"]["value"] is None
    assert body["metrics"]["vc_ratio"]["value"] is None
    assert body["metrics"]["level_of_service"]["value"] is None
    assert body["metrics"]["road_capacity"]["value"] > 0
    assert body["findings"]["over_capacity"]["flagged"] is False
    assert body["recommendations"]["add_capacity"]["items"] == []


def test_v2_uses_runtime_source_when_sim_running():
    client, _ = _client()
    client.post("/api/sim/start", json={"paused": False})
    client.post("/api/sim/tick", json={"ticks": 120})
    body = client.get("/api/analysis/v2").json()
    assert body["metadata"]["source_kind"] == "runtime"
    assert body["metadata"]["is_running"] is True


def test_v2_runtime_produces_traffic_metrics():
    # After enough ticks for vehicles to traverse roads, the runtime run carries
    # measured volume and a real V/C for at least one road.
    client, _ = _client()
    client.post("/api/sim/start", json={"paused": False})
    client.post("/api/sim/tick", json={"ticks": 2500})
    body = client.get("/api/analysis/v2").json()
    assert body["metadata"]["metric_ids"]           # metric stage ran
    vol = body["observations"]["traffic_volume"]["detail"]["per_road"]
    assert vol                                      # some road carried traffic
    vc = body["metrics"]["vc_ratio"]["detail"]["per_road"]
    assert set(vc) <= set(vol)                      # V/C only where volume exists
    assert all(e["vc"] > 0 for e in vc.values())


def test_legacy_analysis_endpoint_unchanged():
    client, _ = _client()
    r = client.get("/api/analysis")
    assert r.status_code == 200
    body = r.json()
    # The legacy shape is intact (buildings/demand/network/warnings).
    assert set(body) == {"buildings", "demand", "network", "warnings"}
