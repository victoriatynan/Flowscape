"""
Flowscape web API (WEB_MIGRATION_PLAN.md Phase 3).

FastAPI wrapper around the headless fixed-timestep SimulationSession. The
backend is authoritative for ALL world and simulation state (see the
Architectural Invariants): the browser issues editing commands and renders
what it is told; every mutation happens here, wrapped in an undoable
Command on the server-side UndoStack.

Communication (matching the plan):
  - REST  : discrete request/response actions -- editing, undo/redo,
            sim control, map load/save, schemas, static geometry.
  - WS    : /ws/sim streams dynamic snapshots while the sim runs.

The simulation advances on the FIXED timestep only (SimulationSession.tick);
the real-time pacing loop just decides how many whole ticks are due and can
never change results (guarded by test_sim_session.py's batching test).

Run:  python api_server.py   (serves on http://127.0.0.1:8000, docs at /docs)
"""

import asyncio
import contextlib
import dataclasses
import os
import time

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from destinations import (BUILDING_TYPES, BUILDING_TYPE_ORDER, CATEGORIES,
                          RESIDENTIAL, generate_trips)
from intersection_control import (CONTROL_TYPE_ORDER, CONTROL_TYPE_LABELS,
                                  CONTROL_TYPE_IMPLEMENTED,
                                  control_settings_schema)
from map_data import (MAPS_DIR, MAP_FILE_EXTENSION, map_to_dict,
                      load_map_dict, save_map, load_map, validate_network)
from road_geometry import build_node_surfaces, compute_road_polygon
from road_network import RoadNetwork, BUILDING_SIZE_FT, FOLD_MIN_ANGLE_DEG
from road_style import (get_road_profile, offset_polyline, ROAD_PROFILE_PRESETS,
                        ROAD_MARK_RATIO, profile_markings, marking_segments,
                        SHOULDER_NONE, SHOULDER_COLORS)
from routing import lane_polyline, _polyline_length
from sim_session import SimulationSession, DEFAULT_TICK_RATE
from undo_history import Command, UndoStack

# Pacing-loop tuning. POLL is how often the loop checks for due ticks;
# MAX_TICKS_PER_SLICE caps catch-up after a stall (beyond it the debt is
# dropped -- the sim slows down rather than death-spiraling; determinism is
# untouched either way, only the real-time rate).
PACING_POLL_SEC = 0.01
MAX_TICKS_PER_SLICE = 30
# Dynamic-state broadcast cadence (plan: 10-20 Hz; sim ticks stay 60 Hz).
SNAPSHOT_INTERVAL_SEC = 1.0 / 15.0


class EditCommand(Command):
    """A reversible API edit built from do/undo closures (the same pattern
    the editor's MoveCommand uses; undo_history stays engine-agnostic)."""

    def __init__(self, do, undo):
        self._do = do
        self._undo = undo

    def redo(self):
        self._do()

    def undo(self):
        self._undo()


class WorldState:
    """The single authoritative world: one network + its undo history +
    the (optional) running simulation session."""

    def __init__(self, network=None):
        self.network = network if network is not None else RoadNetwork()
        self.undo_stack = UndoStack()
        self.session = None
        self.paused = False

    def stop_sim(self):
        self.session = None
        self.paused = False

    def apply(self, do, undo):
        """Run an edit, push it as one undo step, and stop any running
        simulation (its cached routes/vehicles would dangle over the edit)."""
        sim_was_running = self.session is not None
        self.stop_sim()
        do()
        self.undo_stack.push(EditCommand(do, undo))
        return sim_was_running


def _guard_fold_limit(net, affected_node_ids, apply_change, revert_change):
    """Enforce the mismatched-width fold limit around a pending edit.

    `apply_change`/`revert_change` mutate the network in place (position,
    curve, profile, an added road). We apply the change, ask the network
    which of `affected_node_ids` now violate the limit, always revert, and
    raise HTTP 400 if any did -- so the offending state is never committed
    and the real edit still runs through the undo system afterward. Returns
    nothing; raises HTTPException on violation."""
    apply_change()
    try:
        offenders = net.fold_limit_offenders(affected_node_ids)
    finally:
        revert_change()
    if offenders:
        raise HTTPException(
            400,
            "that would fold two roads of different widths too sharply "
            f"(nodes {offenders}); keep the bend within "
            f"{int(FOLD_MIN_ANGLE_DEG)} degrees of straight.")


# ----------------------------------------------------------------------
# Request bodies
# ----------------------------------------------------------------------

class NodeIn(BaseModel):
    x: float
    y: float


class MoveNodeIn(BaseModel):
    x: float
    y: float


class RoadIn(BaseModel):
    start_node_id: int
    # Either connect to an existing node, or give a position: the backend
    # creates the endpoint node + road as ONE undoable command (continuous
    # road drawing -- see EDITOR_IMPROVEMENT_PLAN.md).
    end_node_id: int | None = None
    end_pos: tuple[float, float] | None = None
    curve_offset: tuple[float, float] = (0.0, 0.0)


class BuildingIn(BaseModel):
    x: float
    y: float
    main_node_id: int
    building_type: str = "Small House"


class ControlIn(BaseModel):
    control: str
    settings: dict[str, float] = Field(default_factory=dict)


class CurveIn(BaseModel):
    control_x: float
    control_y: float


class RoadProfileIn(BaseModel):
    preset: str | None = None
    lane_count_forward: int | None = Field(None, ge=1, le=6)
    lane_count_reverse: int | None = Field(None, ge=1, le=6)


class SimStartIn(BaseModel):
    paused: bool = False
    tick_rate: int = DEFAULT_TICK_RATE
    hours_per_second: float | None = None
    max_vehicles: int | None = None
    trip_limit: int | None = None
    # Unified single-clock mode (the "real simulator"): one clock drives motion,
    # demand, and expiry together, with sub-stepped physics. `time_scale` is
    # sim-seconds per real second; unset falls back to the session default. In
    # unified mode `hours_per_second` is derived from `time_scale` and ignored.
    unified: bool = False
    time_scale: float | None = Field(None, ge=1.0, le=360.0)


class TickIn(BaseModel):
    ticks: int = Field(1, ge=1, le=100_000)


class MapFileIn(BaseModel):
    filename: str


def _map_path(filename):
    """MAPS_DIR-jailed path for a client-supplied name: basename only, the
    canonical extension enforced."""
    name = os.path.basename(filename.strip())
    if not name or name in (".", ".."):
        raise HTTPException(400, "empty or invalid filename")
    if not name.endswith(MAP_FILE_EXTENSION):
        name += MAP_FILE_EXTENSION
    return os.path.join(MAPS_DIR, name)


# ----------------------------------------------------------------------
# App factory
# ----------------------------------------------------------------------

def create_app(world=None):
    world = world if world is not None else WorldState()

    @contextlib.asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(_pacing_loop(world))
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    app = FastAPI(title="Flowscape API", lifespan=lifespan)
    app.state.world = world

    # ---------------- health ----------------

    @app.get("/api/health")
    def health():
        return {"status": "ok",
                "sim_running": world.session is not None,
                "paused": world.paused}

    # ---------------- map (persisted data) ----------------

    @app.get("/api/map")
    def get_map():
        """The persisted map data (map_data schema: data + seeds only)."""
        return map_to_dict(world.network)

    @app.put("/api/map")
    def put_map(raw: dict):
        """Replace the whole world from a map dict (same rebuild path as the
        file loader). Clears undo history and stops the sim."""
        world.stop_sim()
        try:
            load_map_dict(world.network, raw)
        except (KeyError, TypeError, ValueError) as e:
            raise HTTPException(400, f"malformed map: {e!r}")
        world.undo_stack.clear()
        return {"ok": True,
                "warnings": validate_network(world.network, verbose=False)}

    @app.get("/api/map/files")
    def list_map_files():
        os.makedirs(MAPS_DIR, exist_ok=True)
        return {"files": sorted(f for f in os.listdir(MAPS_DIR)
                                if f.endswith(MAP_FILE_EXTENSION))}

    @app.post("/api/map/save")
    def save_map_file(body: MapFileIn):
        os.makedirs(MAPS_DIR, exist_ok=True)
        path = _map_path(body.filename)
        save_map(world.network, path)
        return {"ok": True, "filename": os.path.basename(path)}

    @app.post("/api/map/load")
    def load_map_file(body: MapFileIn):
        path = _map_path(body.filename)
        if not os.path.isfile(path):
            raise HTTPException(404, f"no such map: {os.path.basename(path)}")
        world.stop_sim()
        load_map(world.network, path)
        world.undo_stack.clear()
        return {"ok": True, "filename": os.path.basename(path)}

    @app.post("/api/map/test-city")
    def load_test_city():
        """Load the built-in deterministic test city (the editor's B key),
        through the same rebuild path as any other map load."""
        from test_city import create_test_city
        world.stop_sim()
        load_map_dict(world.network, map_to_dict(create_test_city()))
        world.undo_stack.clear()
        return {"ok": True,
                "nodes": len(world.network.nodes),
                "buildings": len(world.network.buildings)}

    # ---------------- static geometry (tessellated, world-space) ----------------

    @app.get("/api/geometry")
    def get_geometry():
        """Tessellated world-space geometry for the client renderer. The
        frontend never recomputes any of this (Geometry Ownership invariant);
        it re-fetches after edits (static data moves only when it changes).

        Roads come TRIMMED at junction mouths, with each node's surface
        (corner-fillet junction / continuation band / width taper, plus the
        sidewalk/shoulder outer ring and dead-end caps) served as its own
        polygon set -- the same build_node_surfaces pass the editor draws
        from, so both clients tessellate identically."""
        net = world.network

        def hexcolor(rgb):
            return "#{:02x}{:02x}{:02x}".format(*rgb[:3])

        def lines_out(edge_lines):
            return [{"points": pts, "color": hexcolor(c)}
                    for pts, c in (edge_lines or [])]

        surfaces = build_node_surfaces(net)
        roads = []
        for road in net.roads.values():
            geo = net.geometry_for_road(road)
            profile = get_road_profile(road)
            centerline = surfaces["trimmed_points"].get(road.id,
                                                        geo["sampled_points"])
            # Asphalt body between the profile's own (possibly asymmetric)
            # carriageway edges, built with the SAME offset_polyline the
            # lane centerlines use, so lanes, road edges, and junction
            # mouths all line up exactly. A wider shoulder polygon layers
            # underneath when the profile has one.
            lw, rw = profile.left_width(), profile.right_width()
            left = offset_polyline(centerline, lw)
            right = offset_polyline(centerline, -rw)
            has_shoulder = (profile.shoulder_type != SHOULDER_NONE
                            and profile.shoulder_width > 0)
            shoulder_polygon = None
            if has_shoulder:
                sw = profile.shoulder_width
                shoulder_polygon = compute_road_polygon(
                    offset_polyline(centerline, lw + sw),
                    offset_polyline(centerline, -(rw + sw)))
            # Real lane markings from the profile's boundary layout (see
            # road_style.profile_markings): the center boundary between
            # opposing directions (amber), separators between same-direction
            # lanes (dashed cream), and the outer edge lines (cream). All
            # follow the TRIMMED centerline so they stop at junction mouths
            # -- the same pass the retired editor renderer drew.
            markings = []
            if len(centerline) >= 2:
                for marking, offset in profile_markings(profile):
                    color = "#efac28" if abs(offset) < 1e-6 else "#efd8a1"
                    line_pts = (offset_polyline(centerline, offset)
                                if offset else centerline)
                    for segment in marking_segments(line_pts, marking):
                        markings.append({"points": segment, "color": color})
            roads.append({
                "id": road.id,
                "start_node_id": road.start_node_id,
                "end_node_id": road.end_node_id,
                "centerline": centerline,
                "control_point": geo["control_point"],
                "profile_data": dict((road.data or {}).get("profile") or {}),
                "polygon": compute_road_polygon(left, right),
                "markings": markings,
                "marking_width": ROAD_MARK_RATIO * profile.carriageway_width(),
                "shoulder_polygon": shoulder_polygon,
                "shoulder_color": (hexcolor(SHOULDER_COLORS.get(
                    profile.shoulder_type, (120, 120, 120)))
                    if has_shoulder else None),
                "total_width": profile.total_width(),
                "lanes_forward": profile.lanes_forward(),
                "lanes_reverse": profile.lanes_reverse(),
            })
        junctions = [{
            "node_id": s["node_id"],
            "kind": s["kind"],
            "polygon": s["polygon"],
            "edge_lines": lines_out(s["edge_lines"]),
            "mouth_width": s["mouth_width"],
            "outer_polygon": s["outer_polygon"],
            "outer_edge_lines": lines_out(s["outer_edge_lines"]),
            "outer_color": (hexcolor(s["outer_color"])
                            if s["outer_color"] else None),
        } for s in surfaces["nodes"]]
        caps = [{"node_id": c["node_id"], "pos": c["pos"],
                 "radius": c["radius"]} for c in surfaces["caps"]]
        lanes = []
        for road in net.roads.values():
            profile = get_road_profile(road)
            for direction, count in (("F", profile.lanes_forward()),
                                     ("R", profile.lanes_reverse())):
                for k in range(count):
                    lane_id = (road.id, direction, k)
                    lanes.append({"lane_id": list(lane_id),
                                  "points": lane_polyline(net, lane_id)})
        buildings = [{
            "id": b.id,
            "x": b.x, "y": b.y,
            "building_type": b.building_type,
            "size_ft": BUILDING_SIZE_FT.get(
                BUILDING_TYPES[b.building_type].size, 30.0)
                if b.building_type in BUILDING_TYPES else 30.0,
            "connection_node_ids": list(b.connection_node_ids),
        } for b in net.buildings.values()]
        nodes = [{"id": n.id, "x": n.x, "y": n.y,
                  "control": (n.data or {}).get("control")}
                 for n in net.nodes.values()]
        return {"nodes": nodes, "roads": roads, "lanes": lanes,
                "buildings": buildings, "junctions": junctions, "caps": caps}

    # ---------------- editing (authoritative, undoable) ----------------

    @app.post("/api/edit/node")
    def create_node(body: NodeIn):
        node = world.network.add_node(body.x, body.y)
        nid = node.id

        def do():
            world.network.nodes[nid] = node

        def undo():
            world.network.nodes.pop(nid, None)

        # add_node already applied the edit; register do/undo around it.
        world.stop_sim()
        world.undo_stack.push(EditCommand(do, undo))
        return {"ok": True, "node": {"id": nid, "x": node.x, "y": node.y}}

    @app.post("/api/edit/node/{node_id}/move")
    def move_node(node_id: int, body: MoveNodeIn):
        net = world.network
        node = net.nodes.get(node_id)
        if node is None:
            raise HTTPException(404, f"no node {node_id}")
        before = (node.x, node.y)
        after = (body.x, body.y)

        def write(state):
            node.x, node.y = state

        # Moving a node changes the tangent it presents AND the tangent each
        # of its roads presents at the far end, so both it and its neighbors
        # can be pushed across the fold limit.
        _guard_fold_limit(net, [node_id] + net.neighbor_node_ids(node_id),
                          lambda: write(after), lambda: write(before))
        world.apply(lambda: write(after), lambda: write(before))
        return {"ok": True}

    @app.post("/api/edit/node/{node_id}/control")
    def set_node_control(node_id: int, body: ControlIn):
        node = world.network.nodes.get(node_id)
        if node is None:
            raise HTTPException(404, f"no node {node_id}")
        if body.control not in CONTROL_TYPE_IMPLEMENTED:
            raise HTTPException(400, f"unknown/unimplemented control "
                                     f"{body.control!r}")
        schema_keys = {s.key for s in control_settings_schema(body.control)}
        bad = set(body.settings) - schema_keys
        if bad:
            raise HTTPException(400, f"settings not in the {body.control} "
                                     f"schema: {sorted(bad)}")
        before = dict(node.data or {})
        after = dict(before)
        after["control"] = body.control
        after.update(body.settings)

        def write(state):
            node.data = dict(state)

        world.apply(lambda: write(after), lambda: write(before))
        return {"ok": True, "data": node.data}

    @app.delete("/api/edit/node/{node_id}")
    def delete_node(node_id: int):
        net = world.network
        node = net.nodes.get(node_id)
        if node is None:
            raise HTTPException(404, f"no node {node_id}")
        # Snapshot everything remove_node cascades over.
        roads = {r.id: r for r in net.roads_for_node(node_id)}
        connections_before = {b.id: list(b.connection_node_ids)
                              for b in net.buildings.values()
                              if node_id in b.connection_node_ids}

        def do():
            for rid in roads:
                net.roads.pop(rid, None)
            for bid in connections_before:
                b = net.buildings.get(bid)
                if b is not None:
                    b.connection_node_ids = [n for n in b.connection_node_ids
                                             if n != node_id]
            net.nodes.pop(node_id, None)

        def undo():
            net.nodes[node_id] = node
            net.roads.update(roads)
            for bid, conns in connections_before.items():
                b = net.buildings.get(bid)
                if b is not None:
                    b.connection_node_ids = list(conns)

        world.apply(do, undo)
        return {"ok": True, "removed_roads": sorted(roads)}

    @app.post("/api/edit/road")
    def create_road(body: RoadIn):
        net = world.network
        if body.start_node_id not in net.nodes:
            raise HTTPException(404, f"no node {body.start_node_id}")
        if (body.end_node_id is None) == (body.end_pos is None):
            raise HTTPException(400, "give exactly one of end_node_id / end_pos")
        world.stop_sim()

        end_node = None
        if body.end_node_id is not None:
            if body.end_node_id not in net.nodes:
                raise HTTPException(404, f"no node {body.end_node_id}")
            if body.start_node_id == body.end_node_id:
                raise HTTPException(400, "a road needs two distinct nodes")
            end_id = body.end_node_id
        else:
            # Continuous drawing: create the endpoint node with the road,
            # as one compound command (a single undo removes both).
            end_node = net.add_node(*body.end_pos)
            end_id = end_node.id

        road = net.add_road(body.start_node_id, end_id,
                            curve_offset=tuple(body.curve_offset))
        rid = road.id

        # add_road/add_node already made the road live, so the network is in
        # its post-edit state -- validate both endpoints and roll back if the
        # new road would fold a width-mismatched pair too sharply.
        offenders = net.fold_limit_offenders([body.start_node_id, end_id])
        if offenders:
            net.roads.pop(rid, None)
            if end_node is not None:
                net.nodes.pop(end_node.id, None)
            raise HTTPException(
                400,
                "that road would fold two roads of different widths too "
                f"sharply (nodes {offenders}); keep the bend within "
                f"{int(FOLD_MIN_ANGLE_DEG)} degrees of straight.")

        def do():
            if end_node is not None:
                net.nodes[end_node.id] = end_node
            net.roads[rid] = road

        def undo():
            net.roads.pop(rid, None)
            if end_node is not None:
                net.nodes.pop(end_node.id, None)

        world.undo_stack.push(EditCommand(do, undo))
        return {"ok": True,
                "road": {"id": rid,
                         "start_node_id": road.start_node_id,
                         "end_node_id": road.end_node_id},
                "created_node": ({"id": end_node.id, "x": end_node.x,
                                  "y": end_node.y}
                                 if end_node is not None else None)}

    @app.post("/api/edit/road/{road_id}/curve")
    def set_road_curve(road_id: int, body: CurveIn):
        """Bend the road: place its quadratic-bezier control point at the
        given world position (stored as curve_offset from the chord
        midpoint -- the editor's drag-the-red-dot operation)."""
        net = world.network
        road = net.roads.get(road_id)
        if road is None:
            raise HTTPException(404, f"no road {road_id}")
        before = tuple(road.curve_offset)

        def write(offset):
            road.curve_offset = tuple(offset)

        def do():
            net.set_curve_offset_from_control_point(
                road, (body.control_x, body.control_y))

        # Bending the road swings its outward tangent at BOTH ends, so either
        # endpoint could cross the fold limit against its neighbouring road.
        _guard_fold_limit(net, [road.start_node_id, road.end_node_id],
                          do, lambda: write(before))
        world.apply(do, lambda: write(before))
        return {"ok": True, "curve_offset": list(road.curve_offset)}

    @app.post("/api/edit/road/{road_id}/profile")
    def set_road_profile(road_id: int, body: RoadProfileIn):
        """Merge profile changes (preset and/or per-direction lane counts)
        into road.data['profile'] -- the same storage the pygame inspector
        edits, so both UIs stay interchangeable."""
        net = world.network
        road = net.roads.get(road_id)
        if road is None:
            raise HTTPException(404, f"no road {road_id}")
        if body.preset is not None and body.preset not in ROAD_PROFILE_PRESETS:
            raise HTTPException(400, f"unknown preset {body.preset!r}")
        before = dict(road.data or {})
        profile = dict(before.get("profile") or {})
        if body.preset is not None:
            profile["preset"] = body.preset
        if body.lane_count_forward is not None:
            profile["lane_count_forward"] = body.lane_count_forward
        if body.lane_count_reverse is not None:
            profile["lane_count_reverse"] = body.lane_count_reverse
        after = dict(before)
        after["profile"] = profile

        def write(state):
            road.data = dict(state)

        # Widening/narrowing this road can turn an already-sharp equal-width
        # bend at either end into the mismatched fold the builder can't draw,
        # so the profile change is held to the same limit.
        _guard_fold_limit(net, [road.start_node_id, road.end_node_id],
                          lambda: write(after), lambda: write(before))
        world.apply(lambda: write(after), lambda: write(before))
        return {"ok": True, "profile": profile}

    @app.delete("/api/edit/road/{road_id}")
    def delete_road(road_id: int):
        net = world.network
        road = net.roads.get(road_id)
        if road is None:
            raise HTTPException(404, f"no road {road_id}")

        def do():
            net.roads.pop(road_id, None)

        def undo():
            net.roads[road_id] = road

        world.apply(do, undo)
        return {"ok": True}

    @app.post("/api/edit/building")
    def create_building(body: BuildingIn):
        net = world.network
        if body.main_node_id not in net.nodes:
            raise HTTPException(404, f"no node {body.main_node_id}")
        if body.building_type not in BUILDING_TYPES:
            raise HTTPException(400, f"unknown building type "
                                     f"{body.building_type!r}")
        main = net.nodes[body.main_node_id]
        control_before = dict(main.data or {})
        world.stop_sim()
        building = net.add_building_with_driveway(
            (body.x, body.y), body.main_node_id,
            building_type=body.building_type)
        bid = building.id
        dw = building.data["driveways"][0]
        entrance = net.nodes[dw["entrance"]]
        driveway = net.roads[dw["road"]]
        control_after = dict(main.data or {})

        def do():
            net.nodes[entrance.id] = entrance
            net.roads[driveway.id] = driveway
            net.buildings[bid] = building
            main.data = dict(control_after)

        def undo():
            net.buildings.pop(bid, None)
            net.roads.pop(driveway.id, None)
            net.nodes.pop(entrance.id, None)
            main.data = dict(control_before)

        world.undo_stack.push(EditCommand(do, undo))
        return {"ok": True, "building": {"id": bid,
                                         "entrance_node_id": entrance.id,
                                         "driveway_road_id": driveway.id}}

    @app.delete("/api/edit/building/{building_id}")
    def delete_building(building_id: int):
        net = world.network
        building = net.buildings.get(building_id)
        if building is None:
            raise HTTPException(404, f"no building {building_id}")
        # The editor's delete lifecycle: the building goes, and each driveway
        # entrance node goes with it (cascading to its driveway road).
        entrances = {}
        driveway_roads = {}
        for dw in building.data.get("driveways", []):
            en = net.nodes.get(dw["entrance"])
            if en is not None:
                entrances[en.id] = en
                for r in net.roads_for_node(en.id):
                    driveway_roads[r.id] = r

        def do():
            net.buildings.pop(building_id, None)
            for rid in driveway_roads:
                net.roads.pop(rid, None)
            for nid in entrances:
                net.nodes.pop(nid, None)

        def undo():
            net.buildings[building_id] = building
            net.nodes.update(entrances)
            net.roads.update(driveway_roads)

        world.apply(do, undo)
        return {"ok": True, "removed_nodes": sorted(entrances),
                "removed_roads": sorted(driveway_roads)}

    @app.post("/api/edit/undo")
    def undo():
        world.stop_sim()
        did = world.undo_stack.undo()
        return {"ok": did, "can_undo": world.undo_stack.can_undo(),
                "can_redo": world.undo_stack.can_redo()}

    @app.post("/api/edit/redo")
    def redo():
        world.stop_sim()
        did = world.undo_stack.redo()
        return {"ok": did, "can_undo": world.undo_stack.can_undo(),
                "can_redo": world.undo_stack.can_redo()}

    # ---------------- simulation control ----------------

    @app.post("/api/sim/start")
    def sim_start(body: SimStartIn):
        kwargs = {"tick_rate": body.tick_rate}
        if body.hours_per_second is not None:
            kwargs["hours_per_second"] = body.hours_per_second
        if body.max_vehicles is not None:
            kwargs["max_vehicles"] = body.max_vehicles
        if body.trip_limit is not None:
            kwargs["trip_limit"] = body.trip_limit
        if body.unified:
            kwargs["unified"] = True
        if body.time_scale is not None:
            kwargs["time_scale"] = body.time_scale
        try:
            world.session = SimulationSession(world.network, **kwargs)
        except ValueError as e:
            raise HTTPException(400, str(e))
        world.paused = body.paused
        return {"ok": True, "paused": world.paused,
                "tick_dt": world.session.tick_dt}

    @app.post("/api/sim/pause")
    def sim_pause():
        if world.session is None:
            raise HTTPException(409, "simulation is not running")
        world.paused = True
        return {"ok": True}

    @app.post("/api/sim/resume")
    def sim_resume():
        if world.session is None:
            raise HTTPException(409, "simulation is not running")
        world.paused = False
        return {"ok": True}

    @app.post("/api/sim/stop")
    def sim_stop():
        world.stop_sim()
        return {"ok": True}

    @app.post("/api/sim/tick")
    def sim_tick(body: TickIn):
        """Advance exactly N fixed ticks synchronously. Deterministic,
        pacing-independent stepping (tests, debugging, fast-forward)."""
        if world.session is None:
            raise HTTPException(409, "simulation is not running")
        world.session.run(body.ticks)
        return world.session.snapshot()

    @app.get("/api/sim/state")
    def sim_state():
        if world.session is None:
            return {"running": False}
        snap = world.session.snapshot()
        snap["running"] = True
        snap["paused"] = world.paused
        return snap

    # ---------------- schemas (drive the client UI generically) ----------------

    # ---------------- map analysis (read-only; never mutates) ----------------

    @app.get("/api/analysis")
    def analysis():
        """Read-only map analysis (EDITOR_IMPROVEMENT_PLAN.md): building
        counts, EXACT day-0 demand (the deterministic generate_trips run,
        not an estimate), network totals, and connectivity warnings. Purely
        informational -- computing it never touches simulation state."""
        net = world.network

        # Buildings by category (+ population/jobs from nominal capacity).
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

        # Demand: the same deterministic generation the simulation uses.
        trips = generate_trips(net, day_index=0) if net.buildings else []
        morning = sum(1 for t in trips if 6.0 <= t.depart_hour < 10.0)
        evening = sum(1 for t in trips if 15.0 <= t.depart_hour < 19.0)

        # Network totals.
        roads = [r for r in net.roads.values() if not r.is_preview]
        lane_length_ft = 0.0
        for road in roads:
            profile = get_road_profile(road)
            centerline = net.geometry_for_road(road)["sampled_points"]
            lane_length_ft += _polyline_length(centerline) * (
                profile.lanes_forward() + profile.lanes_reverse())
        intersections = sum(1 for nid in net.nodes if net.is_intersection(nid))

        # Connectivity warnings: union-find over road links, then flag
        # buildings that are detached or in a minority component; plus
        # demand-mix gaps (residential with nowhere to go).
        parent = {nid: nid for nid in net.nodes}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

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
        # Demand-mix gap: trip generation redistributes weights across the
        # categories that exist, so a missing single category is fine --
        # the real problem is residential with NO destinations at all.
        non_residential = sum(v for c, v in by_category.items()
                              if c != RESIDENTIAL)
        if by_category.get(RESIDENTIAL, 0) > 0 and non_residential == 0:
            warnings.append("Residential areas have no destinations "
                            "(add commercial/education/recreation buildings)")

        return {
            "buildings": {"total": len(net.buildings),
                          "by_category": by_category,
                          "population": population,
                          "jobs": jobs},
            "demand": {"daily_trips": len(trips),
                       "morning_peak_trips": morning,
                       "evening_peak_trips": evening},
            "network": {"roads": len(roads),
                        "nodes": len(net.nodes),
                        "intersections": intersections,
                        "lane_miles": lane_length_ft / 5280.0},
            "warnings": warnings,
        }

    @app.get("/api/schema/intersection-control")
    def schema_intersection_control():
        return {"order": list(CONTROL_TYPE_ORDER),
                "labels": dict(CONTROL_TYPE_LABELS),
                "implemented": sorted(CONTROL_TYPE_IMPLEMENTED),
                "settings": {kind: [dataclasses.asdict(s)
                                    for s in control_settings_schema(kind)]
                             for kind in CONTROL_TYPE_ORDER}}

    @app.get("/api/schema/building-types")
    def schema_building_types():
        """The catalogue facts a client UI needs (picker, footprint, info
        text). Activity profiles stay backend-only -- they are demand
        internals, not render data."""
        return {"order": list(BUILDING_TYPE_ORDER),
                "types": {name: {
                    "category": bt.category,
                    "size": bt.size,
                    "size_ft": BUILDING_SIZE_FT.get(bt.size, 30.0),
                    "capacity": bt.capacity,
                    "count_range": list(bt.count_range),
                    "open_hour": bt.open_hour,
                    "close_hour": bt.close_hour,
                } for name, bt in BUILDING_TYPES.items()}}

    @app.get("/api/schema/road-presets")
    def schema_road_presets():
        """The named road-profile presets (see road_style.py) with the
        facts a client UI needs to offer and describe them."""
        return {"order": list(ROAD_PROFILE_PRESETS),
                "presets": {name: {
                    "lane_width": p.lane_width,
                    "lanes_per_direction": p.lanes_per_direction,
                    "shoulder_type": p.shoulder_type,
                    "shoulder_width": p.shoulder_width,
                    "median_width": p.median_width,
                } for name, p in ROAD_PROFILE_PRESETS.items()}}

    @app.get("/api/palette")
    def palette_colors():
        """The fantasy-24 palette (+ documented extras) as hex strings, so
        the client draws with the same colors as the editor (the project's
        palette-only rule extends to the browser)."""
        import palette
        return {"palette": ["#" + h for h in palette._HEXES],
                "extras": ["#" + h for h in palette.EXTRA_HEXES]}

    # ---------------- dynamic state stream ----------------

    @app.websocket("/ws/sim")
    async def ws_sim(ws: WebSocket):
        """Streams sim snapshots at SNAPSHOT_INTERVAL_SEC while connected.
        Always sends the current state immediately on connect."""
        await ws.accept()
        try:
            while True:
                if world.session is None:
                    await ws.send_json({"running": False})
                else:
                    snap = world.session.snapshot()
                    snap["running"] = True
                    snap["paused"] = world.paused
                    await ws.send_json(snap)
                await asyncio.sleep(SNAPSHOT_INTERVAL_SEC)
        except WebSocketDisconnect:
            pass

    # ---------------- browser client (Phase 4) ----------------
    # Serve the built web client (web/dist at the repo root) at /, when it
    # exists. API routes above take precedence; without a build the API
    # still works standalone (tests, curl, the pygame editor era).
    dist = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "web", "dist")
    if os.path.isdir(dist):
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=dist, html=True), name="client")

    return app


async def _pacing_loop(world):
    """Real-time pacing: decide how many whole fixed ticks are due and run
    them. Only the RATE is real-time; every tick is the same fixed dt, so
    pacing can never alter simulation results."""
    last = time.perf_counter()
    while True:
        await asyncio.sleep(PACING_POLL_SEC)
        now = time.perf_counter()
        session = world.session
        if session is None or world.paused:
            last = now
            continue
        due = int((now - last) / session.tick_dt)
        if due <= 0:
            continue
        if due > MAX_TICKS_PER_SLICE:
            session.run(MAX_TICKS_PER_SLICE)   # cap catch-up, drop the debt
            last = now
        else:
            session.run(due)
            last += due * session.tick_dt      # keep the fractional remainder


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
