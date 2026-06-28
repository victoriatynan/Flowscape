# Flowscape Architecture

This document is the map of how Flowscape is put together: the layer dependency rule, what each module does, how data flows from a placed building to a moving vehicle, and the extension patterns that every subsystem follows.

If you read one thing, read the **layer dependency diagram** — it is the single most important invariant in the project.

---

## 1. Layer dependency diagram

Flowscape is a stack of layers. Each layer may depend **only on the layers below it**.

```
          ┌─────────────────────────────┐
          │        App / Entry          │   main.py, run loop, start screen
          └─────────────┬───────────────┘
                        ▼
          ┌─────────────────────────────┐
          │        Editor / UI          │   panels, widgets, inspector, renderer,
          │                             │   input controller, snap mode
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

- Geometry knows nothing about the simulation. The simulation knows nothing about the UI.
- Data and geometry layers contain **no pygame, no rendering, no input handling**.
- A dependency that points *up* the stack (e.g. geometry importing the renderer) is a bug — it is the thing this document exists to prevent.

This is why the codebase is testable headless and reproducible: everything below "Editor / UI" can be exercised and verified without a display.

> Note: the `RoadNetwork` domain model and several geometry helpers currently live *inside* `road_editor.py` (the Editor/UI layer). That is a known layering violation — the model and the geometry belong lower in the stack. See [REFACTOR_PLAN.md](REFACTOR_PLAN.md).

---

## 2. Module map

### Data layer (pure: no pygame, no rendering)
| Module | Responsibility |
|---|---|
| `road_geometry.py` | `Node` / `Road` / `Zone` dataclasses + pure geometry: bezier sampling, control points, road edges/polygons, tangents. The **single source of truth for geometry.** |
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

### Simulation (driver model)
| Module | Responsibility |
|---|---|
| `traffic_sim.py` | `Vehicle` + `TrafficSimulation` runtime **and** Dijkstra lane pathfinding / routing helpers (two concerns currently fused). |
| `vehicle_perception.py` | Sensing only: nearest leader ahead per vehicle. No movement changes. |
| `vehicle_decision.py` | "What speed?" — speed-governor rules (cruise, following distance, intersection approach); `compute_decisions`. |
| `vehicle_dynamics.py` | "How it moves" — speed integration, motion state. The bottom, **untouchable** layer of the driver model. |
| `vehicle_lane_change.py` | Lateral "pass 2.5": choose a lane change and build a smooth merge polyline. |
| `intersection_control.py` | Pluggable intersection control framework + strategies (`ReservationController`, `StopSignController`) + per-node schema. |

### Editor / UI
| Module | Responsibility |
|---|---|
| `road_editor.py` | **The monolith (~4,200 lines).** Domain model (`RoadNetwork`), camera, all sidebar panels, renderer, input controller, geometry helpers, app entry, start screen. |
| `ui_widgets.py` | Reusable immediate-mode toolkit: `ScrollContainer`, `Dropdown`, `Stepper`, `Button`, `ConfirmDialog`. |
| `inspector_panel.py` | Schema-driven property editor for the selected object (already extracted from the monolith — the model for how the rest should be split). |
| `snap_mode.py` | Road snap mode: controller (logic) + panel (UI). Affects new-road previews only. |

### Entry / diagnostics
| Module | Responsibility |
|---|---|
| `main.py` | Entry shim → `road_editor.main()`. |
| `check_*.py`, `zoom_junction.py` | Headless geometry diagnostics. |
| `test_*.py` | Per-feature guards (plain asserts, headless). |

---

## 3. Responsibilities by layer

- **Data** — own the facts (geometry primitives, save schema, building instances, colors, undo history). Pure Python, no engine.
- **Geometry & Style** — turn road/node facts into centerlines, edges, polygons, lane markings. World space, no rendering.
- **Lane Graph** — turn geometry + topology into drivable lane-to-lane connections.
- **Simulation** — move vehicles along lane paths using the three-layer driver model, mediated by intersection control.
- **Demand & Scheduling** — turn buildings into trips, and release those trips over an accelerated day.
- **Editor / UI** — let a human build the network and watch the simulation; the only layer that touches pygame input/rendering.

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
Input (InputController)
   -> mutate RoadNetwork (wrapped in an undo Command)
      -> road_geometry recomputes centerline/edges/polygon
         -> lane_graph rebuilds junction connectivity
            -> RoadRenderer draws it
```

---

## 5. Current subsystem overview

- **Road network & geometry** — stable. Curvature is a single scalar per road (perpendicular offset); geometry is regenerated, never hand-stored.
- **Lane graph** — stable; the backbone routing depends on.
- **Intersection control** — framework + reservation and stop-sign strategies; configured per node via `node.data` and rebuilt by a factory.
- **Driver model** — three layers (perception → decision → dynamics) plus a lateral lane-change pass; new driver concerns are added as decision *rules*, never by touching dynamics.
- **Demand model (Phase 1, done)** — 6 categories, 27 types, seed-driven `generate_trips`, weekday/weekend activity profiles.
- **Trip scheduling (Phase 2, planned)** — evolve `TripScheduler` + enrich `Trip` so activity windows mean *desired arrival* and departures are back-computed from a Euclidean travel-time estimate. No new layer.
- **Editor/UI** — functional but monolithic; the main refactor target.

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

**Add a UI control**
→ Build it once in `ui_widgets.py` (immediate-mode: `draw` + `handle_*`), then compose it in a panel. For per-object properties, add a field to the Inspector schema rather than a bespoke panel.

**Make a mutation undoable**
→ Wrap the change in a `Command` (or accumulate a drag into a `MoveTransaction`) and push it onto the `UndoStack`. A drag collapses into exactly one undo step.

**Persist a new field**
→ Add it to the matching `*_to_dict` / `*_from_dict` in `map_data.py`. Persist data and seeds only — never derived simulation state. Provide a default so old saves still load.

**Expose a debug visualization**
→ Have the subsystem return drawable `visual_layers()`; bind a key in the input controller to toggle the overlay (see `G` / `P` / `J` / `K` / `I`).

**Add a color**
→ Add it to `palette.py`. Drawing code references palette entries, never raw RGB.

**Add any feature**
→ Add a `test_*.py` beside it: plain asserts, runnable headless (`SDL_VIDEODRIVER=dummy`). One feature ⇄ one guard. Because generation is deterministic, tests are reliable oracles.
