# 08 · UI, Icons & Components

> **Tier:** Implementation · **Status:** Migrated (from `UI-Graphic-Design`, `UI-new`)
> **Related:** [01 Art Bible](01_Art_Bible.md) · [04 Linework](04_Linework_Ink.md) · [09 QA](09_QA_Decision_Framework.md)

Concrete component specs. Every component obeys the illustration rules in docs 01–07: hand-drawn
ink borders, watercolor fills, paper texture, organic silhouettes — no clean vector frames.

## Layout — four workspaces

```
┌──────┬───────────────────────────┬─────────────┐
│ Left │                           │   Right     │
│ Tool │   Center Simulation       │  Analysis & │
│ Pal- │   Viewport (majority of   │  Inspector  │
│ ette │   the screen)             │   Panel     │
├──────┴───────────────────────────┴─────────────┤
│        Bottom Simulation Control Bar            │
└─────────────────────────────────────────────────┘
```

All panels independently **drag-to-resize, collapse, expand, pin**, with min/max width and
smooth resizing. Resize handles are elegant dividers, not obvious grab bars. The viewport
auto-resizes to reclaim freed space.

### Left Tool Palette
Narrow vertical toolbar, **icons only** (no text labels by default). Tools: Selection, Roads,
Nodes, Buildings, Traffic Controls, Terrain, Layers, Analysis, Simulation, Settings. On hover:
tooltip appears (toolbar may temporarily widen to reveal labels); active tool gets a subtle
highlight + gentle glow. Decorative divider separates it from the viewport.

### Center Simulation Viewport
The visual focus. Clean background with only faint decorative elements; decoration confined to
the borders so it never interferes with editing. Roads, intersections, vehicles, overlays, and
handles stay highly visible. Every rendered element adopts the illustrated style — see
*Simulation rendering* below.

### Right Analysis & Inspector Panel
Vertically scrollable, information-driven. Collapsible sections as **framed information cards**
(like chapters in a reference book): Selected Object, Road/Intersection/Building Properties,
Simulation Controls, Time Controls, Demand Analysis, Traffic Statistics, Network Metrics, Route
Inspector, Layer Manager, Performance Metrics, Graphs, Debug Info.

### Bottom Simulation Control Bar
Independent of the side panels; resizable in **height** (drag top edge to expand into a dashboard
or collapse into a compact status strip). Contains: Play, Pause, Resume, Stop, Restart, Step
Forward/Backward, Speed, Timeline Scrubber, Current Time & Date, Day/Night Indicator, Demand
Timeline, Bookmarked Events, live stats (vehicle counts, congestion, performance). The timeline
resembles a finely engraved surveying ruler with graduations and tick marks rather than a digital
slider.

## Information cards

Replace flat panels with structured cards: soft layered appearance, decorative (drawn) borders,
gentle shadows, title section, organized spacing, clear hierarchy. Cards resemble pages or framed
inserts in a historical reference book.

## Borders & dividers

Every panel and interactive element has a **visible drawn ink border** — decorative illustration,
not a software frame. Fine double lines, geometric corner details, botanical corner flourishes
(curled vines, small leaves, ink flourishes), compass-inspired dividers, measuring-rule accents.
Borders never look like clean vector strokes. Decoration frames content; it never dominates —
recurring motifs generally stay below ~10% opacity and never compete with primary information.

## Icons

Miniature **illustrations**, not simplified symbols — like botanical engravings, individually
drawn by the same artist. Each icon: strong silhouette, variable-width contour, internal
construction lines, material definition, transparent watercolor, surface texture, natural
asymmetry, readable at small sizes. Must read as a black ink silhouette before color.

**Never** use or imitate modern icon libraries (Material, Fluent, SF Symbols, Heroicons, Lucide,
Feather). Motifs: compass, survey tripod, drafting pen, road, bridge, building, traffic signal,
stopwatch, gear, blueprint, ruler, tree, vehicle, layer stack, graph, globe, map pin.

## Typography

Literary, not digital. Preferred faces: **Cormorant Garamond, IM Fell English, EB Garamond,
Junicode**. Headers slightly decorative / engraved feel, uppercase section titles with wide
spacing. Body: readable serif optimized for long reading with excellent contrast. Numerical data:
larger, highly legible numerals like precision-instrument readouts. **Avoid** sans-serif,
geometric, modern display, and tech-inspired type.

## Data visualization

Match the design language — prefer instrument-inspired visuals over plain progress bars: circular
gauges, radial indicators, tick-mark scales, compass-style rings, instrument dials, survey rulers.
Immediately understandable while reinforcing the aesthetic. (Chart color/accessibility: pair with
the `dataviz` guidance when built.)

## Motion

Refined and deliberate — critically damped easing, smooth interpolation, gentle fades, layered
reveals, smooth panel expansion, slight hover elevation, soft glow on active controls, accordion
transitions. **Avoid** bounce, elastic overshoot, snapping, flashing, aggressive scaling, and
energetic/playful animation.

## Simulation rendering

Every rendered element adopts the illustrated style: roads, lane markings, medians, curbs,
sidewalks, buildings, trees, vehicles, traffic controls, selection highlights, route previews,
pathfinding overlays, heatmaps, terrain, grid, background textures. Roads resemble carefully
inked transportation routes in an illustrated atlas — soft inked borders, slightly organic
outlines — not flat gray CAD geometry. The editor grid becomes an illustrated **surveying grid**:
fine pen lines, uneven ink density, measurement ticks, coordinate annotations, compass references.
The simulation stays perfectly readable while feeling like an animated page from an illustrated atlas.

## ⚠ Note
Sources describe "engraved brass buttons/medallions." Reconcile with the no-metallic decision in
[06 Color](06_Color_Theory.md) — either matte pigmented "brass" tone or a genuine metallic finish.
