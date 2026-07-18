# Flowscape

Flowscape is a top-down 2D traffic simulation game/tool that allows users to design road networks, place intersections, control traffic signals, and see how vehicles move on roads. This project aims to cover congestion, roadway capacity, signal timing, queue formation, and more in a sandbox-like game.

A Python simulation backend (authoritative, fixed-timestep, **deterministic** by design: the same map and seed always replay the same day) serving a React/Canvas editor in the browser.

## How it works at a glance

You draw a road network — nodes, curved roads, intersections, buildings — and Flowscape brings it to life: it builds a lane-connectivity graph at every junction, generates a realistic day of trips from the buildings, and micro-simulates individual vehicles (perception → decision → dynamics) as they route across the map and negotiate intersections. The browser renders 15 Hz state snapshots streamed over a WebSocket, interpolated to display rate.

- **Browser editor** — place nodes, connect them with straight or bezier-curved roads, drag to reshape, edit per-road profiles/lane counts and curvature, save/load maps as JSON. Every edit is an authoritative, undoable backend command.
- **Lane graph** — automatic many-to-many lane-to-lane connectivity at every junction, derived purely from road geometry.
- **Intersection control** — pluggable controllers (reservation, stop sign, yield, traffic light), configurable per node from the schema-driven inspector.
- **Building demand model** — 27 building types across 6 categories, each with vehicle-count ranges and weekday/weekend activity profiles. Buildings (never bare road nodes) generate trips.
- **Vehicle micro-simulation** — a three-layer driver model (perception, speed-governor decision, dynamics) plus a lateral lane-change pass.

## Installation

Requires **Python 3.12** and **Node.js** (to build the web client once).

```bash
pip install -r requirements.txt
```

## How to run

Flowscape runs in the browser: a Python simulation backend (FastAPI) serving a
React/Canvas client (see [WEB_MIGRATION_PLAN.md](WEB_MIGRATION_PLAN.md)).

```bash
cd web && npm install && npm run build && cd ..   # once, to build the client
python Flowscape/main.py                          # serves + opens the browser
```

The app is at `http://127.0.0.1:8000/` (interactive API docs at `/docs`).
`--no-browser` serves without opening a window; `python Flowscape/api_server.py`
does the same thing directly.

Once the browser app is open, the fastest way to see traffic:

1. Click **Load Test City** (a grid of roads + buildings).
2. Click **▶ Start** — vehicles begin spawning from buildings over an accelerated day/night cycle.
3. Scroll to zoom, drag to pan; use the edit toolbar (Select / Node / Road / Building) to reshape the city, and the inspector to configure intersections and road profiles.

(The original desktop pygame editor was retired once the browser reached the migration's teardown criteria — see WEB_MIGRATION_PLAN.md Phase 6.)

## Running the tests

Every feature is guarded by a `test_*.py` that runs headless with plain asserts (no pytest, no display, no pygame). Run any of them directly:

```bash
cd Flowscape
python test_building_demand.py       # demand generation determinism
python test_sim_session.py           # fixed-timestep loop determinism
python test_api_server.py            # web API guards (in-process, no network)
python test_junction_surfaces.py     # junction tessellation guards
python test_driveways.py             # model-B driveway lifecycle
```

The geometry diagnostics (`check_fillet_direction.py`, `check_taper.py`) sweep the junction stress scenarios in `junction_scenarios.py` and report violations (a few are known and pre-existing; compare counts, don't expect zero).

## Documentation

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — layer dependency diagram, module map, data flow, and the extension patterns every subsystem follows.
- **[REFACTOR_PLAN.md](REFACTOR_PLAN.md)** — current split targets and the proposed extraction order.
- **[WEB_MIGRATION_PLAN.md](WEB_MIGRATION_PLAN.md)** — the completed migration to the browser, phase by phase, with the architectural invariants the codebase follows.
- **[EDITOR_IMPROVEMENT_PLAN.md](EDITOR_IMPROVEMENT_PLAN.md)** — editor workflow improvements (continuous road drawing, real lane markings, the Map Analysis panel).
- **[UI_PLAN.md](UI_PLAN.md)** — the UI theme/configuration system (design panel, presets, saved defaults).
- **[SIMULATION_PLAN.md](SIMULATION_PLAN.md)** — forward roadmap: taking the simulation from watchable demo to a validated traffic-engineering tool (unified clock, physics validation, metrics, scale).
