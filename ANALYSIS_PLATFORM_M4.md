# Analysis Platform — Milestone 4 (Applications: the Engineering Inspector)

> Implementation contract. Milestones 1–3 built the analysis engine and two
> engineering verticals **entirely behind the API**, under a strict "no UI
> changes" rule. M4 is the turn outward: the **first milestone that touches the
> React frontend.** It ships one flagship application fully — the **Engineering
> Inspector**, which reads the `AnalysisResult` package for the selected road and
> displays its observations, metrics, findings, and recommendations without
> performing a single engineering calculation of its own. The rest of the
> Applications layer (reports, charts, scenario comparison, overlays, lessons,
> assessments) is specified here as additive consumers of the **same** results,
> to be built on the interface the Inspector proves. As a secondary, incremental
> track, M4 begins collapsing the legacy `/api/analysis` duplicate-calculation
> path into a thin adapter over the platform.

Design rationale and the full multi-milestone vision live in
[`Flowscape/Analysis_System_Planning`](Flowscape/Analysis_System_Planning).
Prior contracts: [ANALYSIS_PLATFORM_M1.md](ANALYSIS_PLATFORM_M1.md) (core
framework), [ANALYSIS_PLATFORM_M3.md](ANALYSIS_PLATFORM_M3.md) (horizontal
geometry), M2 traffic-operations slice (tracked in [TODO.md](TODO.md)).

---

## Guiding principle: the frontend is a presentation layer only (locked)

> **The React frontend consumes serialized `AnalysisResult`s and never performs
> engineering logic, calculation, or interpretation. The Analysis Platform
> remains the single source of truth for engineering knowledge.**

This is the M4 analog of the backbone principle that carried M1–M3 ("no engine
changes"): where the *engine* was closed to modification and every new analysis
arrived as a plugin, the *frontend* is closed to engineering logic and every
displayed conclusion arrives already computed in the `AnalysisResult`. The
Inspector decides **how** to show a V/C ratio, a severity, an SSD margin — never
**what** those values are, whether they are good or bad, or what to do about
them. Those are the platform's answers, serialized and consumed verbatim.

Two consequences the contract holds itself to:

1. **No thresholds, no formulas, no standards in TypeScript.** If a number needs
   comparing, judging, banding, or unit-converting, that already happened in a
   plugin and rides in the result (`value`, `units`, `severity`, `evidence`,
   `explanation`, `items`). The frontend that recomputes any of it is a bug.
2. **Result-shape-driven rendering, not plugin-id-driven rendering.** Inspector
   presentation keys on the *generic* result contract — `kind`
   (observation/metric/finding/recommendation), `category`, `severity`, `units`,
   `detail.per_road`, `evidence`, `items` — not on specific plugin ids like
   `vc_ratio` or `ssd_deficiency`. A new plugin of an existing `kind` therefore
   surfaces in the Inspector with **no component change**, mirroring "a new
   metric registers with no engine change." A genuinely new *presentation shape*
   may add a renderer; it still adds no engineering logic.

---

## Where M4 sits

```
Snapshot → Observations → Metrics → Findings → Recommendations → Applications
           └─ M1 ─┘  └── M2 traffic ──┘ └── M3 horizontal geometry ──┘
                                                        └──── M4 opens this ────┘
```

M1 proved the engine is stage-generic. M2 and M3 proved it carries independent
engineering domains with no engine edits. **M4 proves the results are
*consumable*** — that a real application can render the full four-stage package
for a selected entity, tracing one road from raw geometry fact all the way to a
recommended fix, with the frontend contributing only layout.

---

## M4 charter — the applications menu

Following the M2/M3 shape, **one flagship application ships fully** and the rest
are **additive consumers of the identical `AnalysisResult`**, specified here so
scope is fixed even where implementation follows the flagship:

| application                  | consumes                                   | M4 status |
|------------------------------|--------------------------------------------|-----------|
| **Engineering Inspector**    | per-entity slice of obs/metrics/findings/recs | **flagship — full vertical** |
| Findings report              | network-wide findings ranked by severity + recs | additive |
| Charts                       | metric roll-ups / per-road distributions   | additive |
| Debug overlays               | color roads on the canvas by metric/finding | additive |
| Scenario comparison          | diff two captured `AnalysisResult`s         | additive (needs snapshot capture) |
| Lessons / assessments        | findings as objectives; scores from severities | additive |
| AI explainer (optional)      | reads results only, never the sim           | additive, optional |

Everything on this list is a function of an already-computed `AnalysisResult`.
None re-enters the engine; none re-derives a number.

**Legacy `/api/analysis` convergence** runs alongside as an incremental backend
track (below), not as the flagship. Its success bar for M4 is "started and
safe," not "finished."

---

## The flagship: the Engineering Inspector

Today's [`Inspector.tsx`](web/src/Inspector.tsx) is an **editor** panel — it
mutates the selected node/road/building (control type, road profile, delete). M4
adds a second, strictly **read-only analysis region** to that same panel: when a
road is selected, it shows what the platform *knows* about that road.

### What it consumes, and how the selection maps to results

The engine already keys per-entity results by road id, so the mapping is exact
and requires no new backend shape:

- **Observations** — network-level facts (`road_count`, `average_speed`, …); a
  road-scoped observation like `horizontal_curvature` carries
  `detail.per_road[road.id]`.
- **Metrics** — `detail.per_road[road.id]` holds this road's `road_capacity`,
  `vc_ratio`, `level_of_service`, `required_ssd`, `available_ssd`, etc.
- **Findings** — `evidence` is a list of flagged instances; the entries where
  `evidence[i].road_id == road.id` are this road's findings, each with
  `severity`, `explanation`, and traceable numbers (`vc`, `margin_ft`, …).
- **Recommendations** — `items[i].supporting_evidence` references the road; the
  matching items are this road's proposed fixes with `expected_benefit` and
  `tradeoffs`.

The Inspector therefore renders, for one selected road, the **entire vertical
chain** the platform produced for it — the traceability the planning doc's SSD
example demands, made visible: *radius → required/available SSD → deficiency
finding → the three improvement levers*.

### Data flow (presentation-only, end to end)

1. Frontend fetches the whole package from the existing
   `GET /api/analysis/v2` (unchanged) — Runtime source if a sim is active, else
   Static, exactly as today.
2. The Inspector **filters** the package to the selected road id in the
   presentation layer. Filtering by id is selection, not engineering — no
   thresholds, no math. Fetch-once-filter-client keeps the endpoint untouched
   and the whole package available for other consumers.
3. Each surviving result renders through the generic, `kind`-keyed presentation
   components: a metric row (`value` + `units`), a finding card (`severity`
   badge + `explanation` + evidence numbers), a recommendation card (`title` +
   `expected_benefit` + `tradeoffs`). Severity → color is a fixed presentation
   map over the four platform severities (`none`/`low`/`moderate`/`high`), not a
   computed judgement.

### Honesty about node/intersection selection

Today every metric and finding is **per-road** (traffic ops and horizontal
geometry both). There are **no per-node results yet** — intersection-level
analyses (intersection spacing, intersection sight distance, control-delay LOS)
are M3/future additive plugins that have not landed. So for a selected node the
Inspector's analysis region honestly shows an **empty state** ("no
intersection-level analysis available yet"), *not* a fabricated one. When
intersection plugins register — keyed by node id under the same `detail.per_node`
/ `evidence` convention — the identical Inspector renderer picks them up with no
new code. Buildings likewise: analysis region empty until a demand/land-use
plugin scopes to them (see convergence track). The flagship targets roads because
that is where the platform currently has something true to say.

### Refresh triggers

- **On selection change** and **on `geoVersion` bump** (map edits) — refetch and
  re-filter, matching how the existing panels already refresh.
- **While a sim runs**, findings evolve as the traversal counter accumulates
  volume. M4 refreshes the analysis region on the same cadence the live snapshot
  panel already polls (or on an explicit "refresh analysis" affordance). No new
  subscription to the sim clock — the platform stays on-demand (M1 principle 2).

---

## Secondary track — legacy `/api/analysis` convergence (incremental, low-risk)

The legacy [`/api/analysis`](Flowscape/api_server.py:770) still computes building
mix, exact day-0 demand (`generate_trips`), network totals, and connectivity
warnings **in the endpoint**, feeding [`AnalysisPanel.tsx`](web/src/AnalysisPanel.tsx).
That is the last duplicate engineering-calculation path outside the platform.
M4 begins retiring it **one calculation at a time**, preserving the existing API
response shape and the existing panel behavior at every step:

- `connected_components` already exists as an M1 observation — the connectivity
  warnings can read platform results instead of re-running union-find.
- Building mix / population / jobs → a `building_mix` observation (network
  category), the counts + capacity roll-up the endpoint does inline.
- Day-0 demand (`daily_trips`, AM/PM peaks) → a `day0_demand` observation at the
  builder boundary (the only layer allowed to call `generate_trips`).
- The endpoint then assembles its **same JSON** from `AnalysisResult` fields —
  becoming a thin serialization adapter, not a calculator.

**Bar for M4:** the migration is *started and safe* — at least connectivity and
building-mix ported, `/api/analysis` byte-compatible with today for the existing
panel, no regression. Finishing the endpoint's reduction to a pure adapter may
spill into a follow-up; the **milestone succeeds or fails on the Inspector**,
not on fully deleting the legacy math.

---

## Package layout — frontend-additive plus optional backend observations

```
web/src/
├── Inspector.tsx        # + read-only analysis region for the selected road
├── analysis/            # NEW: result-shape-driven presentation components
│   ├── AnalysisSection.tsx   # renders a filtered AnalysisResult slice
│   ├── MetricRow.tsx         # value + units, kind="metric"
│   ├── FindingCard.tsx       # severity badge + explanation + evidence
│   └── RecommendationCard.tsx# title + expected_benefit + tradeoffs
├── api.ts               # + fetchAnalysisV2()
└── types.ts             # + AnalysisResult / stage-result TS types (mirror to_dict)

Flowscape/analysis/observations/
└── network.py           # (convergence track) + building_mix, day0_demand
```

No `engine/` file is touched. No metric/finding/recommendation *logic* is added
for the flagship — M4 consumes what M2/M3 already produce. The only backend
additions are convergence-track **observations** (facts), registered through the
same `engine/registry.py`.

---

## API exposure

**No new endpoint and no contract change to `/api/analysis/v2`** — the flagship
consumes the existing package and filters client-side. `/api/analysis` keeps its
exact response shape throughout the convergence track (its internals migrate
underneath; its output does not move). This preserves the M1–M3 guarantee that
the legacy path stays intact for the current UI.

---

## Tests

Frontend and backend, leaning on the existing deterministic fixtures:

- **Presentation-only invariant (the headline test).** On the M2/M3 fixture maps,
  assert the Inspector's rendered numbers are *equal to* the `AnalysisResult`
  fields byte-for-byte — no rounding logic, no recomputation, no threshold in the
  component. A test that mutates a result value and sees the UI change in lockstep
  proves the frontend computes nothing.
- **Selection mapping.** Selecting a road with a fired `ssd_deficiency` /
  `over_capacity` shows exactly that road's evidence and recommendations;
  selecting a clear road shows the all-clear state; selecting a node shows the
  honest empty state (no fabricated per-node analysis).
- **Generic-renderer proof.** A stub result of an existing `kind` under a new
  plugin id renders through the same components with no new code — the frontend
  analog of M2/M3's "registers with no engine change."
- **Refresh.** Editing geometry (`geoVersion` bump) and, under a running sim,
  accumulating volume both refresh the analysis region; the platform is still
  invoked on demand (no sim-clock subscription).
- **Convergence (backend).** `building_mix` / `day0_demand` /
  connectivity-from-`connected_components` observations return the same values the
  legacy endpoint computes inline; `/api/analysis` stays byte-compatible with a
  golden response on the fixture maps; full headless suite green.

**Definition of done:** selecting a road in the Inspector displays its
observations, metrics, findings, and recommendations, pulled from a single
`GET /api/analysis/v2` package and filtered in the presentation layer, with **no
engineering calculation in the frontend**; node/building selections show honest
empty states; the generic renderer surfaces a new same-`kind` plugin with no
component change; the convergence track has ported at least connectivity and
building-mix into platform observations with `/api/analysis` unchanged in output;
M1–M3 results and both API paths fully intact; full headless suite green.

---

## Explicit M4 non-goals

- **No engineering logic in the frontend** — no thresholds, standards, unit
  conversion, severity computation, or interpretation in TypeScript. Every such
  value is consumed pre-computed. This is the milestone's defining constraint.
- **No new engineering analyses.** M4 ships *applications*, not verticals. New
  metrics/findings (intersection-level analysis, the M3 additive geometry menu,
  M2 delay/queue/density) remain their own future plugin work; the Inspector will
  render them for free when they land.
- **Only the Inspector ships.** Reports, charts, overlays, scenario comparison,
  lessons, assessments, and the AI explainer are specified as additive consumers
  and built later on the interface the Inspector proves — not in M4.
- **No engine, snapshot-shape, simulation, or renderer changes** for the flagship.
  (Convergence-track observations are additive facts, not engine edits.)
- **The legacy path is not deleted.** `/api/analysis`'s *output* is unchanged and
  `AnalysisPanel.tsx` keeps working; only its internal calculations begin
  migrating underneath. Full reduction to a thin adapter may complete in a
  follow-up.

---

## Appendix A — concrete frontend interface (signatures)

Design-level signatures for the flagship, so implementation is transcription, not
invention. Every type mirrors a backend `to_dict()` **field-for-field** — the
frontend adds no field the platform did not serialize. Every component is
display-only: no thresholds, no arithmetic, no unit conversion, no severity
computation.

### TS result types — mirror `analysis/**/base.py` `to_dict()` and `models/result.py`

```ts
// web/src/types.ts  (additions)

export type Severity = 'none' | 'low' | 'moderate' | 'high'
export type Stage = 'observation' | 'metric' | 'finding' | 'recommendation'

// Per-entity detail is keyed by road id. NOTE: JSON object keys are strings, so
// these come back stringified — look up with String(roadId). Values are opaque
// to the presentation layer: a scalar, or a record of already-computed fields.
export type PerRoad = Record<string, number | Record<string, unknown> | null>

// Observations and metrics share the same serialized shape (base.py).
export interface StageValueResult {
  id: string
  category: string
  kind: 'observation' | 'metric'
  value: number | string | null           // network roll-up; null = honest N/A
  units: string | null
  detail?: { per_road?: PerRoad } & Record<string, unknown>
}
export type ObservationResult = StageValueResult & { kind: 'observation' }
export type MetricResult = StageValueResult & { kind: 'metric' }

// One flagged instance. Always carries road_id; the rest are plugin-specific,
// already display-ready (e.g. vc, volume, capacity | required_ft, available_ft,
// margin_ft, design_speed_mph, radius_ft). The UI never interprets them.
export interface EvidenceRow {
  road_id: number
  severity?: Severity
  [field: string]: unknown
}

export interface FindingResult {
  id: string
  category: string
  kind: 'finding'
  name: string
  severity: Severity                       // network roll-up severity
  flagged: boolean                         // == evidence.length > 0
  evidence: EvidenceRow[]
  explanation: string
  supporting_metrics: string[]
  supporting_observations: string[]
  confidence: number | null
}

export interface RecommendationItem {
  title: string
  expected_benefit: string
  tradeoffs: string
  supporting_evidence?: unknown            // the road / finding it addresses
  [field: string]: unknown
}

export interface RecommendationResult {
  id: string
  category: string
  kind: 'recommendation'
  items: RecommendationItem[]
  supporting_findings: string[]
  confidence: number | null
}

export interface AnalysisResult {
  observations: Record<string, ObservationResult>
  metrics: Record<string, MetricResult>
  findings: Record<string, FindingResult>
  recommendations: Record<string, RecommendationResult>
  metadata: {
    source_kind: string
    is_running: boolean
    snapshot_hash?: string
    generated_at?: string
    [k: string]: unknown
  }
}
```

### The projection — pure, presentation-only selection

The one function that maps a selected road to its slice of the package. It is a
**projection**: it picks the entries whose per-entity key / `road_id` matches
`roadId`. No comparison, no math — selection only. This is the whole of the
"filter client-side" step, and it contains zero engineering logic by
construction.

```ts
// web/src/analysis/roadAnalysis.ts

export interface RoadAnalysis {
  observations: { result: ObservationResult; perRoad: unknown }[]
  metrics:      { result: MetricResult; perRoad: unknown }[]
  findings:     { finding: FindingResult; row: EvidenceRow }[]
  recommendations: { rec: RecommendationResult; items: RecommendationItem[] }[]
  empty: boolean   // true → render the honest empty state (node/building/clear road)
}

// Pure. For each metric/observation: keep it if detail.per_road[String(roadId)]
// exists, carrying that road's precomputed value. For each finding: keep the
// evidence rows where row.road_id === roadId. For each recommendation: keep the
// items whose supporting_evidence references roadId.
export function roadAnalysis(result: AnalysisResult, roadId: number): RoadAnalysis
```

### Components — display only

```ts
// web/src/analysis/AnalysisSection.tsx
// Mounted read-only inside Inspector.tsx when a road is selected. Fetches the
// whole package once per (geoVersion, running-tick) and shares it across
// selections; projects to roadId; lays out the four stages; shows the empty
// state when projection.empty.
function AnalysisSection(props: {
  roadId: number
  geoVersion: number
  heritage?: boolean
}): JSX.Element

// One metric's roll-up value + units for this road. props.perRoad is this road's
// precomputed entry, shown as labeled fields when it's a record.
function MetricRow(props: { result: MetricResult; perRoad: unknown }): JSX.Element

// A fired finding for this road: severity badge, name, explanation, and the
// evidence row's precomputed numbers as labeled fields.
function FindingCard(props: { finding: FindingResult; row: EvidenceRow }): JSX.Element

// One proposed fix: title, expected benefit, trade-offs.
function RecommendationCard(props: { item: RecommendationItem }): JSX.Element

// The ONLY place severity meets color. A fixed lookup over the four platform
// severities — NOT a judgement (which severity a thing has was decided by the
// finding plugin). This constant is the boundary the presentation-only rule
// draws: mapping an already-decided severity to a swatch is presentation;
// deciding the severity would be engineering and does not happen here.
const SEVERITY_COLOR: Record<Severity, string>
```

### API client

```ts
// web/src/api.ts  (addition) — existing endpoint, unchanged contract.
export const fetchAnalysisV2 = () => req<AnalysisResult>('/api/analysis/v2')
```

When intersection-level plugins land, they register per-node results under the
same `detail.per_node` / `evidence.node_id` convention; a sibling `nodeAnalysis`
projection and the identical cards render them with no new engineering logic —
the empty state simply stops being empty.
