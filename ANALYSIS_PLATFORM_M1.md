# Analysis Platform — Milestone 1 (Core Framework)

> Implementation contract. Milestone 1 is an **architectural** milestone, not an
> engineering one. Its purpose is to establish the reusable analysis pipeline,
> plugin model, dependency resolution, and immutable data flow using a handful of
> simple, factual observations. Engineering analyses (capacity, LOS, stopping
> sight distance, …) arrive in later milestones as **plugins** on top of this
> proven framework — they are not part of M1.

Design rationale and the full multi-milestone vision live in
[`Flowscape/Analysis_System_Planning`](Flowscape/Analysis_System_Planning).

---

## What the platform is

A **read-only** layer that sits beside the simulation. It never influences
vehicle behavior, routing, demand, or geometry. It observes an immutable
snapshot of simulation state, evaluates it, and produces reusable analysis
results that applications consume.

```
Simulation snapshot → Observations → Metrics → Findings → Recommendations → Applications
                      └──────────────── M1 implements this stage ────┘
```

M1 implements **one stage (Observations) end-to-end**, but the engine (registry,
dependency resolver, cache, pipeline) is **stage-generic**: Metrics, Findings,
and Recommendations register and resolve through the exact same machinery in
later milestones with **no engine changes**. Proving that plumbing is the whole
point of the milestone.

## Non-breaking by construction

The existing `GET /api/analysis` endpoint and `AnalysisPanel.tsx` remain
**unchanged** and keep serving the current UI. The Analysis Platform runs
underneath as a **parallel** implementation exposed on a new endpoint. Over
future milestones the existing static calculations (building mix, demand,
connectivity, …) migrate into the platform until `/api/analysis` becomes a thin
adapter over it.

---

## Core principles (locked)

1. **Common snapshot interface.** One immutable `Snapshot` type. Both a static
   source (editor/map state) and a runtime source (live or replayed simulation)
   implement a common source interface and emit the *same* `Snapshot`. The
   pipeline is agnostic to which produced it.
2. **On demand only.** The platform is invoked explicitly. It never subscribes
   to ticks and has no coupling to the render loop or the simulation clock.
3. **Unit normalization at the boundary.** The snapshot **builder** is the only
   place that knows sim internals. It converts sim-internal quantities (scaled
   feet, sim-clock time, internal speed units) into **canonical engineering
   units** (true feet, mph, hours). No observation ever sees `ROAD_WIDTH_SCALE`
   or the fantastical clock.
4. **Immutable data flow.** Each stage consumes immutable outputs of the
   previous stage. No stage mutates simulation state or its own inputs.
5. **Standards are configurable implementations, not architecture.** M1 has no
   engineering standards. When they arrive, they are injected into plugins
   (a standards/config object), never baked into the engine or interfaces.
6. **Graceful degradation.** Road-classification fields (`functional_class`,
   `design_speed`, `context`) ride in the snapshot as **optional / `None`**.
   M1 does not depend on the P1 classification system landing.

---

## Package layout — `Flowscape/analysis/`

```
analysis/
├── __init__.py
├── snapshot/
│   ├── models.py      # frozen, immutable snapshot dataclasses
│   ├── builder.py     # THE unit-normalization boundary
│   └── sources.py     # StaticSource / RuntimeSource → same Snapshot type
├── observations/
│   ├── base.py        # Observation ABC + ObservationResult
│   ├── network.py     # RoadCount, IntersectionCount, TotalRoadLength,
│   │                  #   BuildingCount, ConnectedComponents
│   └── traffic.py     # VehicleCount, AverageVehicleSpeed
├── engine/
│   ├── registry.py         # stage-generic plugin registry
│   ├── dependency_graph.py # topo-sort + cycle detection
│   ├── cache.py            # per-run memoization, keyed by snapshot identity
│   └── pipeline.py         # run(snapshot, only=None) → AnalysisResult
├── models/
│   └── result.py      # AnalysisResult (+ metadata), JSON-serializable
└── tests/
```

Only the Observation stage has concrete plugins in M1. `metrics/`, `findings/`,
and `recommendations/` packages are **not** created yet — they slot in later
against the same `engine/`.

---

## The snapshot

Immutable (frozen) dataclasses holding **facts only**, in canonical units.

- **RoadSnapshot** — `id`, `length_ft`, `lanes_forward`, `lanes_reverse`,
  `start_node_id`, `end_node_id`; optional `functional_class`, `design_speed`,
  `context` (default `None`); runtime-only fields default to empty/`None` under
  a static source.
- **NodeSnapshot** — `id`, `is_intersection`, `control_type`, `position`.
- **BuildingSnapshot** — `id`, `building_type`, `category`,
  `connection_node_ids`.
- **VehicleSnapshot** — `id`, `origin`, `destination`, `position`,
  `speed_mph` (runtime only).
- **Snapshot** (top level) — the collections above plus `metadata`
  (`source_kind`, `is_running`, `sim_time_hours`, …).

### Sources (common interface, same output type)

- **StaticSource(world / RoadNetwork)** — topology + geometry; empty vehicle
  set; `is_running = False`.
- **RuntimeSource(sim_session)** — wraps the existing
  `SimSession.snapshot()`; same topology + live vehicles; `is_running = True`.

### Builder = normalization boundary

`build_snapshot(source) → Snapshot`. All unit conversions (stored→true feet,
internal speed→mph, sim-clock→hours) live here and nowhere else. Exact
conversion constants are pinned against `road_geometry.py`, `sim_clock.py`, and
`vehicle_dynamics.py` during implementation.

---

## Observation plugin interface

```
Observation:
    id: str
    category: str
    requires: tuple[str, ...]          # ids of observations it depends on
    compute(snapshot, deps) -> ObservationResult

ObservationResult:
    id, value, units, category         # JSON-serializable
```

### The seven M1 observations (independent, deterministic, factual)

| id                  | category | value                                            |
|---------------------|----------|--------------------------------------------------|
| road_count          | network  | number of non-preview roads                      |
| intersection_count  | network  | number of intersection nodes                     |
| total_road_length   | network  | Σ centerline length, ft                          |
| building_count      | network  | total buildings (+ breakdown by type)            |
| vehicle_count       | traffic  | active vehicles (0 when idle)                    |
| average_speed       | traffic  | mean vehicle speed, mph (empty-safe → None/0)    |
| connected_components| network  | count of disconnected road sub-networks          |

None make engineering judgments; they expose facts later metrics/findings build
on (e.g. `total_road_length` → density metrics; `average_speed` → delay/LOS;
`connected_components` → a future "network disconnected" finding).

The production observations are intentionally **independent**. The dependency
resolver and cache are proven in tests via **fixture plugins** with a real
dependency chain (A→B→C) and a cycle case — so ordering and single-compute
caching are exercised without forcing an artificial dependency into shipped
observations.

---

## Engine

- **registry.py** — stage-generic registration (observations now; metrics /
  findings / recommendations later through the same API).
- **dependency_graph.py** — topological ordering from declared `requires`;
  detects cycles; supports running a requested subset + its transitive deps.
- **cache.py** — per-run memoization keyed by snapshot identity + plugin id, so
  shared computations run exactly once. Snapshot immutability makes this safe.
- **pipeline.py** — `run(snapshot, only=None) → AnalysisResult`: resolve order,
  execute, memoize, collect results + metadata.

**AnalysisResult** — `{ observations: {id: result}, metadata: {source_kind,
is_running, snapshot_hash, generated_at} }`, fully JSON-serializable.

---

## API exposure

New on-demand endpoint (e.g. `GET /api/analysis/v2`): build the appropriate
source (Runtime if a simulation is active, else Static), run the pipeline,
return the `AnalysisResult` as JSON. The existing `/api/analysis` and
`AnalysisPanel.tsx` are untouched.

---

## Tests

Leaning on the existing `test_maps` regression framework for deterministic
fixtures:

- **snapshot** — immutability (frozen), unit normalization correctness,
  static-vs-runtime topology parity, runtime vehicle fields populate correctly.
- **engine** — registry; dependency ordering; cycle detection; cache proves a
  shared dependency computes exactly once (fixture plugins).
- **observations** — each of the seven yields exact, deterministic values on a
  known test map; `vehicle_count == 0` and `average_speed` empty-safe when idle.

**Definition of done:** the pipeline runs on both a static and a runtime
snapshot on demand; the seven observations return correct values; the engine is
stage-generic (a later Metric stage would register with zero engine changes);
the existing analysis path is fully intact; full headless suite green.

---

## Explicit M1 non-goals

- No metrics, findings, or recommendations.
- No engineering standards or judgments.
- No UI changes; no simulation or renderer changes.
- The existing `/api/analysis` + `AnalysisPanel` stay exactly as they are.
