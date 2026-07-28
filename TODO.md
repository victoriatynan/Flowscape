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

## Backlog / deferred (no action until there's a concrete reason)

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
