# Analysis Platform — Milestone 3 (Horizontal Geometric Design)

> Implementation contract. Milestone 3 adds the **second engineering vertical**
> — roadway geometry — on top of the pipeline M1 proved and M2 exercised. It is
> deliberately scoped to **horizontal (plan-view) geometry only**: every M3
> analysis is derivable from the 2D world the simulator actually models. The
> flagship analysis is **Horizontal Stopping Sight Distance (2D approximation)**,
> carried end-to-end: geometry observation → SSD metric → deficiency finding →
> recommendations. The engine does not change; M3 is new plugins plus one
> snapshot extension.

Design rationale and the full multi-milestone vision live in
[`Flowscape/Analysis_System_Planning`](Flowscape/Analysis_System_Planning).
Prior contracts: [ANALYSIS_PLATFORM_M1.md](ANALYSIS_PLATFORM_M1.md) (core
framework), M2 traffic-operations slice (tracked in [TODO.md](TODO.md)).

---

## Guiding principle: analyses are constrained to the model's fidelity

The simulator has a **2D plan-view** world: node positions, road centerlines
(quadratic Béziers), lane counts, controls. It has **no terrain, elevation,
grade, or cross-section in the vertical plane.** Rather than pretend otherwise,
M3 constrains itself to analyses that are *technically honest* at that fidelity.

This is why M3 is titled **Horizontal** Geometric Design, not "Geometric
Design." Vertical geometry (grade, crest/sag curves, vertical SSD,
superelevation) is not a missing *plugin* — it is a missing *dimension of the
simulation*. When Flowscape gains elevation, a separate **Vertical Geometry**
observation package is added on top of that new sim capability, without touching
any horizontal analysis shipped here. Keeping the boundary at the world model's
edge is what makes the results trustworthy.

---

## Where M3 sits

```
Snapshot → Observations → Metrics → Findings → Recommendations → Applications
           └── M1 ──┘      └───────── M2 (traffic vertical) ─────────┘
           └──────── M3 adds the HORIZONTAL-GEOMETRY vertical ────────┘
```

M2 proved a full four-stage vertical (`traffic_volume → road_capacity →
vc_ratio → level_of_service → over_capacity → add_capacity`). M3 lays a
**parallel** vertical in the `geometry` category beside it, registered through
the identical registry/dependency/cache machinery — proving the pipeline carries
a **second** engineering domain with no engine edits, only new `geometry.py`
modules in `observations/`, `metrics/`, `findings/`, `recommendations/`, and new
tables in `standards.py`.

---

## M3 charter — the horizontal analysis menu

M3 opens the horizontal-geometry domain. Following M2's shape, **one flagship
vertical ships fully** (Horizontal SSD), and the rest are **additive plugins on
the same snapshot foundation**, specified here so the scope is fixed even where
implementation follows the flagship:

| analysis                          | derivable from 2D? | M3 status            |
|-----------------------------------|--------------------|----------------------|
| Horizontal curve radius           | yes                | **foundation** (snapshot fact + observation) |
| **Horizontal SSD (plan-view)**    | yes                | **flagship — full vertical** |
| Horizontal alignment consistency  | yes                | additive plugin      |
| Design-speed consistency          | yes                | additive plugin      |
| Intersection spacing              | yes                | additive plugin      |
| Access (driveway) spacing         | yes                | additive plugin      |
| Functional-class consistency      | yes                | additive plugin      |
| Block length                      | yes                | additive plugin      |
| Network connectivity measures     | yes                | additive plugin (extends M1 `connected_components`) |
| Curve advisory speed              | yes                | **future**           |

Everything on this list is a function of node positions, centerline geometry,
lane/class metadata, and spacing between features — all present in the 2D model.

**Explicitly out of M3** (needs a dimension the simulator does not model):
vertical SSD, crest/sag curves, grade, passing sight distance, decision sight
distance, superelevation, drainage, cross slope. These are **not** deferred
plugins — they are deferred until the *simulation* gains vertical geometry.

---

## The core challenge: horizontal geometry is not in the snapshot yet

Everything M2 needed was already a fact the snapshot carried or the session
measured. **SSD is different** — it needs roadway *shape*, and today's
`RoadSnapshot` has only `length_ft`, lane counts, and an optional `design_speed`
(`None` until the P1 classification system re-lands). There is no curve radius or
deflection anywhere in the snapshot.

So M3's first work is a **snapshot extension at the builder boundary** — the one
module allowed to know sim internals
([`analysis/snapshot/builder.py`](Flowscape/analysis/snapshot/builder.py)).
Roads are quadratic Béziers defined by a `curve_offset` control point
([road_geometry.py:50](Flowscape/road_geometry.py:50)), so horizontal curve
radius and deflection are **derivable geometry**, not new authored data — the
builder converts raw Bézier/centerline geometry into canonical plan-view facts,
and no downstream stage ever touches the live network.

### New `RoadSnapshot` fields — plan-view facts only

The snapshot carries **only what exists in the 2D world model**. No grade field;
a `grade_pct = 0.0` stand-in would be a fabricated fact and is explicitly not
added.

| field                          | units | source                                              | straight road |
|--------------------------------|-------|-----------------------------------------------------|---------------|
| `governing_curve_radius_ft`    | ft    | controlling (tightest) radius along the centerline   | `None` (no curve) |
| `horizontal_deflection_angle_deg` | deg | total plan-view turn angle start-tangent→end-tangent | `~0.0`        |

`length_ft` and `design_speed` already exist on `RoadSnapshot`. The name
`governing_` states what the value *represents* — the radius that controls the
analysis — leaving `min_`/`average_`/`at_station_` radius as future sibling
observations rather than baking one interpretation into the field name.

---

## The Horizontal SSD vertical, stage by stage

> **Documented assumption:** this is **Horizontal Stopping Sight Distance
> (2D / plan-view approximation)** — sight distance limited by *horizontal*
> curvature and a lateral clearance, with no vertical component. Named this way
> so future developers see the fidelity boundary explicitly.

### 1. Observation — `geometry` category

**`horizontal_curvature`** (id `horizontal_curvature`, category `geometry`)
Reads `governing_curve_radius_ft` (and `horizontal_deflection_angle_deg`) off
each road and packages per-road values into `detail["per_road"]`, with the
network roll-up `value` = the **sharpest** (smallest finite) radius, or `None`
when every road is straight. Purely factual — no standard applied. Seeds the
vertical exactly as `traffic_volume` seeded M2.

### 2. Metrics — `geometry` category

**`required_ssd`** (requires: `()`)
Plan-view AASHTO stopping sight distance from design speed, per road:

```
SSD = 1.47·V·t  +  V² / (30·(a/32.2))
```

`V` = design speed (mph), `t` = perception-reaction time, `a` = deceleration
rate. **No grade term** — the plan-view model is flat by definition, so the
downgrade correction is absent (not zeroed-in as a fake input). Every constant
comes from `standards.py`, including the **design-speed default** applied when a
road's `design_speed` is `None` (pre-P1) — the same graceful-degradation pattern
capacity uses for `functional_class`. Per-road required SSD in
`detail["per_road"]`; network `value` = max required SSD.

**`available_ssd`** (requires: `horizontal_curvature`)
Sight distance a driver actually has on a curve, limited by lateral clearance
`M` to the sight obstruction on a curve of radius `R` (AASHTO horizontal
sightline relation):

```
S = (R / 28.65) · arccos((R − M) / R)
```

`M` (middle-ordinate clearance, ft) comes from `standards.py` — an assumed clear
distance from centerline to the obstruction until a roadside-obstruction model
lands (Option A, per prior decision). A straight road
(`governing_curve_radius_ft is None`) is **not sight-limited by curvature** →
available SSD unconstrained (`None`/`inf`), never flagged. Per-road available SSD
in `detail["per_road"]`; network `value` = worst (smallest) available SSD.
*(Deflection angle bounds the curve's arc length; using it to cap available SSD
on short curves is a documented refinement, not required for the M3 slice.)*

### 3. Finding — `geometry` category

**`ssd_deficiency`** (requires: `required_ssd`, `available_ssd`)
Flags every **curved** road where `available_ssd < required_ssd`. Evidence per
road carries `required_ft`, `available_ft`, `margin_ft` (available − required;
negative = deficient), `design_speed_mph`, and `radius_ft` — the exact traceable
structure the planning doc's SSD example shows. Severity scales with the deficit
via `standards.py` bands. Empty evidence = honest all-clear, matching M2's
`over_capacity`.

### 4. Recommendations — `geometry` category

**`improve_sight_distance`** (requires: `ssd_deficiency`)
Per flagged road, the three horizontal levers, each with expected benefit and
trade-offs:

- **Increase curve radius** — flattens the curve, raising available SSD (costly;
  needs right-of-way).
- **Reduce design speed** — lowers required SSD (reduces mobility/throughput).
- **Remove the sight obstruction / widen the clear zone** — raises available SSD
  by increasing `M` (needs roadside right-of-way).

Advisory and traceable only — never an automatic edit to the network.

---

## Standards additions — `metrics/standards.py`

New numbers land in the existing swappable standards module (the M1 principle-5
home), as a horizontal-`geometry` section beside the traffic tables:

```python
# Horizontal SSD kinematics (AASHTO Green Book, simplified educational profile)
PERCEPTION_REACTION_S = 2.5          # driver PRT
DECELERATION_FPS2     = 11.2         # comfortable braking
# (no grade term — plan-view model is flat by definition)

# Design-speed default when a road has no design_speed yet (pre-P1),
# by functional class, mph — falling back to a global default.
DESIGN_SPEED_BY_CLASS = {"freeway": 65, "highway": 55, "arterial": 40,
                         "collector": 30, "local": 25}
DEFAULT_DESIGN_SPEED_MPH = 30

# Assumed lateral clearance (ft) from centerline to the sight obstruction,
# until a roadside-obstruction model lands. A swappable stand-in (Option A).
DEFAULT_LATERAL_CLEARANCE_FT = 10.0

# SSD deficiency severity bands, by deficit ratio (required − available)/required.
SSD_DEFICIT_MODERATE = 0.10
SSD_DEFICIT_HIGH     = 0.25
```

Swap this profile for an AASHTO/agency standard and **no metric, finding, or
recommendation code changes** — the guarantee M2 proved.

---

## Package layout — additive only

```
analysis/
├── snapshot/
│   ├── models.py      # + governing_curve_radius_ft, horizontal_deflection_angle_deg
│   └── builder.py     # + curve radius/deflection extraction from Bézier/centerline
├── observations/
│   └── geometry.py    # NEW: horizontal_curvature
├── metrics/
│   ├── geometry.py    # NEW: required_ssd, available_ssd
│   └── standards.py   # + horizontal-geometry SSD constants (above)
├── findings/
│   └── geometry.py    # NEW: ssd_deficiency
└── recommendations/
    └── geometry.py    # NEW: improve_sight_distance
```

Registration goes through the same `engine/registry.py` calls M2 uses (wired in
`analysis/__init__.py`). No `engine/` file is touched.

---

## API exposure

None new. Geometry plugins register into the same pipeline, so
`GET /api/analysis/v2` returns a **richer package** (geometry observations,
metrics, findings, recommendations under their `kind` buckets) with **no
endpoint or contract change**. Legacy `/api/analysis` + `AnalysisPanel` stay
untouched, exactly as in M1/M2.

---

## Tests

Extend the `test_maps` regression framework with a **horizontal-geometry fixture
map** — at minimum one straight road and one curve of *known* radius and
deflection — so plan-view SSD math is asserted against hand-computed values:

- **snapshot** — `governing_curve_radius_ft` and `horizontal_deflection_angle_deg`
  are correct on the known curve and radius `None` / deflection ~0 on the
  straight road; new fields are frozen/immutable; static-vs-runtime parity
  (geometry is source-independent).
- **observation** — `horizontal_curvature` returns exact per-road radii and the
  sharpest-radius roll-up; all-straight map → `value is None`.
- **metrics** — `required_ssd` matches the hand-computed AASHTO value for the
  fixture design speed (and the default when `design_speed is None`);
  `available_ssd` matches the horizontal-sightline formula on the known curve; a
  straight road is unconstrained.
- **finding** — `ssd_deficiency` fires on a curve deliberately too sharp for its
  design speed, clears when flattened, grades severity by the standards bands;
  evidence carries required/available/margin/radius.
- **recommendation** — `improve_sight_distance` proposes the three horizontal
  levers per flagged road and nothing when the finding is clear.
- **standards swap** — changing the design-speed default or lateral clearance
  changes results with no plugin-code change (proves principle 5 again).

**Definition of done:** the horizontal-geometry vertical runs on both static and
runtime snapshots; radius and deflection extract correctly at the boundary; the
four stages return correct, traceable plan-view SSD results on the fixture map;
the engine is unchanged; M1/M2 results and the legacy path are fully intact;
full headless suite green.

---

## Explicit M3 non-goals

- **No vertical geometry of any kind** — vertical SSD, crest/sag curves, grade,
  passing sight distance, decision sight distance, superelevation, cross slope,
  drainage. These require a dimension the simulator does not model and belong to
  a future **Vertical Geometry** package built on a future sim capability, not to
  M3.
- **No fabricated inputs** — no `grade_pct` stand-in field; the snapshot carries
  only facts the 2D world actually contains.
- No roadside-obstruction geometry model (available SSD uses a standards
  clearance constant — Option A; the real model is a later refinement).
- No engine changes; no UI changes; no simulation or renderer changes.
- Does **not** depend on P1 classification landing — `design_speed` falls back to
  the standards default, exactly as capacity does for `functional_class`.
```
