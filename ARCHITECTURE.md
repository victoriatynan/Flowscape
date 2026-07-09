# Flowscape Architecture

This document is the map of how Flowscape is put together: the layer dependency rule, what each module does, how data flows from a placed building to a moving vehicle, and the extension patterns that every subsystem follows.

If you read one thing, read the **layer dependency diagram** — it is the single most important invariant in the project.

---

## 1. Layer dependency diagram

Flowscape is a stack of layers. Each layer may depend **only on the layers below it**.

```
          ┌─────────────────────────────┐
          │       Browser Client        │   web/ (React + TS + Canvas): renders,
          │                             │   edits, previews — never authoritative
          └─────────────┬───────────────┘
                        ▼  REST + WebSocket
          ┌─────────────────────────────┐
          │       Web API / Entry       │   api_server.py, sim_session.py, main.py
          └─────────────┬───────────────┘
                        ▼
          ┌─────────────────────────────┐
          │   Demand & Scheduling       │   destinations.py (building demand),
          │                             │   sim_clock.py (TripScheduler)
          └─────────────┬───────────────┘
                        ▼
          ┌─────────────────────────────┐
          │        Simulation           │   traffic_sim, vehicle_perception/
          │     (driver model)          │   decision/dynamics/lane_change,
          │                             │   intersection_control
          └─────────────┬───────────────┘
                        ▼
          ┌─────────────────────────────┐
          │         Lane Graph          │   lane_graph.py
          └─────────────┬───────────────┘
                        ▼
          ┌─────────────────────────────┐
          │     Geometry & Style        │   road_geometry.py, road_style.py
          └─────────────┬───────────────┘
                        ▼
          ┌─────────────────────────────┐
          │           Data              │   map_data.py, buildings/road_geometry
          │                             │   dataclasses, undo_history, palette
          └─────────────────────────────┘
```

**The rule: lower layers must never depend on higher layers.**

- Geometry knows nothing about the simulation. The simulation knows nothing about the API or the browser.
- The Python side contains **no rendering and no input handling** — the browser client owns presentation; the backend owns every fact and every mutation (see WEB_MIGRATION_PLAN.md's Architectural Invariants).
- A dependency that points *up* the stack (e.g. geometry importing the API) is a bug — it is the thing this document exists to prevent.

This is why the codebase is testable headless and reproducible: the entire Python stack runs without a display (no pygame anywhere; the desktop editor was retired in the web migration's Phase 6).

---

## 2. Module map

### Data layer (pure: no pygame, no rendering)
| Module | Responsibility |
|---|---|
| `road_geometry.py` | `Node` / `Road` / `Zone` dataclasses + pure geometry: bezier sampling, control points, road edges/polygons, tangents, junction/continuation surface helpers (fillets, tapers), the `build_node_surfaces` assembly pass (shared by the editor renderer and the web API), geometry watchdog. The **single source of truth for geometry.** |
| `road_network.py` | The `RoadNetwork` domain model: committed nodes/roads/zones/buildings in world space, driveway placement, trim/taper laws. No pygame. |
| `road_style.py` | Visual style (`RoadStyle`, lane markings, decals) **and** road profile (`RoadProfile`: lane counts, widths, median/shoulder regions). Logical/world-space only. |
| `map_data.py` | JSON save/load for nodes/roads/zones/buildings; `validate_network`. The **single source of truth for the save schema.** Persists data only — never derived simulation state. |
| `buildings.py` | `Building` placed-instance dataclass (type name, position, connection nodes, stable `seed`). |
| `undo_history.py` | Command-pattern undo/redo (`Command`, `MoveCommand`, `MoveTransaction`, `UndoStack`). Engine-agnostic. |
| `palette.py` | The fantasy-24 color palette. **Every color drawn anywhere must come from here.** |

### Geometry / Lane graph
| Module | Responsibility |
|---|---|
| `lane_graph.py` | Builds the many-to-many, weighted lane-to-lane connectivity graph at every junction, purely from road directions/geometry. Turn classification, connector curves. |

### Demand & scheduling
| Module | Responsibility |
|---|---|
| `destinations.py` | The building demand model: `BuildingType` / `Activity` / `Trip`, the 27-type catalogue, per-category activity profiles, and seed-driven `generate_trips`. The **single source of truth for building archetypes.** |
| `sim_clock.py` | **`TripScheduler`** — owns the daily schedule, advances an accelerated clock, and releases each trip exactly once via a spawn callback. The scheduling layer between demand and simulation. |
| `sim_session.py` | **`SimulationSession`** — fixed-timestep headless wrapper around the whole runtime spine (demand → scheduler → spawn queue → traffic sim). No pygame; the loop the web backend wraps (WEB_MIGRATION_PLAN.md Phase 2). Owns the demo/tick constants. |

### Simulation (driver model)
| Module | Responsibility |
|---|---|
| `traffic_sim.py` | `Vehicle` + `TrafficSimulation` runtime. |
| `routing.py` | Directed lane graph, deterministic Dijkstra pathfinding, lane traversal geometry (polylines, arc-length sampling). Pure logic, no per-frame state. |
| `vehicle_perception.py` | Sensing only: nearest leader ahead per vehicle. No movement changes. |
| `vehicle_decision.py` | "What speed?" — speed-governor rules (cruise, following distance, intersection approach); `compute_decisions`. |
| `vehicle_dynamics.py` | "How it moves" — speed integration, motion state. The bottom, **untouchable** layer of the driver model. |
| `vehicle_lane_change.py` | Lateral "pass 2.5": choose a lane change and build a smooth merge polyline. |
| `intersection_control.py` | Pluggable intersection control framework + strategies (`ReservationController`, `StopSignController`) + per-node schema. |

### Web API / Entry
| Module | Responsibility |
|---|---|
| `api_server.py` | FastAPI wrapper around `SimulationSession` + `RoadNetwork`: authoritative REST editing with server-side undo, sim control, map load/save, tessellated-geometry and schema endpoints, WebSocket snapshot stream; serves the built client at `/`. |
| `main.py` | Entry point → serves the web app (uvicorn) and opens the browser. |

### Browser client (`web/`, React + TypeScript + Canvas)
| Piece | Responsibility |
|---|---|
| `renderer.ts` / `camera.ts` | Draw backend-tessellated geometry + interpolated vehicles; pan/zoom (view state only). |
| `App.tsx` / `hitTest.ts` | Tools (Select/Node/Road/Building), selection hit-testing, non-authoritative drag previews committed as API commands. |
| `Inspector.tsx` | Schema-driven property panel (control kinds + `FieldSpec` settings, road presets/lanes). |
| `useSimStream.ts` | `/ws/sim` snapshots + id-matched interpolation. |

### Diagnostics / tests
| Module | Responsibility |
|---|---|
| `junction_scenarios.py` | Pure junction stress-scenario networks shared by the diagnostics. |
| `check_fillet_direction.py`, `check_taper.py` | Headless geometry diagnostics over `build_node_surfaces()` (report known violation counts; compare, don't expect zero). |
| `test_*.py` | Per-feature guards (plain asserts, headless, pygame-free). |

---

## 3. Responsibilities by layer

- **Data** — own the facts (geometry primitives, save schema, building instances, colors, undo history). Pure Python, no engine.
- **Geometry & Style** — turn road/node facts into centerlines, edges, polygons, lane markings. World space, no rendering.
- **Lane Graph** — turn geometry + topology into drivable lane-to-lane connections.
- **Simulation** — move vehicles along lane paths using the three-layer driver model, mediated by intersection control.
- **Demand & Scheduling** — turn buildings into trips, and release those trips over an accelerated day.
- **Web API / Entry** — expose editing, sim control, geometry, and schemas; own the fixed-timestep loop and every authoritative decision.
- **Browser client** — let a human build the network and watch the simulation; the only layer that touches rendering/input, and never authoritative.

---

## 4. Data flow

### Demand → vehicles (the runtime spine)
```
Building Demand          destinations.generate_trips(network, day_index, …)
      │                  buildings (with seeds) -> deterministic list[Trip]
      ▼
Trip Scheduler           sim_clock.TripScheduler
      │                  owns the day; releases each Trip when its time arrives
      ▼
Vehicle Spawn            TrafficSimulation.spawn_trip(origin_node, dest_node, …)
      │                  spawn-clearance gate may drop a blocked release
      ▼
Traffic Simulation       per frame: perception -> decision -> lane change ->
                         dynamics, mediated by intersection_control
```

Key property: **buildings generate trips; road nodes are only attachment points.** A node never sources demand. Every randomized property of a building (vehicle count, activity mix, departure times) is derived from that building's stable `seed`, so the same map replays identically.

### Editing → geometry → render
```
Browser tool click / drag release
   -> REST edit command (api_server)
      -> mutate RoadNetwork (wrapped in an undo Command)
         -> road_geometry recomputes centerlines/edges/junction surfaces
            -> client refetches /api/geometry and redraws
```

---

## 5. Current subsystem overview

- **Road network & geometry** — stable. Curvature is a single scalar per road (perpendicular offset); geometry is regenerated, never hand-stored.
- **Lane graph** — stable; the backbone routing depends on.
- **Intersection control** — framework + reservation and stop-sign strategies; configured per node via `node.data` and rebuilt by a factory.
- **Driver model** — three layers (perception → decision → dynamics) plus a lateral lane-change pass; new driver concerns are added as decision *rules*, never by touching dynamics.
- **Demand model (Phase 1, done)** — 6 categories, 27 types, seed-driven `generate_trips`, weekday/weekend activity profiles.
- **Trip scheduling (Phase 2, done)** — activity windows mean *desired arrival*; departures are back-computed from a Euclidean travel-time estimate, released through the spawn queue.
- **Web stack (migration done)** — `SimulationSession` (fixed 60 Hz timestep) wrapped by `api_server.py`, rendered/edited by the `web/` client. The pygame editor is retired; see WEB_MIGRATION_PLAN.md.

---

## 6. "Single source of truth" philosophy

Every fact lives in exactly **one** place; everything else references it.

- **Geometry** is computed only in `road_geometry.py`. Nothing stores derived edges/polygons.
- **Colors** come only from `palette.py` (fantasy-24).
- **Building archetypes** exist only in `destinations.BUILDING_TYPES`; a placed `Building` references its type *by name* and never copies category/size/capacity/hours onto itself.
- **The save schema** lives only in `map_data.py`, and it persists *data*, never derived simulation state. Reproducibility is stored as a **seed**, not as rolled-out values.
- **Road style/profile** is resolved from `road_style.py`, not duplicated per road.

The payoff: changing a fact (a color, a building's capacity, a road's geometry) changes it everywhere, and there is never a second copy to drift out of sync.

---

## 7. Extension patterns

A big reason Flowscape has been smooth to extend is that almost every subsystem follows a consistent, predictable pattern. When you add something new, find the matching pattern and follow it — you should rarely need to touch unrelated layers.

**Add a driver concern (e.g. "slow for a hazard")**
→ Add a *rule* to `vehicle_decision.py` that proposes a speed cap; the speed-governor takes the minimum of all proposals. **Never touch `vehicle_dynamics.py`.** Guard it with a `test_*.py`.

**Add an intersection control type (e.g. traffic signal)**
→ Add a `Controller` class implementing the controller interface, a settings schema, and register it in the `make_controller` factory. It becomes configurable per node via `node.data` with **no UI changes** — the Inspector is schema-driven.

**Add a building type**
→ Add one entry to `destinations.BUILDING_TYPES` (name, category, size, count range). It inherits its category's activity profile, picks up a category color, and appears in the palette via `BUILDING_TYPE_ORDER`. No generation code changes.

**Add a building/demand category or activity**
→ Extend `CATEGORIES` / `CATEGORY_PROFILES` in `destinations.py`. Trip generation already iterates categories and weighted activity choices generically.

**Add an editable property**
→ Serve it through a schema endpoint (`api_server.py`) and let the web inspector generate the control; add the validated edit endpoint as an undoable command. Never build bespoke frontend UI for per-object properties.

**Make a mutation undoable**
→ Wrap the change in a `Command` (or accumulate a drag into a `MoveTransaction`) and push it onto the `UndoStack`. A drag collapses into exactly one undo step.

**Persist a new field**
→ Add it to the matching `*_to_dict` / `*_from_dict` in `map_data.py`. Persist data and seeds only — never derived simulation state. Provide a default so old saves still load.

**Expose a debug visualization**
→ Have the subsystem return drawable `visual_layers()` (plain shape dicts); serve them over the API and draw them as a client overlay. (The pygame-era key-toggled overlays retired with the editor; `visual_layers()` producers remain in the simulation modules.)

**Add a color**
→ Add it to `palette.py`. Drawing code references palette entries, never raw RGB.

**Add any feature**
→ Add a `test_*.py` beside it: plain asserts, runnable headless (no display, no pygame). One feature ⇄ one guard. Because generation is deterministic, tests are reliable oracles.
