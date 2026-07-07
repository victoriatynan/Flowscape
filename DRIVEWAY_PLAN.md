# Driveways & Access Points — Plan

Goal: get cars onto the road **fluidly and legibly** instead of teleporting onto
the centerline through a single point. We separate the three things currently
collapsed into one node — **the building** (where demand comes from), **the
driveway** (where it enters the road), and **the road** (the network).

This is both a simulation change (throughput, realistic merging) and a
**visual** change (cars emerge from buildings, queue in driveways, merge) — see
the [Visuals](#visuals) section, which threads through every phase.

---

## Why

Measured today (test city, slowed clock): a high-capacity building can't release
its fleet through one connection node — cars serialize behind the spawn-clearance
gate and the surplus expires. Three concrete problems:

1. **Throughput** — one origin emits cars one at a time; an apartment of 40 can't
   clear them through a single driveway.
2. **Spawn location** — cars appear on the road centerline, which reads as
   "popping onto the road."
3. **Legibility** — there's no visible link between a building and the road.

---

## Design — a driveway is a short, narrow *road* (model B)

A driveway is modeled as a real (narrow) road, not a special case:

```
building ──[ driveway road ]──▶ [ junction ] ═══ main road
            (narrow profile)      yields to through-traffic
```

- The building attaches to a small **entrance node** sitting off the main road.
- A short **driveway road** (narrow profile) connects the entrance node to the
  main-road node, which becomes a **junction**.
- Cars **spawn at the entrance node** (off the main road), drive the driveway,
  and **yield** at the junction — waiting for a gap in through-traffic before
  merging (the chosen merge rule).

The big win of model B: it dissolves the hard parts into systems that already
exist, rather than building parallel ones.

### Why this reuses everything
| Concern | Handled by (existing) |
|---|---|
| The merge / yield | `intersection_control.IntersectionControl` at the junction node |
| Routing onto the network | `find_lane_path` / `lanes_departing_node` — routes through the driveway automatically |
| Off-road spawn | the origin node is simply the entrance node; the spawn pipeline is unchanged |
| Off-road queue/buffer | the existing perception + car-following rule, on the driveway lane |
| Drawing the driveway | the road renderer draws it from its (narrow) profile |
| Persistence | `map_data` already serializes nodes + roads |

Confirmed against the code: junctions are **reservation-controlled by default**
(`DEFAULT_INTERSECTION_CONTROL = CONTROL_RESERVATION`), so a driveway junction is
**collision-safe with zero new code** — a driveway car only enters when it can
reserve the conflict zone. A true **yield** (through-traffic keeps priority) is a
declared-but-unimplemented type (`CONTROL_YIELD`) that the framework already
anticipates as a `ReservationController` subclass ("no priority traffic, then
`super().can_enter()`") — adding it is "a controller class + a `CONTROLLER_TYPES`
entry," exactly like the existing `StopSignController`.

So the only genuinely new pieces are: a **narrow driveway road profile**, the
small **`YieldController`** (framework-ready), and **editor plumbing** to
auto-create/destroy a building's driveway(s).

**Feasibility verified (headless, against current code):** with a through road
`A–B–C` and a driveway road `D–B` (D a dead-end entrance node), `resolve_route`
routes `D → C` and `D → A` successfully, and `spawn_on_route` places the car on
the driveway near D — **off the main road** — with no sim changes. The routing,
off-road spawn, and (default reservation) merge all work out of the box; the new
work is confined to the profile, the editor plumbing, and the optional yield.

---

## Phases

### Phase D1 — Driveway road + off-road spawn
**Goal:** placing a building creates a driveway; its cars spawn off the road and
drive on.

- Define a **"driveway" road profile** (1 narrow lane) in `road_style`.
- On building placement, auto-create an **entrance node** (off-road, near the
  footprint, facing the road) and a **driveway road** entrance → main node;
  set `connection_node_ids = [entrance node]`.
- **Attachment (decision):** today `_place_building` requires clicking an existing
  road **node**. First cut = connect the driveway to that clicked node
  (**node-attach**): minimal and works now, but driveways land at endpoints /
  intersections. Realistic **mid-block** driveways need a **road-split** primitive
  (split a road at a point, insert a junction node, rewire the lane graph) that
  doesn't exist yet — defer as a follow-on. **Recommend node-attach first.**
- Routing + spawn now originate off-road through the driveway, with **no change
  to the spawn pipeline** (the origin node is just the entrance node).
- **Lifecycle:** the building owns its driveway — store the driveway road/entrance
  ids on `Building.data` (editor bookkeeping) so deleting the building removes
  them.
- **Visual:** the driveway draws as a narrow road for free.
- **Verify:** a car spawns on the driveway (off the main centerline) and drives
  onto the road; placing/deleting a building cleanly adds/removes its driveway;
  determinism intact (geometry is pure).
- **Risk:** medium — editor lifecycle + a new profile; sim path largely reused.

### Phase D2a — Merge safety (free, via default reservation)
**Goal:** driveway cars merge without collisions or dangerous cut-ins.

- The driveway junction is a normal node with 2+ roads, so it is
  **reservation-controlled by default** — no new controller. A driveway car
  enters only when it can reserve the conflict zone; cars back up **on the
  driveway** (off-road) via the existing car-following rule.
- **Test fixture:** the test city has one node per building and can't exercise
  merging — add a fixture (a through-road + a building with a driveway).
- **Verify:** driveway cars merge with no overlap; a queue forms on the driveway
  under load; `test_spawn_clearance` stays green.
- **Risk:** low — reuses the default reservation control.

### Phase D2b — Through-traffic priority (`YieldController`)
**Goal:** the driveway defers to the main road, so busy roads don't stutter.

- Default reservation is first-come-first-served, so a driveway car can
  occasionally make through-traffic wait. With many driveways that makes main
  roads choppy — so this is **not cosmetic**; it's needed for realistic flow at
  scale.
- Add `YieldController(ReservationController)` (framework-anticipated: defer to
  conflicting priority movements, else `super().can_enter()`), register it in
  `CONTROLLER_TYPES`, and set driveway junctions to `CONTROL_YIELD`.
- **Verify:** through-traffic keeps priority; driveway cars wait for a gap;
  `test_intersection_control_ui` still passes.
- **Risk:** low-medium — one controller subclass; the framework is built for it.

### Phase D3 — Egress throughput  ✅ done (corrected from the plan's premise)
**Goal:** a big building can clear its fleet faster than one-car-at-a-time.

**The plan's original premise was wrong** and measurements corrected it:
- *"More driveways = more throughput"* — **false** here. Controlled tests showed
  the binding constraints are the spawn queue's global rate R (~4/s, deliberate
  for watchability) and the concurrency cap + travel time — not the per-entrance
  clearance. Worse, each extra driveway adds a **yield junction** that slows
  through-traffic, so multiple driveways did *worse*. (Multiple driveways to the
  *same* node also don't all route — a lane-graph limitation.)
- The real lever, isolated cleanly (rate/cap/expiry/yield removed), was the
  **spawn point's spatial capacity**: throughput scaled **linearly** with spread
  spawn points (0.5 → 1.0 → 1.5 cars/s for 1/2/3), and a single entrance clears
  only ~0.5/s — below R.

**What shipped: a staggered SPAWN ZONE** (`traffic_sim._spawn_on_path`). A car
takes the first clear slot along the departing lane (stepping back by
`SPAWN_CLEARANCE_FT`) instead of always the start, so a burst fills the driveway
nose-to-tail with **no overlap and no new junctions**. Longer driveway = bigger
zone. Result: single-entrance 0.5→~0.67/s (more for longer driveways), and the
test-city demo loss **57% → 46%**. Modest but real, with no downside.
- The multi-driveway **model** (`add_driveway_to_building`, list storage,
  lifecycle) is kept as a **realism** feature (multi-exit buildings for D4), NOT
  a throughput lever.
- **Guarded by** the reworked test_spawn_clearance.py (staggering + full-lane gate,
  no-overlap invariant preserved).
- **Deferred:** editor UX to add/remove driveways; the real throughput ceiling is
  R / cap / clock speed (a separate spawn-queue decision, traded against
  watchability).

### Phase D4 — Visual polish
**Goal:** make access read richly.

- Refine the driveway/apron styling so it reads as a driveway, not a thin road.
- **Emergence** — fade/scale a car in over ~0.3 s as it pulls out of the entrance.
- **Parking-lot footprint** with marked exits for large buildings (several
  driveways from one lot).
- **Visible source queue** / building "active" indicator while emitting.
- **Verify:** aprons stay in the static render cache (re-profile); emergence reads
  smoothly; big buildings show legible, congested egress.
- **Risk:** low, additive, mostly rendering.

---

## Visuals

Visual payoff threads through the phases:
- **D1** — driveways appear as narrow roads from each building.
- **D2** — cars visibly wait and merge; queues form on the driveway, off the road.
- **D3** — several driveways feeding a busy building in parallel.
- **D4** — driveway/apron styling, emergence animation, parking lots, source queues.

All colours come from `palette.py`; driveways read as paved stubs off the road.

---

## Cross-cutting guarantees

- **Determinism** — entrance nodes and driveway roads are created deterministically
  on placement; spawn originates at the entrance node; no new RNG. Demand
  generation stays a pure function of day + seed + building type.
- **Performance** — the graph grows by ~2 elements (entrance node + driveway road)
  per driveway. Lane graph and routing scale linearly; driveways are short and
  local. Driveway rendering lives in the **static cache** (free per frame). Note:
  each driveway junction is a **reservation-controlled node** running per-junction
  logic each step, so hundreds at city scale add controller work — a perf
  checkpoint, and another reason D2b (yield) helps main-road flow. Watch total
  graph size only at city scale.
- **No-overlap contract** — the spawn-clearance gate still applies at the entrance
  node; `test_spawn_clearance` stays green.
- **Lifecycle** — a driveway belongs to its building: created with it, destroyed
  with it. Saved/loaded as ordinary nodes + roads, tagged as driveways.
- **Layering** — driveway geometry/profile sits with road geometry (low in the
  stack); the yield is intersection-control; drawing is the renderer. Nothing
  points upward.

---

## Decisions

**Resolved:**
- Driveway model = **B, a short narrow road** (reuses lane graph, routing,
  intersection control, renderer).
- Merge rule = **yield**. Confirmed in code: **safety is free** via the default
  reservation control (D2a); **through-traffic priority** is a small
  `YieldController` subclass the framework already anticipates (D2b).
- **Attachment** = **node-attach first** (driveway to the clicked road node);
  mid-block via a **road-split** primitive is deferred.

**Still to pick (carry into D1/D2):**
- **Driveway length** — this *is* the off-road buffer capacity (longer = more cars
  queue before backpressure → fewer expiries, more space used).
- **Entrance-node placement** — where on the footprint the driveway meets the
  building (edge facing the road).

---

## Progress checklist

### D1 — Driveway road + off-road spawn  ✅ done (guarded by test_driveways.py)
- [x] "Driveway" narrow road profile in `road_style` (+ `DRIVEWAY_ROAD_WIDTH`)
- [x] Auto-create entrance node + driveway road on building placement (node-attach)
- [x] Building owns its driveway ids (lifecycle: delete with building)
- [x] Test: off-road spawn + drive-on; place/delete round-trips cleanly
- [x] Update `create_test_city` so its buildings use driveways (so B+T shows them)
- [ ] (Deferred) road-split primitive for mid-block driveways

### D2a — Merge safety (default reservation, no new controller)  ✅ done
- [x] Driveway test fixture (through-road + building) — in test_driveways.py
- [x] Merges with no overlap; demo flows through driveway junctions

### D2b — Through-traffic priority  ✅ done
- [x] `YieldController(ReservationController)` + register in `CONTROLLER_TYPES`
      (`_approach_distance` lifted to the base so stop-sign + yield share it;
      yield_gap setting in the schema)
- [x] Driveway junctions set to `CONTROL_YIELD` (in `add_building_with_driveway`)
- [x] Test: through keeps priority, driveway waits for a gap; suite green
- Note: per-node control means a shared intersection becomes yield wholesale
  (safe — turns yield to straights, base reservation still prevents collisions).
  Isolating the yield to just the driveway approach wants mid-block driveways
  (the deferred road-split).

### D3 — Multiple driveways
- [ ] Building supports several entrance nodes + driveway roads
- [ ] Editor UX to add/remove driveways
- [ ] Test: N driveways clear the fleet faster; loss drops

### D4 — Visual polish
- [ ] Driveway/apron styling
- [ ] Emergence fade/scale on spawn
- [ ] Parking-lot footprint + marked exits; visible source queue

### Definition of done (per phase)
- [ ] Behaviour matches the phase goal; no regressions
- [ ] Deterministic; driveway rendering stays cached
- [ ] Full headless test suite green
