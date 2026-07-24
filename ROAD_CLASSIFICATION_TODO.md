# Road Classification — TODO

Tracks the remaining work on the road functional-classification system. The
design review and rationale live in [ROAD_CLASSIFICATION_PLAN.md](ROAD_CLASSIFICATION_PLAN.md);
this file is just the running checklist.

## Done

- [x] **Semantic layers on `RoadProfile`** — `functional_class`, `context`,
  `design_speed` (mph), `access_control` as optional, migration-free metadata
  in the opaque `road.data["profile"]` dict (`road_style.py`).
- [x] **Design speed → speed-governor** — baked onto each compiled lane segment
  (ft/s) and capped by `rule_design_speed` in `vehicle_decision.py`.
- [x] **Functional class → routing** — `route_weight()` biases Dijkstra edge
  cost so through-trips prefer arterials over locals (`routing.py`).
- [x] **Access control → driveway gate** — `driveway_attach_blocker()` /
  `can_attach_driveway()` block driveways on limited-access roads
  (`road_network.py`, enforced in the API).
- [x] **Presets as templates** — each preset seeds the cross-section *and*
  resolves the four semantic fields (`ROAD_PROFILE_PRESETS`).
- [x] **Inspector UI** — Class / Context / Access dropdowns + Design-mph input
  edit the four fields (`web/src/Inspector.tsx`).
- [x] Guarded by `test_road_classification.py`; full suite green.

- [x] **Context cosmetics (Layer 2)** — `context` (`CONTEXT_RURAL` / `SUBURBAN`
  / `URBAN` / `INDUSTRIAL`) now drives appearance, not just a label. A resolver
  (`context_cosmetics` / `context_verge_regions` / `context_curb_lines` in
  `road_style.py`) maps each context to a cosmetic **verge** — the strip just
  outside the built shoulder — plus an optional **curb** line: urban = tight
  kerbed sidewalk, suburban = grass lawn, rural = wide earth ditch, industrial =
  paved apron. Served as `verge_bands` / `curb_lines` from `api_server.py` and
  painted by `web/src/renderer.ts` (a new layer under the shoulder + curb
  strokes with the markings).
  - Purely visual: the verge is drawn **outside** `total_width()` and never
    feeds it, the carriageway, the lane graph, junctions, or routing. Retagging
    a road repaints the verge but cannot move a lane, edge, or junction mouth.
  - Guarded by `test_road_classification.py` §6, incl. the no-width-regression
    invariant across all contexts. Verified in-browser (rural verge wider / no
    curb vs urban sidewalk + curb; width unchanged).

- [x] **Land-use suggestions (Phase 5)** — `land_use.suggest_road_profile`
  reads the buildings around a road and proposes a plausible `context` /
  `functional_class` (+ a matching cross-section template): residential →
  suburban local, commercial → urban collector, industrial → industrial, empty
  → rural local. Exposed read-only at `GET /api/road/{id}/suggest-profile`; the
  Inspector's **"Suggest from surroundings"** button pre-fills the dropdowns as
  a *proposal* with a rationale, and the user clicks **Apply** — so it seeds but
  never overrides explicit edits (seed-then-edit).
  - Guarded by `test_land_use.py` (mapping + tie-break + read-only invariant).
    Verified in-browser end-to-end.

## To do

All planned items are complete. Anything below the line stays out of scope
until there is a concrete reason to revisit it.

## Notes

- Keep the **authored + template-seeded** model (see plan §4): semantic fields
  are metadata a resolver reads to seed the cross-section, never a per-frame
  generator.
- `ROAD_WIDTH_SCALE = 2.6` still means rendered widths ≠ the true feet stored
  (plan §6, "smaller flags"). Revisit only if engineering accuracy becomes a
  selling point.
- Jurisdiction standard packs (NYSDOT/AASHTO/NACTO) remain out of scope — a
  future template *pack*, not architecture (plan §6).
