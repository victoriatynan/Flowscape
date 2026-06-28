# Flowscape

Flowscape is a top-down 2D traffic simulation game/tool that allows users to design road networks, place intersections, control traffic signals, and see how vehicles move on roads. This project aims to cover congestion, roadway capacity, signal timing, queue formation, and more in a sandbox-like game.

Built in Python + pygame, and **deterministic** by design: the same map and seed always replay the same day, so behavior is reproducible and verifiable without watching the screen.

## How it works at a glance

You draw a road network — nodes, curved roads, intersections, buildings — and Flowscape brings it to life: it builds a lane-connectivity graph at every junction, generates a realistic day of trips from the buildings, and micro-simulates individual vehicles (perception → decision → dynamics) as they route across the map and negotiate intersections. The simulation is kept cheap enough to run smoothly in pygame while producing varied, believable traffic.

- **Road editor** — place nodes, connect them with straight or bezier-curved roads, drag to reshape, edit per-road lane counts and curvature, save/load maps as JSON.
- **Lane graph** — automatic many-to-many lane-to-lane connectivity at every junction, derived purely from road geometry.
- **Intersection control** — pluggable controllers (reservation-based, stop-sign), configurable per node from the Inspector.
- **Building demand model** — 27 building types across 6 categories, each with vehicle-count ranges and weekday/weekend activity profiles. Buildings (never bare road nodes) generate trips.
- **Vehicle micro-simulation** — a three-layer driver model (perception, speed-governor decision, dynamics) plus a lateral lane-change pass.
- **Debug visualizations** — toggle overlays for the lane graph, perception, decisions, dynamics, and intersection state.

## Installation

Requires **Python 3.12** and **pygame ≥ 2.5.2**.

```bash
pip install -r requirements.txt
```

## How to run

```bash
python Flowscape/main.py
```

Once the editor is open, the fastest way to see traffic:

1. Press **B** to load the built-in test city (a grid of roads + buildings).
2. Press **T** to start the trip demo — vehicles begin spawning from buildings over an accelerated day/night cycle.
3. Press **G**, **P**, **J**, **K**, or **I** to inspect what the simulation is doing.

## Controls

**Tools** (top toolbar, or number keys when not in the Road tool)

| Key | Tool | Does |
|---|---|---|
| `1` | Select | Select/drag nodes, select roads, edit control points |
| `2` | Node | Click anywhere to create a node (no road) |
| `3` | New Road | Connect two **existing** nodes (creates no nodes) |
| — | Building | Place a building on a road node (scrollable type picker) |
| — | Zone | Placeholder (coming soon) |

**Camera** (any tool)

- **Scroll** — zoom at cursor
- **Right-drag** — pan the view

**Select tool**

- Hover a node to highlight; click to select (green ring); drag to move it (roads follow).
- Click a road to select it (orange) — shows its bezier control point.
- Drag the red dot to bend the curve, or **scroll** to nudge curvature.
- Click empty space to deselect.

**New Road tool**

- Click node A, move the mouse for a live preview, click node B to commit A→B.
- **Scroll** adjusts curvature; **Esc** or click empty space cancels.
- Snap mode (this tool only): **`1`** Auto · **`2`** Straight · **`3`** Curved · hold **Shift** to force curved · hold **Ctrl** to force straight.

**Visualization overlays**

| Key | Overlay |
|---|---|
| `G` | Lane graph |
| `V` | Spawn a demo vehicle |
| `P` | Perception (what each vehicle senses ahead) |
| `K` | Dynamics |
| `J` | Decision (speed-governor) |
| `I` | Intersection control state |

**General**

| Key | Action |
|---|---|
| `D` | Toggle debug |
| `B` | Load the test city |
| `T` | Toggle the daily trip demo |
| `S` / `Shift+S` | Save map JSON / Save As |
| `L` | Load map JSON |
| `Del` / `Backspace` | Delete selected |
| `Ctrl/Cmd+Z` | Undo |
| `Ctrl+Shift+Z` / `Ctrl/Cmd+Y` | Redo |
| `Esc` | Cancel drag / road placement / modal |
| `F11` | Toggle fullscreen |

## Running the tests

Every feature is guarded by a `test_*.py` that runs headless with plain asserts (no pytest required). Run one directly, with a dummy video driver so it needs no display:

```bash
cd Flowscape
SDL_VIDEODRIVER=dummy python test_building_demand.py
SDL_VIDEODRIVER=dummy python test_lane_change.py
SDL_VIDEODRIVER=dummy python test_spawn_clearance.py
SDL_VIDEODRIVER=dummy python test_intersection_control_ui.py
SDL_VIDEODRIVER=dummy python test_undo_move.py
```

The visual sweeps (`test_intersections_visual.py`, `test_2road_angles_visual.py`) render PNGs into `test_output/` for inspection.

## Documentation

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — layer dependency diagram, module map, data flow, and the extension patterns every subsystem follows.
- **[REFACTOR_PLAN.md](REFACTOR_PLAN.md)** — current split targets and the proposed extraction order.
