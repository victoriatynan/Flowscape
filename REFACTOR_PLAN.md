# Flowscape Refactor Plan

This is the working plan for breaking down the oversized modules so the codebase stays easy for both humans and LLMs to work on. It is intentionally incremental: every step is independently shippable and verifiable against the existing headless tests.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the layer rules these extractions are trying to restore.

---

## Why this plan exists

Most modules are small and single-purpose (under ~700 lines). Two are not, and one is a layering violation hiding in the largest file:

- `road_editor.py` is **~4,200 lines** — 4× the next largest module — and contains 15 classes plus 20 module functions spanning four different responsibilities (domain model, geometry, rendering, UI/input).
- `traffic_sim.py` is **~930 lines** and fuses two concerns: routing/pathfinding and the vehicle runtime.
- The `RoadNetwork` **domain model** and a cluster of **geometry helpers** live inside `road_editor.py` (the UI layer) when they belong lower in the stack.

Large, multi-responsibility files are the main friction for editing precisely, reviewing changes, and fitting context into a model. Splitting them is high value and independent of any feature work.

---

## Current split targets

| File | Lines | Problem |
|---|---|---|
| `road_editor.py` | ~4,200 | 6–7 modules fused; includes a misplaced domain model and misplaced geometry helpers. **Primary target.** |
| `traffic_sim.py` | ~930 | Routing/pathfinding fused with the vehicle runtime. **Secondary target.** |
| `intersection_control.py` | ~674 | Cohesive today, but holds multiple controller strategies. **Watch** — split one-strategy-per-file only if a 3rd/4th controller lands. |
| `road_style.py` | ~540 | Does two jobs (`RoadStyle` vs `RoadProfile`). **Watch** — split only if it grows. |

---

## Proposed extraction order

Ordered so the biggest clarity wins and the layering fixes come first, and so each step leaves the tree green.

### `road_editor.py`

1. **`RoadNetwork` → `road_network.py`** — move the domain model out of the UI file.
2. **Geometry helpers → `road_geometry.py`** — move `_fillet_points`, `_line_intersection`, `_segment_intersection`, `detect_geometry_issues`, `_build_junction_polygon`, `_taper_curve`, `_build_taper_polygon`, etc. into the geometry layer where they belong.
3. **`RoadRenderer` → `renderer.py`** and **`InputController` → `editor_controller.py`** — the two largest remaining classes (21 and 39 methods).
4. **Panels → `editor_panels.py`** (`Toolbar`, `SimPanel`, `BuildingPanel`, `GridPanel`, `SettingsPanel`, `Sidebar`, `StartScreen`); **`Camera`/`ScaleBar` → `camera.py`**; **`SnapSystem`/`PlacementManager` → `placement.py`**.
5. **App entry → `app.py`** (`main`, `run_start_screen`, `_compute_layout`, save-prompt).

### `traffic_sim.py`

6. **Routing → `routing.py`** — pull `build_routing_graph`, `find_lane_path` (Dijkstra), `lane_polyline` and related helpers out; keep `Vehicle` + `TrafficSimulation` runtime in `traffic_sim.py`.

---

## Why each extraction exists

- **`road_network.py`** — the model is referenced everywhere but currently can only be imported through the UI monolith. Pulling it out fixes a layering violation and lets the simulation/data layers depend on it cleanly.
- **Geometry helpers → `road_geometry.py`** — geometry is supposed to have a single home. These helpers leaked upward into the UI file; returning them restores the "single source of truth for geometry" rule and shrinks `road_editor.py` fast.
- **`renderer.py`** — `RoadRenderer` (21 methods) is a self-contained drawing concern; isolating it makes both rendering and the rest of the editor easier to reason about.
- **`editor_controller.py`** — `InputController` (39 methods) is the single most complex class in the project; on its own it becomes reviewable and testable.
- **`editor_panels.py` / `camera.py` / `placement.py`** — these are cohesive UI/interaction units that don't need to sit in the same file as the model or renderer. `inspector_panel.py` already proves this split works.
- **`app.py`** — wiring/entry is a distinct concern from both the model and the UI widgets.
- **`routing.py`** — pathfinding is pure graph logic with no per-frame state; separating it from the `Vehicle`/`TrafficSimulation` runtime clarifies both and makes routing independently testable.

> Guardrail for every step: it is a **move**, not a rewrite. Behavior must not change, and the full headless test suite must stay green before and after. Because the suite is deterministic, this is exactly the kind of low-risk, reversible refactor that is safe to hand to an LLM one module at a time.

---

## Progress checklist

### `road_editor.py`
- [ ] 1. Extract `RoadNetwork` → `road_network.py`
- [ ] 2. Move geometry helpers → `road_geometry.py`
- [ ] 3a. Extract `RoadRenderer` → `renderer.py`
- [ ] 3b. Extract `InputController` → `editor_controller.py`
- [ ] 4a. Extract panels → `editor_panels.py`
- [ ] 4b. Extract `Camera` / `ScaleBar` → `camera.py`
- [ ] 4c. Extract `SnapSystem` / `PlacementManager` → `placement.py`
- [ ] 5. Extract app entry → `app.py`

### `traffic_sim.py`
- [ ] 6. Extract routing/pathfinding → `routing.py`

### Watch list (no action yet)
- [ ] `intersection_control.py` — split per-strategy only if a 3rd controller is added
- [ ] `road_style.py` — split `RoadStyle` vs `RoadProfile` only if it grows

### Definition of done (per step)
- [ ] Behavior unchanged (pure move)
- [ ] No upward layer dependencies introduced
- [ ] Full headless test suite green (`SDL_VIDEODRIVER=dummy python test_*.py`)
