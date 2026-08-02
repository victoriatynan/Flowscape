# Flowscape — TODO

The single source of truth for outstanding work. The web migration, the module
refactor, the editor-workflow improvements, and the UI theme system are all
shipped and have been retired from this list. What remains is ranked below by
impact, with the rationale and a definition of done for each.

Architecture rules these items must respect live in [ARCHITECTURE.md](ARCHITECTURE.md).

---

## P1 — Re-apply the road functional-classification system

**Status:** fully designed and previously implemented end-to-end, then reverted
to keep the tree clean. It is **not in the committed code today** (`road_style.py`,
`routing.py`, `vehicle_decision.py`, `road_network.py` carry none of it). The
complete re-application spec — exact constants, resolvers, wiring, and tests —
is preserved in [ROAD_CLASSIFICATION_ASBUILT.md](ROAD_CLASSIFICATION_ASBUILT.md).
Treat that file as the implementation contract; values are to be filled in
manually.

**Why it's first:** it's the largest self-contained chunk of genuinely new
*simulation* behavior on the board, and it's fully specced — the design risk is
already retired. It also unblocks the driveway work below (its access-control
layer is the gate on where a driveway may attach).

**Scope** — four semantic fields on `RoadProfile`, each defaulting to `None`
(legacy behavior), riding in the opaque `road.data["profile"]` dict so there is
no save/load migration:

1. **Functional class → routing** — bias Dijkstra edge cost so through-trips
   prefer arterials over locals (`routing.py`).
2. **Design speed → speed-governor** — a new `min`-cap decision rule, baked onto
   each compiled lane segment; no network lookup in the hot loop
   (`vehicle_decision.py`, `traffic_sim.py`).
3. **Access control → driveway-attach gate** — block driveways on limited-access
   roads in the domain model (`road_network.py`), enforced by the API.
4. **Context → cosmetic verge/curb** — purely visual, painted *outside*
   `total_width()`; never touches the carriageway, lane graph, or junctions.

Then: presets become full templates (seed cross-section + resolve the four
fields), the Inspector gets Class/Context/Access dropdowns + a design-speed
input, and land-use suggestions (`land_use.py`) propose a profile from
surrounding buildings (seed-then-edit, never auto-override).

**Definition of done:** all four layers wired end-to-end; `None`/unknown
reproduces today's behavior at every consumer; geometry provably untouched by
semantics; guarded by `test_road_classification.py` + `test_land_use.py`; full
headless suite green.

---

## P2 — Driveways D3: multiple driveways / multi-exit buildings

**Status:** D1–D3 core shipped (model-B driveways, off-road spawn, default
reservation merge, the `YieldController`, and the staggered spawn zone). The
throughput premise was measured and corrected — **more driveways is a *realism*
feature, not a throughput lever** (each extra driveway adds a yield junction that
slows through-traffic; the real throughput ceiling is the spawn queue's rate/cap
and clock speed, deferred below). Frame this as multi-exit buildings, not faster
egress.

**Remaining:**
- Let a building own several entrance nodes + driveway roads (the model —
  `add_driveway_to_building`, list storage, delete-with-building lifecycle —
  already exists; this is wiring it up as a first-class feature).
- Editor UX to add and remove a building's driveways.

**Definition of done:** a building can carry N driveways placed/deleted cleanly
through the editor; each round-trips through save/load; determinism intact; the
spawn-clearance no-overlap invariant holds (`test_spawn_clearance.py` green).

**Depends on:** P1's access-control gate (a driveway must refuse to attach to a
limited-access road).

---

## P3 — Driveways D4: access visual polish

**Status:** additive rendering work, lowest risk. Nothing below changes
simulation behavior.

**Remaining:**
- Driveway/apron styling so it reads as a driveway, not a thin road.
- Emergence: fade/scale a car in over ~0.3 s as it pulls out of the entrance.
- Parking-lot footprint with marked exits for large buildings.
- Visible source queue / building "active" indicator while emitting.

**Definition of done:** aprons stay in the static render cache (no per-frame
cost); emergence reads smoothly; large buildings show legible, congested egress.

---

## Analysis Platform — read-only engineering analysis layer

Full design + multi-milestone vision:
[ANALYSIS_PLATFORM_M1.md](ANALYSIS_PLATFORM_M1.md) and
[Flowscape/Analysis_System_Planning](Flowscape/Analysis_System_Planning).

A read-only layer that observes an immutable snapshot of simulation state and
produces reusable analysis (observations → metrics → findings → recommendations)
consumed by the Inspector, reports, charts, scenario comparison, lessons, and
assessments. It never influences vehicle behavior, routing, demand, or geometry.

**Milestone 1 — core framework: DONE.** `Flowscape/analysis/` ships the
stage-generic engine (registry, dependency resolver, per-run cache, on-demand
pipeline), the immutable snapshot with a common static/runtime source interface
and unit-normalization boundary, and the seven proof observations (road count,
intersection count, total road length, building count, vehicle count, average
speed, connected components). Exposed non-breaking at `GET /api/analysis/v2`;
the legacy `/api/analysis` + `AnalysisPanel` are untouched. Guarded by
`analysis/tests/` (engine, snapshot, observations, API); full headless suite
green.

**Milestone 2 — Traffic operations: core vertical slice DONE.** The engine now
composes all four stages (observation → metric → finding → recommendation) in one
pass, bucketed by plugin `kind`. Volume is **simulation-derived**: a rolling
per-road traversal counter (`Flowscape/traffic_counter.py`, wired into
`sim_session`) surfaces veh/hr into the snapshot, feeding `traffic_volume`
(observation) → `road_capacity` / `vc_ratio` / `level_of_service` (metrics) →
`over_capacity` (finding) → `add_capacity` (recommendation). Capacity + LOS bands
live in the swappable `analysis/metrics/standards.py`. Exposed through the
existing `/api/analysis/v2` (richer package, no endpoint change). Guarded by
`test_traffic_counter.py` + `analysis/tests/test_metrics.py` / `test_findings.py`
and extended engine/API tests; full suite green.
- **M2 remainder — partially shipped (2026-07-31).** Added on the existing
  engine with **zero core change**: `vehicle_miles_traveled` (metric, volume ×
  length), and a mirror-image operational vertical `excess_capacity` (finding —
  under-utilized/over-built roads, graded off `vc_ratio`) → `right_size_road`
  (recommendation — road diet). Guarded by `analysis/tests/test_extensions.py`.
  **Still deferred (need NEW sim instrumentation, not just a plugin):** delay,
  queue length, and directional (per-direction) V/C all require per-road /
  per-direction counters the snapshot does not yet carry — like `traffic_counter`
  did for volume. `throughput` is redundant with the `traffic_volume` roll-up.

**Milestone 3 — Horizontal Geometric Design: core vertical slice DONE.** Full
contract: [ANALYSIS_PLATFORM_M3.md](ANALYSIS_PLATFORM_M3.md). M3's goal is
**architectural, not exhaustive** — prove the platform supports a completely
different engineering discipline (roadway geometry) with **zero core-engine
changes**, exactly as M2 proved it for traffic operations. Scoped to analyses
derivable from Flowscape's current **2D top-down model**; vertical geometry
(grade, crest/sag curves, vertical SSD, superelevation) is **intentionally
deferred** until the *simulation* supports elevation — a missing dimension of the
sim, not a missing plugin.
- **Fully-implemented vertical slice: Stopping Sight Distance (Horizontal /
  Plan-View Approximation).** The snapshot now carries plan-view geometry facts
  extracted at the builder boundary from the road's quadratic Bézier via the exact
  analytic `analysis/snapshot/geometry_math.py` — `governing_curve_radius_ft` and
  `horizontal_deflection_angle_deg` (no fabricated grade field). Chain:
  `horizontal_curvature` (observation) → `required_ssd` / `available_ssd` (metrics)
  → `ssd_deficiency` (finding) → `improve_sight_distance` (recommendation), added
  as `geometry.py` in each stage folder with **no engine change**. AASHTO SSD
  kinematics, the pre-P1 design-speed default, and the lateral-clearance stand-in
  (Option A) live in the swappable `analysis/metrics/standards.py`. Exposed through
  the existing `/api/analysis/v2` (richer package, no endpoint change). Guarded by
  `analysis/tests/test_geometry.py` (19 tests: geometry math, builder extraction,
  observation, both metrics, finding fire/clear + severity bands, recommendation,
  and two standards-swap proofs); full headless suite green at 149.
- **Remaining horizontal analyses — partially shipped (2026-07-31).** Added on
  the existing engine with **zero core change**, three new verticals: (a) curve
  advisory speed — `curve_advisory_speed` (metric, point-mass safe speed;
  superelevation held at 0 for the flat 2D model, same honesty as SSD's no-grade)
  → `curve_speed_advisory` (finding) → `curve_warning_treatment` (recommendation);
  (b) access management / block length — `block_length` (observation,
  intersection-bounded spacing) → `short_block_spacing` (finding) →
  `consolidate_access` (recommendation); (c) `intersection_density` (network
  metric, intersections per centerline mile). All numbers live in the swappable
  `standards.py`; guarded by `analysis/tests/test_extensions.py`. **Still
  definition-level only:** horizontal alignment consistency, design-speed and
  functional-class consistency (these read the P1 classification fields, which are
  `None` until P1 lands, so they would no-op today), driveway spacing, and other
  network connectivity measures — incremental additions on the same foundation.
- **Milestone 4 — Applications: the Engineering Inspector: flagship DONE
  (2026-07-31).** Full contract: [ANALYSIS_PLATFORM_M4.md](ANALYSIS_PLATFORM_M4.md).
  First milestone to touch the React frontend, under the locked principle **the
  frontend is a presentation layer only**. **Flagship shipped:** a read-only
  analysis region in `Inspector.tsx` that, for the selected road, renders its
  observations/metrics/findings/recommendations pulled from one
  `GET /api/analysis/v2` package and filtered client-side by road id — numbers
  consumed byte-for-byte, zero engineering logic in TS. New `web/src/analysis/`
  (pure `roadAnalysis` projection with loose `String()` id matching, display-only
  cards keyed on the generic result shape so a future same-`kind` plugin surfaces
  with no component change); node/building selections show honest empty states.
  Verified live in-browser + guarded by a new Vitest + Testing-Library suite (12
  FE tests incl. the presentation-only invariant). **Secondary track — started
  and safe:** the legacy `/api/analysis` building-mix and connectivity
  calculations now read platform observations (`building_mix`,
  `connected_components.detail.main_component`) with the endpoint's JSON kept
  byte-compatible (golden `test_convergence.py`); full headless suite green at
  153.
  - **M4 remaining (additive, spec-only):** `day0_demand` observation + full
    reduction of `/api/analysis` to a thin adapter; an **intersection-level
    plugin** (per-node metric/finding under `detail.per_node` / `evidence.node_id`)
    to retire the Inspector's node empty-state; reports, charts, debug overlays,
    scenario comparison, lessons/assessments, optional AI explainer — all later
    consumers of the same results on the interface the Inspector now proves.

**Standards** (HCM capacity/LOS, AASHTO SSD) are configurable implementations
injected into plugins, never baked into the engine.

---

## Backlog / deferred (no action until there's a concrete reason)

- **Road ink reads as scattered dots** — `inkStroke` (canvas roads) stamps loose nib dots that don't overlap into a solid tapered line and don't match the UI's clean SVG lerp lines (`inkPathUri`); tune density/jitter or unify the rasterizer.
- **Mid-block driveways (road-split primitive)** — driveways currently
  node-attach only; realistic mid-block access needs a primitive to split a road
  at a point, insert a junction, and rewire the lane graph. Also what's needed to
  isolate a yield to just the driveway approach rather than the whole junction.
- **Spawn-queue throughput ceiling** — the real limit on egress is the spawn
  queue's global rate `R` (~4/s, deliberately slow for watchability) and the
  concurrency cap, not per-driveway clearance. A separate tuning decision traded
  against watchability.
- **Map Analysis capacity indicators** — demand-vs-capacity bars and congestion
  prediction need a road-capacity model, which is a simulation feature, not a
  panel feature. (The rest of the Map Analysis panel is shipped.)
- **Road classification extras** — jurisdiction standard packs
  (NYSDOT/AASHTO/NACTO) as a future template *pack*, not architecture; and
  revisiting `ROAD_WIDTH_SCALE = 2.6` (rendered widths ≠ true stored feet) only
  if engineering accuracy becomes a selling point.
