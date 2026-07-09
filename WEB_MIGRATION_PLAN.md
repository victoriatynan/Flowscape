# Web Migration Plan

This document outlines the long-term plan for migrating Flowscape from a desktop Pygame application to a browser-based application while preserving the existing simulation engine.

The objective is **not** to rewrite the simulator. Instead, the existing Python simulation will become a headless backend, and a modern web frontend will replace the current Pygame interface.

The backend will remain the single source of truth for all simulation state, while the browser will be responsible only for rendering, user interaction, and editor controls.

This migration is intended to be incremental, allowing existing functionality and deterministic testing to remain intact throughout the process.

---

## Goals

* Preserve all existing simulation logic.
* Do not port the simulation to JavaScript.
* Keep deterministic simulation behavior.
* Maintain compatibility with existing save files.
* Preserve the current architectural layering.
* Replace only the presentation layer.
* Continue supporting automated headless testing.
* Improve maintainability by separating UI from simulation.

---

## Existing Architecture

```
App / Entry
      │
Editor / UI
      │
Demand & Scheduling
      │
Simulation
      │
Lane Graph
      │
Geometry / Style
      │
Data
```

Everything below the Editor/UI layer is already Pygame-free and can execute headlessly (verified: no module below Editor/UI imports pygame — the simulation layer stores sprite *paths* only; loading happens in the renderer).

This existing separation makes the project well suited for a client-server architecture.

---

## Target Architecture

```
                Browser

        HTML / CSS / JavaScript
                 │
      Canvas / WebGL Rendering
                 │
     REST API + WebSocket Connection
                 │
──────────────────────────────────────────
             Python Backend
──────────────────────────────────────────

      Editor / Simulation API
                 │
      Demand & Scheduling
                 │
        Vehicle Simulation
                 │
          Lane Graph
                 │
       Geometry / Style
                 │
               Data
```

The browser becomes another client of the simulation rather than containing simulation logic itself.

---

## Architectural Invariants

The following principles must remain true throughout the migration. Every architectural decision should be evaluated against these invariants.

### Backend Authority

The backend is the single source of truth for both simulation and editor state. The frontend must never become authoritative over simulation data or world state, and must never duplicate or independently calculate simulation behavior.

This covers, among other things:

* vehicle movement
* routing
* demand generation
* traffic lights
* scheduling
* lane changes
* building state

All changes to the world are performed by the backend. The frontend only visualizes the results.

### Preserve Existing Layering

The current layering remains intact, with the API replacing Pygame as the top of the stack:

```
Browser → API → Simulation → Lane Graph → Geometry → Data
```

No frontend code should directly manipulate simulation internals.

### Geometry Ownership

All geometry generation is owned exclusively by the backend. This includes, but is not limited to:

* road geometry
* lane offsets
* Bezier sampling
* tapers
* fillets
* intersection polygons
* lane polygons
* any other derived geometry

The frontend must never recreate or independently calculate these structures. Instead, the backend provides **tessellated world-space geometry** (polylines and polygons), and the frontend only transforms and renders it.

This preserves the project's existing "single source of truth" philosophy and prevents a second geometry implementation from drifting out of sync.

### Determinism

Determinism is a fundamental design goal. Given identical maps, building seeds, and simulation settings, the backend must always produce identical simulation results.

Rendering speed, network latency, or client performance must never influence simulation behavior.

This ensures:

* reproducible bugs
* reliable testing
* deterministic save files

### Fixed Simulation Timestep

The backend simulation must execute using a **fixed timestep** rather than frame time. (Today the Pygame loop feeds the simulation clamped real frame time; determinism currently comes from the tests feeding a constant `dt`. The server loop makes fixed stepping the rule.)

Simulation timing must be independent of rendering, network transmission, and browser refresh rate.

Recommended architecture:

* Simulation updates at a fixed rate (for example, 60 simulation ticks per second).
* Snapshot broadcasts occur independently (for example, 10–20 updates per second).
* Browser rendering occurs independently at the display refresh rate, interpolating between snapshots.

This preserves deterministic behavior while allowing efficient network communication and smooth rendering. Adopting the fixed-timestep loop is the acceptance criterion for Phase 2.

### Static vs Dynamic Data

Static data is transmitted only when it changes:

* road, lane, and intersection geometry (tessellated)
* buildings
* palettes

Dynamic simulation data is streamed continuously:

* vehicle positions, rotation, speed
* traffic light states
* simulation clock
* performance statistics

The frontend combines the static map with dynamic updates to render each frame. This minimizes bandwidth while keeping rendering responsive.

### Frontend Is a Client, Not the Editor

Although editing occurs through the browser, the frontend does not own editor logic. It issues editing commands to the backend:

* CreateRoad
* DeleteRoad
* MoveNode
* SplitRoad
* PlaceBuilding
* DeleteBuilding

The backend performs all validation, authoritative snapping, geometry generation, routing updates, and state modifications. The frontend presents the resulting world state.

**Preview nuance:** during a live drag, the frontend may display a *non-authoritative* snap or placement preview (this is temporary UI state, which the frontend owns). The backend re-validates and performs the authoritative snap when the edit is committed. Previews never mutate world state.

### Selection Model

Object selection is temporary UI state and remains entirely client-side. The backend is queried only when retrieving object data, validating edits, or applying changes. Selection state is not synchronized over the WebSocket connection.

### Collaboration Scope

The initial web migration targets a **single-user** editor. Collaborative editing is explicitly out of scope for the initial implementation. This keeps undo history, editing operations, and simulation state straightforward while leaving multi-user support as a separate future architectural effort.

---

## Backend Responsibilities

The backend becomes the simulation server. It is responsible for:

* maintaining the RoadNetwork
* executing fixed-timestep simulation ticks
* routing vehicles
* generating traffic demand and scheduling trips
* processing lane changes
* managing traffic lights and intersection control
* generating all derived geometry (tessellation for the client)
* validating editor operations and performing authoritative snapping
* applying every world modification
* maintaining undo history
* loading and saving maps
* broadcasting simulation state snapshots

The backend remains responsible for every authoritative simulation decision.

---

## Frontend Responsibilities

The frontend becomes a rendering and editing client. It is responsible for:

* drawing roads, buildings, and vehicles from backend-supplied geometry
* camera movement
* selection and other temporary UI state
* toolbars, inspector panels, and property editing
* sending editing commands to the backend
* interpolating between simulation snapshots for smooth rendering
* non-authoritative previews during drags (see the snapping nuance above)

The frontend never performs authoritative simulation calculations.

---

## Communication Strategy

Two communication methods will be used.

### REST API

REST endpoints are appropriate for discrete request/response user actions:

* create road / delete road
* place building
* move node
* undo / redo
* load map / save map
* start / pause / stop simulation

### WebSockets

WebSockets are appropriate for continuously changing information:

* vehicle positions
* simulation clock
* traffic lights
* performance statistics
* simulation status

A persistent connection avoids repeatedly polling the backend. (Selection is deliberately absent from this list — see the Selection Model invariant.)

---

## Inspector Architecture

The existing schema-driven inspector architecture is preserved. Rather than creating frontend-specific property editors, the backend exposes object schemas through the API, and the frontend dynamically generates inspector controls from those schemas.

This allows new editable object types or controller types to be introduced without frontend-specific UI development — the same extension pattern the Pygame inspector already follows.

---

## Suggested Technology

**Backend:** Python, FastAPI, WebSockets, Uvicorn

**Frontend:** React, TypeScript, HTML5 Canvas

Potential future upgrade: PixiJS or a WebGL renderer for improved performance.

---

## Migration Phases

### Phase 1 — Refactor What the Migration Needs ✅ Done

Before introducing any web technologies, complete the extractions from [REFACTOR_PLAN.md](REFACTOR_PLAN.md) that unblock the migration, in priority order:

1. **Extract `RoadNetwork`** out of `road_editor.py` — the API server cannot cleanly import the domain model through a Pygame monolith.
2. **Extract the geometry helpers** into `road_geometry.py` — the backend tessellation endpoint needs geometry importable without the UI.
3. **Extract routing** out of `traffic_sim.py` into `routing.py`.

The remaining extractions (Pygame renderer, input controller, camera, panels) stay valuable for maintainability while the Pygame editor lives through Phase 5, but they are **lower priority** because that code is ultimately replaced by the web frontend.

### Phase 2 — Headless Backend ✅ Done

Separate the simulation loop completely from Pygame. The simulation must be executable without creating a window, driven by the fixed-timestep loop described in the invariants.

**Acceptance criterion:** a fixed-rate tick loop produces identical results to the headless test harness for the same map and seed.

Implemented as `sim_session.py` (`SimulationSession`: demand → scheduler → spawn queue → traffic sim, advanced in fixed 60 Hz ticks, `snapshot()` for state out), guarded by `test_sim_session.py`: no pygame in `sys.modules`, two sessions in lockstep, tick pipeline equal to the hand-wired fixed-dt harness, and tick batching provably invisible to results.

### Phase 3 — Introduce FastAPI ✅ Done

Wrap the simulation with a web server. Create API endpoints for editing, simulation control, loading, saving, and inspector schema/data access. No frontend changes are required at this stage.

Implemented as `api_server.py` (run with `python api_server.py`, interactive docs at `/docs`), guarded by `test_api_server.py` (12 tests via TestClient, no network). What it provides:

* **Editing (REST, authoritative, undoable)** — create/move/delete nodes, roads, buildings (with the model-B driveway lifecycle), per-node intersection-control settings validated against the schema, undo/redo on a server-side `UndoStack`. Any edit stops a running simulation so cached routes never dangle.
* **Simulation control** — start (optionally paused) / pause / resume / stop, plus a synchronous `POST /api/sim/tick` for deterministic stepping; a real-time pacing loop runs whole fixed ticks only, so pacing can never alter results.
* **Map persistence** — `GET/PUT /api/map` (full map dict through the same rebuild path as the file loader) and save/load/list of named files jailed to the `maps/` folder.
* **Static geometry** — `GET /api/geometry` serves tessellated world-space centerlines, road polygons, lane polylines, nodes, and building footprints (Geometry Ownership invariant: the client only renders).
* **Schemas** — intersection-control types + per-type `FieldSpec` settings, and the building-type catalogue, for schema-driven client UI.
* **Streaming** — `WS /ws/sim` broadcasts dynamic snapshots at 15 Hz while the sim runs (60 Hz fixed ticks underneath).

Junction-surface tessellation (the renderer's fillet/taper polygons) is not yet exposed over `/api/geometry`; that lands with Phase 4 when the browser renderer needs it.

### Phase 4 — Browser Renderer ✅ Initial client done

Build an initial browser client supporting map rendering (from tessellated geometry), vehicle rendering (from snapshots), and camera movement. The Pygame editor continues to function during this phase.

Implemented as `web/` (Vite + React + TypeScript + Canvas). `npm run build` produces `web/dist`, which `api_server.py` serves at `/` — so `python Flowscape/api_server.py` is the whole stack. For development, `npm run dev` proxies `/api` and `/ws` to the Python server.

What the client does: renders the map from `GET /api/geometry` (road polygons, dashed lane centerlines, category-colored building footprints, control-ring nodes — fantasy-24 palette throughout), draws vehicles from the `/ws/sim` stream with id-matched interpolation between 15 Hz snapshots, wheel-zoom-at-cursor + drag-pan camera, and a toolbar (load test city, start/pause/resume/stop, live clock/car/queue readout). Because the backend is authoritative, the sim keeps running across page reloads.

Supporting backend additions: stable per-run vehicle ids in snapshots (deterministic spawn order), `POST /api/map/test-city`, `GET /api/palette`, static serving of `web/dist`.

Junction-surface tessellation is done: the node-surface assembly pass was extracted from the pygame renderer into `road_geometry.build_node_surfaces()` (verified pixel-identical — all 25 visual-sweep PNGs hash-equal before/after, and the renderer passes its builders through so the `check_*.py` monkey-patch diagnostics still intercept). `/api/geometry` now serves trimmed road bodies (asymmetric carriageway edges via the same `offset_polyline` lanes use), shoulder polygons, junction/continuation/taper surface polygons with fillet edge-line curves, and dead-end caps — and the browser client draws them with the editor's exact layering.

Remaining fidelity niceties (not blocking Phase 5): per-road lane markings/decals, vehicle sprites, traffic-light state visuals.

### Phase 5 — Browser Editor 🔶 Core tools done

Gradually replace editor functionality: selection, node editing, road drawing, building placement, inspector, toolbar. Pygame remains available until feature parity is achieved.

Landed so far (all mutations through the authoritative API, all undoable server-side):

* **Tools** — Select / Node / Road / Building, with an edit toolbar, undo/redo buttons, and keyboard shortcuts (Esc, Del, Ctrl+Z/Y).
* **Select** — hit-testing for nodes, buildings, and roads (client-side picking only); drag-to-move nodes with a non-authoritative preview committed via `POST .../move` on release.
* **Road drawing** — two-click node-to-node with a dashed preview line.
* **Building placement** — type picker from the building-types schema, ghost footprint at the cursor, driveway wired to the nearest road node by the backend.
* **Inspector** — schema-driven panel (the pygame inspector's counterpart): intersection-control kind + `FieldSpec` settings generated from the API schema, object info, delete.

Verified end-to-end in the browser: create nodes/road/building, apply a stop-sign control, drag-move, then six undos restored the pristine test city.

Also landed since: **road curvature editing** (drag the selected road's bezier control handle; `POST /api/edit/road/{id}/curve` recomputes the curve server-side), **per-road profile/lane editing** (preset + per-direction lane counts in the inspector, merged into `road.data['profile']` — the same storage the pygame inspector edits — via `POST /api/edit/road/{id}/profile`, presets served at `/api/schema/road-presets`), and the **map save/load UI** (Save… prompt + Load… file dropdown over the jailed `maps/` endpoints). Browser-verified: an 80 px handle drag produced a 140 ft offset with the centerline bowing exactly offset/2; a save → mutate → load roundtrip restored both curve and profile.

Still to reach parity before Phase 6: zones, snap modes, the debug visualization overlays, and rendering niceties (lane markings/decals, vehicle sprites, traffic-light state visuals).

### Phase 6 — Complete Migration ✅ Done

After all editor functionality has been migrated:

* remove Pygame rendering
* remove Pygame event handling
* retain the simulation engine

The simulator now runs entirely through the browser.

**Teardown record (all three criteria met):**

1. **Editor-behavior tests re-based.** `test_undo_move` now drives `undo_history.MoveTransaction`/`UndoStack` directly (the layer the drag-collapses-to-one-step law lives in); `test_intersection_control_ui`, `test_traffic_light`, and `test_driveways` exercise the same domain sequences the API performs (`node.data` writes + `IntersectionControl.rebuild()`, `add_building_with_driveway`, the delete lifecycle). The pygame widget tests retired with the widgets — that surface is the schema-driven web inspector, guarded by `test_api_server.py` and browser verification.
2. **Geometry diagnostics re-based.** Scenario networks moved to `junction_scenarios.py` (pure); `check_fillet_direction.py` / `check_taper.py` capture rings via `build_node_surfaces()` builder hooks instead of monkey-patching the renderer — reproducing the baseline counts exactly (140 fillets / 2 known violations, 12 tapers / 1 known violation). The visual sweeps' programmatic guard (caps only at dead ends, one surface per multi-road node) became `test_junction_surfaces.py`. The lane-marking connector non-crossing guard retired with the renderer; recreate it when lane markings are served over the API.
3. **Parity gaps resolved by explicit scope decisions.** Zones were a placeholder even in pygame (dropped; re-scope when zones become real); snap modes were new-road preview UX (client-side concern for a future editor polish pass); the key-toggled debug overlays retired with the renderer (the `visual_layers()` producers remain in the simulation modules, ready to serve over the API as client overlays).

The pygame modules (`road_editor.py`, `ui_widgets.py`, `inspector_panel.py`, `snap_mode.py`, the PNG sweeps, `zoom_junction.py`, icon `tools/`) are removed from the tree; `pygame` is no longer a dependency. The whole Python suite runs with no display and no SDL.

---

## Testing Strategy

Existing deterministic tests remain the primary verification mechanism. Every migration step must preserve:

* deterministic generation
* save compatibility
* routing behavior
* scheduling
* lane changes
* traffic lights
* undo history

New API endpoints receive automated tests where appropriate. The simulation remains executable headlessly throughout the migration.

---

## Long-Term Benefits

* Modern browser-based interface
* Platform-independent deployment
* Cleaner separation between simulation and presentation
* Easier future UI development
* Potential for collaborative editing (out of scope initially — see Collaboration Scope)
* Easier remote hosting
* Simpler integration with external tools
* Greater maintainability through stronger architectural boundaries

The simulation engine remains unchanged while the user experience becomes significantly more flexible and maintainable.

---

## Documentation Conventions

* This file (`WEB_MIGRATION_PLAN.md`, repo root) is the canonical migration document.
* A single `requirements.txt` at the repository root is the only dependency file.
* Documentation follows the same "single source of truth" philosophy as the code: each fact stated in exactly one place.
