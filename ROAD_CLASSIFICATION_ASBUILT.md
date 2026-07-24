# Road Classification — As-Built Implementation Spec

Companion to [ROAD_CLASSIFICATION_PLAN.md](ROAD_CLASSIFICATION_PLAN.md) (the
design review / rationale) and [ROAD_CLASSIFICATION_TODO.md](ROAD_CLASSIFICATION_TODO.md)
(the checklist). This document captures the **concrete implemented logic** —
exact values, resolvers, and wiring — for the road classification system.

> **Why this file exists:** the system had been fully implemented in the working
> tree across `road_style.py`, `routing.py`, `vehicle_decision.py`,
> `traffic_sim.py`, `road_network.py`, `api_server.py`, `land_use.py`, and the
> web client (`types.ts`, `api.ts`, `renderer.ts`, `Inspector.tsx`), guarded by
> `test_road_classification.py` and `test_land_use.py`. Those working-tree edits
> were reverted to keep git clean; **this document preserves the full
> implementation and exact values so the work can be re-applied.** Everything
> below is an as-built spec, not currently-committed code.

---

## §1 — Overview: five semantic layers

A road's *cross-section* (how it's drawn: lanes, markings, shoulders) is already
the source of truth in `RoadProfile`. This system adds four **semantic** fields
that describe *what a road is*, independently of how it's drawn:

| Layer | Field (`RoadProfile`) | Type | Drives |
|-------|----------------------|------|--------|
| 1 | `functional_class` | `FUNC_*` str | Dijkstra edge-cost (routing) |
| 2 | `context` | `CONTEXT_*` str | Cosmetic verge/curb (visual only) |
| 4 | `design_speed` | float (mph) | Sim speed-governor cap |
| 5 | `access_control` | `ACCESS_*` str | Driveway-attach gate |

(Layer 3 is cross-section geometry, which the authored profile already owns —
hence the numbering gap. See PLAN §2–§4 for why this maps onto the reviewed
design.)

**Core invariants (do not violate when re-implementing):**

1. **Metadata, not a generator.** These fields are read by *resolvers* to seed
   behavior; never a per-frame generator the renderer runs. The authored
   cross-section stays the source of truth. (PLAN §4 decision: authored +
   template-seeded.)
2. **Migration-free.** All four ride in the opaque `road.data["profile"]` dict.
   No save/load migration; old maps lack the keys and resolve to their preset's
   values (or `None`).
3. **`None` == legacy behavior.** Every field defaults to `None`, and every
   consumer treats `None`/unknown as "no opinion" so a road with no semantic
   metadata behaves exactly as before.
4. **Geometry is never touched by semantics.** Context cosmetics paint *outside*
   `total_width()`; routing weights bias only Dijkstra cost; nothing here moves a
   lane, edge, junction mouth, or the carriageway.

---

## §2 — Vocabularies and constants (`road_style.py`)

Add near the existing edge-style aliases. Single source a UI reads.

```python
# Layer 1 — Functional classification (low → high mobility / low → high access)
FUNC_DRIVEWAY       = "driveway"
FUNC_LOCAL          = "local"
FUNC_COLLECTOR      = "collector"
FUNC_MINOR_ARTERIAL = "minor_arterial"
FUNC_MAJOR_ARTERIAL = "major_arterial"
FUNC_EXPRESSWAY     = "expressway"
FUNC_FREEWAY        = "freeway"

# Layer 2 — Context (surrounding land use; drives cosmetics)
CONTEXT_RURAL      = "rural"
CONTEXT_SUBURBAN   = "suburban"
CONTEXT_URBAN      = "urban"
CONTEXT_INDUSTRIAL = "industrial"

# Layer 5 — Access control (how strictly access is limited; gates driveways)
ACCESS_UNCONTROLLED = "uncontrolled"   # full access (driveways/intersections anywhere)
ACCESS_PARTIAL      = "partial"        # some access management
ACCESS_CONTROLLED   = "controlled"     # limited access (interchanges only)
ACCESS_PRIVATE      = "private"        # a private drive, not a public road

# Ordered vocabularies — the single source a UI reads (low→high mobility;
# open→closed access).
FUNCTIONAL_CLASSES = (FUNC_DRIVEWAY, FUNC_LOCAL, FUNC_COLLECTOR,
                      FUNC_MINOR_ARTERIAL, FUNC_MAJOR_ARTERIAL,
                      FUNC_EXPRESSWAY, FUNC_FREEWAY)
CONTEXTS = (CONTEXT_RURAL, CONTEXT_SUBURBAN, CONTEXT_URBAN, CONTEXT_INDUSTRIAL)
ACCESS_CONTROLS = (ACCESS_UNCONTROLLED, ACCESS_PARTIAL, ACCESS_CONTROLLED,
                   ACCESS_PRIVATE)

# 1 mph = this many ft/s. design_speed is stored in mph (what engineers/UI
# speak); the sim runs in ft/s (VEHICLE_SPEED_FT_S == 44.0 == 30 mph).
FT_S_PER_MPH = 44.0 / 30.0
```

### `RoadProfile` additions

Four fields (all default `None`) and one method:

```python
    # --- Semantic layers (metadata; never affect cross-section geometry) ---
    functional_class: str = None   # FUNC_*  — role in the network
    context: str = None            # CONTEXT_* — surrounding land use
    design_speed: float = None     # mph — feeds the sim speed-governor
    access_control: str = None     # ACCESS_* — how limited access is

    def design_speed_ft_s(self):
        """design_speed (mph) → ft/s, or None when unset. The mph↔ft/s
        conversion lives in exactly one place (the speed-governor calls this)."""
        if self.design_speed is None:
            return None
        return self.design_speed * FT_S_PER_MPH
```

---

## §3 — Layer 1: functional class → routing (`road_style.py` + `routing.py`)

Higher-mobility roads are **cheaper** to route through, so through-trips chain
arterials/expressways and use locals/driveways only for unavoidable first/last-
mile access. Biases only Dijkstra edge cost — geometry and the lane graph are
untouched. `collector == 1.0` so today's default-profile maps route exactly as
before; `None`/unknown → `DEFAULT_ROUTE_WEIGHT`.

```python
# road_style.py
FUNCTIONAL_CLASS_ROUTE_WEIGHT = {
    FUNC_FREEWAY:        0.5,
    FUNC_EXPRESSWAY:     0.6,
    FUNC_MAJOR_ARTERIAL: 0.7,
    FUNC_MINOR_ARTERIAL: 0.85,
    FUNC_COLLECTOR:      1.0,
    FUNC_LOCAL:          1.5,
    FUNC_DRIVEWAY:       3.0,
}
DEFAULT_ROUTE_WEIGHT = 1.0

def route_weight(profile):
    """Relative Dijkstra edge-cost multiplier for routing THROUGH a road of this
    profile's functional class. Unknown/None → DEFAULT_ROUTE_WEIGHT (collector).
    Pure metadata lookup — never touches geometry or the lane graph."""
    return FUNCTIONAL_CLASS_ROUTE_WEIGHT.get(profile.functional_class,
                                             DEFAULT_ROUTE_WEIGHT)
```

Wire into the routing graph builder. Cost of traversing *into* a lane is the
route weight of that lane's road:

```python
# routing.py
from road_style import get_road_profile, offset_polyline, route_weight

def _edge_cost(network, dst_lane_id):
    """Cost of traversing INTO dst_lane_id: the functional-class route weight of
    that lane's road. Biases through-trips onto higher-mobility roads while still
    allowing locals for unavoidable access hops. No functional class →
    DEFAULT_ROUTE_WEIGHT (== old UNIFORM_EDGE_COST), so unclassified maps route
    exactly as before. dst_lane_id is (road_id, dir, lane_index)."""
    road = network.roads.get(dst_lane_id[0])
    if road is None:
        return UNIFORM_EDGE_COST
    return UNIFORM_EDGE_COST * route_weight(get_road_profile(road))

# in build_routing_graph(), replace the uniform cost:
#   edges.setdefault(src, []).append((dst, _edge_cost(network, dst)))
```

---

## §4 — Layer 4: design speed → sim speed-governor

**Authored + template-seeded** model (PLAN §4 decision): design speed is
metadata baked onto each compiled lane segment at compile time, and a *pure*
decision rule reads it. No network lookup in the hot decision loop. (See the
three-layer driver model: add driver concerns as speed-governor rules, never
touch dynamics.)

### Bake it onto the segment (`traffic_sim.py`)

In the segment-compile method, add `design_speed` (ft/s) alongside the existing
per-segment fields, mirroring how `turn_type` is baked onto connections:

```python
segments.append({"kind": "lane", "lane_id": lane_id,
                 "points": pts, "length": _polyline_length(pts),
                 "design_speed": self._lane_design_speed(lane_id)})

def _lane_design_speed(self, lane_id):
    """Design speed (ft/s) of the road carrying lane_id, or None when the road
    has none. lane_id is (road_id, dir, lane_index)."""
    road = self.network.roads.get(lane_id[0])
    if road is None:
        return None
    return get_road_profile(road).design_speed_ft_s()
```

### Read it as a decision rule (`vehicle_decision.py`)

The governor takes the min of all rules' proposed caps. Roads with no design
speed return `INF` (no opinion) → vehicle falls back to its own cruise.

```python
def rule_design_speed(vehicle, ctx):
    """Cap the vehicle at the design speed of the road it is currently on.
    Baked onto each lane segment (ft/s) at compile time, so this rule is pure —
    it reads only the current segment, no network lookup. None → INF (no
    opinion), vehicle falls back to cruise_speed, exactly as before."""
    segs = getattr(vehicle, "segments", None)
    i = getattr(vehicle, "seg_index", 0)
    if not segs or i >= len(segs):
        return INF
    cap = segs[i].get("design_speed")
    return cap if cap is not None else INF

# Register in DECISION_RULES, after cruise, before follow:
DECISION_RULES = (
    ("cruise",       rule_cruise),
    ("design_speed", rule_design_speed),
    ("follow",       rule_following_distance),
    ("approach",     rule_intersection_approach),
)
```

---

## §5 — Layer 5: access control → driveway-attach gate (`road_network.py`)

Freeways/expressways admit traffic only at interchanges, never at a direct
driveway. So a driveway may not attach to a node touched by an
`ACCESS_CONTROLLED` road. Every other access class permits attachment. Enforced
in the **domain model** (raises `ValueError`) with a read-only predicate the
Building tool/API check first for a clean refusal.

```python
from road_style import get_road_profile, ACCESS_CONTROLLED

def driveway_attach_blocker(self, node_id):
    """First limited-access (ACCESS_CONTROLLED) road touching node_id, or None if
    a driveway may attach here. Preview roads ignored (not committed geometry)."""
    for road in self.roads_for_node(node_id):
        if road.is_preview:
            continue
        if get_road_profile(road).access_control == ACCESS_CONTROLLED:
            return road
    return None

def can_attach_driveway(self, node_id):
    """True when a driveway may attach at node_id. Read-only; callers check this
    before placing a building so the user gets a clean refusal, not an error."""
    return self.driveway_attach_blocker(node_id) is None
```

Both `place_building_with_driveway` and `add_driveway_to_building` must call
`driveway_attach_blocker(main_node_id)` **before** creating any state and raise
`ValueError` if blocked — so a refusal never leaves a stranded, driveway-less
building. The API translates this to a 400 (see §8).

---

## §6 — Layer 2: context cosmetics (purely visual verge + curb)

`context` resolves to a cosmetic **verge** — the strip of ground just beyond the
built shoulder that reads as the road's setting — plus an optional **curb** line.
Drawn **additively, outside `total_width()`**. NEVER feeds `total_width`, the
carriageway, the lane graph, junction geometry, or routing. Retagging a road
repaints the verge but cannot move a lane, edge, or junction mouth. A road with
no context gets no verge and renders exactly as before.

### Resolver (`road_style.py`)

```python
CURB_COLOR = (70, 70, 70)   # dark line at the road/verge boundary

@dataclass
class ContextCosmetics:
    """How a context paints the verge just outside the road. Feet are true
    (unscaled); the resolver scales verge_width by ROAD_WIDTH_SCALE. Purely
    visual — no geometry meaning."""
    verge_color: tuple   # rgb fill of the outer verge band
    verge_width: float   # feet of cosmetic band beyond the shoulder (0 → none)
    curb: bool           # stroke a curb line at the road/verge boundary

# Neutral fallback: no verge, no curb → context-less road unchanged.
DEFAULT_COSMETICS = ContextCosmetics((120, 120, 120), 0.0, False)

# Widths differ deliberately so the setting reads at a glance. Cosmetic feet
# only — they never widen the road.
CONTEXT_COSMETICS = {
    CONTEXT_URBAN:      ContextCosmetics((188, 188, 182), 6.0,  True),   # tight kerbed sidewalk
    CONTEXT_SUBURBAN:   ContextCosmetics((120, 150, 92),  8.0,  False),  # grass lawn
    CONTEXT_RURAL:      ContextCosmetics((126, 110, 80),  12.0, False),  # wide earth ditch
    CONTEXT_INDUSTRIAL: ContextCosmetics((122, 122, 126), 5.0,  True),   # paved apron
}

def context_cosmetics(context):
    return CONTEXT_COSMETICS.get(context, DEFAULT_COSMETICS)

def context_verge_regions(sampled_points, profile):
    """[{"polygon": [...], "color": (r,g,b)}, ...] — one verge band per side,
    resolved from profile.context, or [] when no verge. Each band sits OUTSIDE
    that side's built shoulder (side carriageway width + shoulder_width), so it
    never overlaps the body and is NOT part of total_width(). profile is already
    scaled; verge_width is scaled here to match."""
    cos = context_cosmetics(profile.context)
    width = cos.verge_width * ROAD_WIDTH_SCALE
    if width <= 0:
        return []
    regions = []
    # Each side offset by its OWN carriageway + shoulder (mirrors
    # profile_shoulder_regions) so an asymmetric cross-section never shifts the
    # other side's verge.
    for sign, side_width in ((1, profile.left_width()), (-1, profile.right_width())):
        base = side_width + profile.shoulder_width
        inner = offset_polyline(sampled_points, sign * base)
        outer = offset_polyline(sampled_points, sign * (base + width))
        regions.append({"polygon": inner + list(reversed(outer)), "color": cos.verge_color})
    return regions

def context_curb_lines(sampled_points, profile):
    """[polyline, ...] curb strokes at the road/verge boundary when the context
    calls for a curb (urban / industrial), else []. Painted lines, not geometry."""
    cos = context_cosmetics(profile.context)
    if not cos.curb:
        return []
    lines = []
    for sign, side_width in ((1, profile.left_width()), (-1, profile.right_width())):
        base = side_width + profile.shoulder_width
        lines.append(offset_polyline(sampled_points, sign * base))
    return lines
```

### Client render (`web/src/renderer.ts`)

In `renderStatic`, paint the verge as **layer 0** (before the shoulder layer),
then stroke curbs with the markings. In the Heritage/manuscript view, wash each
band ~55% toward the paper color so it reads as a soft tint:

```
// 0. Context verge layer — sidewalk/lawn/ditch/apron beyond the shoulder.
//    Painted first so shoulder + asphalt stack on top; widens only the RENDERED
//    footprint, never geometry.
for road.verge_bands: fill polygon (heritage: lerpColor(band.color, paper, 0.55))
// with the markings:
road.curb_lines.forEach: strokeInkLine(c.points, seed, max(0.8, 0.9 * cam.scale))
```

> **Note (`ROAD_WIDTH_SCALE = 2.6`):** rendered widths ≠ true feet stored (PLAN
> §6 "smaller flags"). The resolver scales `verge_width` by `ROAD_WIDTH_SCALE` to
> match the road body. Revisit only if engineering accuracy becomes a selling
> point.

---

## §7 — Presets as templates (`road_style.py`)

Each preset both seeds the cross-section AND resolves the four semantic fields —
so a preset is a full **template**. Today's preset names muddle function and
context (PLAN §5 old→new mapping): "residential"/"industrial" are really
*context*; "highway"/"expressway" are really *function*. The semantic fields
disentangle that. Add these to the existing `ROAD_PROFILE_PRESETS` entries:

| Preset | functional_class | context | design_speed (mph) | access_control |
|--------|------------------|---------|--------------------|----------------|
| `residential` | `FUNC_LOCAL` | `CONTEXT_SUBURBAN` | 25 | `ACCESS_UNCONTROLLED` |
| `urban` | `FUNC_COLLECTOR` | `CONTEXT_URBAN` | 30 | `ACCESS_UNCONTROLLED` |
| `highway` | `FUNC_MINOR_ARTERIAL` | `CONTEXT_SUBURBAN` | 45 | `ACCESS_PARTIAL` |
| `industrial` | `FUNC_COLLECTOR` | `CONTEXT_INDUSTRIAL` | 35 | `ACCESS_UNCONTROLLED` |
| `expressway` | `FUNC_EXPRESSWAY` | `CONTEXT_URBAN` | 65 | `ACCESS_CONTROLLED` |
| `driveway` | `FUNC_DRIVEWAY` | `CONTEXT_SUBURBAN` | 10 | `ACCESS_PRIVATE` |

> Jurisdiction standard packs (NYSDOT/AASHTO/NACTO) are **out of scope** (PLAN
> §6) — a future template *pack*, not architecture.

---

## §8 — API surface (`api_server.py`)

**`RoadProfileIn`** — add four optional fields; only sent keys merge as
overrides. `design_speed` validated `Field(None, ge=5, le=85)` (mph).

**`POST /api/edit/road/{id}/profile`** — validate each string field against its
vocabulary (`FUNCTIONAL_CLASSES` / `CONTEXTS` / `ACCESS_CONTROLS`) → 400 on
unknown; merge only keys the client actually sent into `profile`.

**Geometry payload (per road)** — add:
- `verge_bands`: `[{polygon, color(hex)}]` from `context_verge_regions`
- `curb_lines`: `[{points, color(hex CURB_COLOR)}]` from `context_curb_lines`
- resolved `functional_class`, `context`, `design_speed`, `access_control`
  (preset seed + overrides, so the inspector shows effective values even when
  only a preset name is stored; `None` is a valid "unset").

**`GET /api/road/{id}/suggest-profile`** — read-only; returns
`suggest_road_profile(net, road)` (see §9). 404 if no such road.

**`POST` create-building** — call `net.driveway_attach_blocker(main_node_id)`
up front; if blocked, raise `HTTPException(400, ...)` before any state changes.

**Presets schema endpoint** — also return
`functional_classes` / `contexts` / `access_controls` (ordered lists) so the
client offers them without hardcoding enums.

---

## §9 — Phase 5: land-use suggestions (`land_use.py`, new module)

Convenience on top of the semantic layers: read the buildings around a road and
propose a plausible `context` / `functional_class` (+ a matching cross-section
template). Real DOT practice reads surrounding land use to classify a road; this
is the toy version.

**Strictly a suggestion** — nothing mutates a road. Returns a proposal the caller
uses to SEED an unset profile; never overrides explicit edits (seed-then-edit).
Kept in its own module so `road_style` stays independent of the demand catalogue
(`destinations`); this is the one place they meet.

```python
DEFAULT_NEARBY_RADIUS = 220.0   # feet; ~a short block

# Dominant surrounding category → (context, functional_class, preset template).
# preset None → leave the cross-section untouched, only propose semantic labels.
CATEGORY_SUGGESTION = {
    RESIDENTIAL:     (CONTEXT_SUBURBAN,   FUNC_LOCAL,     "residential"),
    COMMERCIAL:      (CONTEXT_URBAN,      FUNC_COLLECTOR, "urban"),
    INDUSTRIAL:      (CONTEXT_INDUSTRIAL, FUNC_COLLECTOR, "industrial"),
    EDUCATION:       (CONTEXT_SUBURBAN,   FUNC_COLLECTOR, "residential"),
    PUBLIC_SERVICES: (CONTEXT_URBAN,      FUNC_COLLECTOR, "urban"),
    RECREATION:      (CONTEXT_SUBURBAN,   FUNC_LOCAL,     "residential"),
}

# Tie-break toward higher-intensity land use (tells you more about the road's
# role than a lone house). Higher wins.
_CATEGORY_INTENSITY = {
    INDUSTRIAL: 5, COMMERCIAL: 4, PUBLIC_SERVICES: 3,
    EDUCATION: 2, RECREATION: 1, RESIDENTIAL: 0,
}

# No buildings near → open country → rural local road, no template.
EMPTY_SUGGESTION = (CONTEXT_RURAL, FUNC_LOCAL, None)
```

Helpers (all read-only over the network):
- `_dist_point_to_segment(px,py, ax,ay, bx,by)` — shortest dist P→segment AB
  (straight endpoint segment is a fine proxy even for curved roads).
- `buildings_near_road(network, road, radius)` — buildings whose footprint
  center is within `radius` of the road's endpoint segment.
- `category_counts(buildings)` — `{category: n}`, skipping types not in
  `BUILDING_TYPES`.
- `dominant_category(counts)` — `max` by `(count, intensity)`; `None` if empty.
- `suggest_road_profile(network, road, radius=DEFAULT_NEARBY_RADIUS)` — returns
  `{context, functional_class, preset, dominant, counts, rationale}`. Rationale
  is human-readable, e.g. `"Mostly commercial nearby (3 commercial, 1 residential)."`
  or `"No buildings nearby — open country (rural local road)."`

---

## §10 — Client UI (`web/src/Inspector.tsx`, `api.ts`, `types.ts`)

**`types.ts`** — `GeometryRoad` gains `verge_bands` (`{polygon, color}[]`),
`curb_lines` (`EdgeLine[]`), and nullable `functional_class` / `context` /
`design_speed` (mph) / `access_control`. `RoadPresetsSchema` gains
`functional_classes` / `contexts` / `access_controls` string arrays.
`ProfileSuggestion` interface for the suggest endpoint.

**`api.ts`** — `setRoadProfile` gains the four optional fields;
`suggestRoadProfile(id)` (read-only GET) returning `ProfileSuggestion`.

**`Inspector.tsx`** —
- Three dropdowns (Class / Context / Access) fed by the schema vocabularies,
  plus a "Design mph" number input (`min 5, max 85, step 5`). `pretty()` turns
  `"minor_arterial"` → `"Minor Arterial"`. Empty option `"—"` = unset.
- Values resolve `pendingProfile ?? road.<field> ?? ''`. `applyProfile` sends
  only keys that carry a value (never sends unset ones).
- **"Suggest from surroundings"** button → `suggestRoadProfile`, which pre-fills
  the *pending* dropdowns (proposal, not applied) and shows the rationale hint.
  The user reviews and clicks **Apply** — it never auto-overrides
  (seed-then-edit).

---

## §11 — Tests

- **`test_road_classification.py`** — vocabularies, `route_weight` fallback,
  `design_speed_ft_s` conversion, decision-rule cap + `None`→`INF`, driveway
  access gate, preset templates, and §6 context cosmetics incl. the
  **no-width-regression invariant** across all contexts (verge never changes
  `total_width()`).
- **`test_land_use.py`** — category→suggestion mapping, intensity tie-break, and
  the read-only invariant (suggestion mutates nothing).

---

## §12 — Design principles to preserve on re-implementation

1. Keep the **authored + template-seeded** model (PLAN §4): semantic fields are
   metadata a resolver reads to seed the cross-section, never a per-frame
   generator.
2. `None`/unknown is always a valid "unset" that reproduces legacy behavior at
   every consumer.
3. Add driver concerns (like design speed) as **speed-governor rules**, never by
   touching vehicle dynamics — see the three-layer driver model.
4. Suggestions **seed, never override** — read-only, user-applied.
5. Cosmetics stay strictly outside geometry; the style/geometry separation this
   codebase is built on is non-negotiable.
