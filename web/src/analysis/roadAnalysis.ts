// The projection — pure, presentation-only selection (M4).
//
// Maps a full AnalysisResult package to the slice belonging to one selected
// road. This is SELECTION, not engineering: it picks the entries whose
// per-entity key / road_id matches roadId and carries their already-computed
// values through unchanged. No comparison, no math, no thresholds, no unit
// conversion — by construction there is zero engineering logic here.
//
// Id matching is deliberately LOOSE (String(a) === String(b)). Per-entity
// `detail.per_road` keys are JSON object keys and therefore strings; evidence /
// recommendation `road_id` values arrive as numbers. Comparing as strings makes
// the projection correct for both the traffic and geometry tracks; a naive
// `===` would silently drop whichever side is stringified.

import type {
  AnalysisResult,
  EvidenceRow,
  MetricResult,
  ObservationResult,
  RecommendationItem,
  RecommendationResult,
} from '../types'

export interface RoadAnalysis {
  observations: { result: ObservationResult; perRoad: unknown }[]
  metrics: { result: MetricResult; perRoad: unknown }[]
  findings: { finding: import('../types').FindingResult; row: EvidenceRow }[]
  recommendations: { rec: RecommendationResult; items: RecommendationItem[] }[]
  empty: boolean // true → render the honest empty state (node/building/clear road)
}

const sameId = (a: unknown, b: unknown) => String(a) === String(b)

// This road's precomputed entry from a stage's per_road map, or undefined if the
// stage says nothing about this road. Keys are strings on the wire.
function perRoadEntry(
  result: ObservationResult | MetricResult,
  roadId: number,
): unknown {
  const perRoad = result.detail?.per_road
  if (!perRoad) return undefined
  const key = String(roadId)
  return Object.prototype.hasOwnProperty.call(perRoad, key)
    ? perRoad[key]
    : undefined
}

export function roadAnalysis(
  result: AnalysisResult,
  roadId: number,
): RoadAnalysis {
  const observations: RoadAnalysis['observations'] = []
  for (const result_ of Object.values(result.observations ?? {})) {
    const perRoad = perRoadEntry(result_, roadId)
    if (perRoad !== undefined) observations.push({ result: result_, perRoad })
  }

  const metrics: RoadAnalysis['metrics'] = []
  for (const result_ of Object.values(result.metrics ?? {})) {
    const perRoad = perRoadEntry(result_, roadId)
    if (perRoad !== undefined) metrics.push({ result: result_, perRoad })
  }

  const findings: RoadAnalysis['findings'] = []
  for (const finding of Object.values(result.findings ?? {})) {
    for (const row of finding.evidence ?? []) {
      if (sameId(row.road_id, roadId)) findings.push({ finding, row })
    }
  }

  const recommendations: RoadAnalysis['recommendations'] = []
  for (const rec of Object.values(result.recommendations ?? {})) {
    const items = (rec.items ?? []).filter((item) => {
      // Items carry a top-level road_id; fall back to the road_id nested in
      // supporting_evidence for plugins that only reference it there.
      const evidence = item.supporting_evidence as { road_id?: unknown } | undefined
      return sameId(item.road_id, roadId) || sameId(evidence?.road_id, roadId)
    })
    if (items.length) recommendations.push({ rec, items })
  }

  const empty =
    observations.length === 0 &&
    metrics.length === 0 &&
    findings.length === 0 &&
    recommendations.length === 0

  return { observations, metrics, findings, recommendations, empty }
}
