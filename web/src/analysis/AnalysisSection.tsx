import { useEffect, useState } from 'react'
import * as api from '../api'
import type { AnalysisResult } from '../types'
import { roadAnalysis } from './roadAnalysis'
import MetricRow from './MetricRow'
import FindingCard from './FindingCard'
import RecommendationCard from './RecommendationCard'

// Read-only analysis region for the selected road (M4 flagship). Fetches the
// whole /api/analysis/v2 package, projects it to this road in the presentation
// layer, and lays out the four stages. It performs NO engineering logic: every
// number, severity, and sentence is consumed exactly as the platform serialized
// it. Node/building selections and clear roads render an honest empty state.
//
// Refresh: the package is refetched whenever this component (re)mounts, which
// App.tsx keys on `${kind}-${id}-${geoVersion}` — so selection changes and map
// edits both refresh it. `roadId`/`geoVersion` are in the effect deps to make
// that explicit and survive any future keying change. The platform stays
// on-demand: no subscription to the sim clock.
export default function AnalysisSection({ roadId, geoVersion }:
                                        { roadId: number; geoVersion: number
                                          heritage?: boolean }) {
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError(null)
    api.fetchAnalysisV2()
      .then((r) => { if (alive) { setResult(r); setLoading(false) } })
      .catch((e) => { if (alive) { setError(String(e)); setLoading(false) } })
    return () => { alive = false }
  }, [roadId, geoVersion])

  return (
    <div className="analysis-section">
      <div className="row analysis-section-title">Engineering analysis</div>
      {loading && <div className="row analysis-empty">Analyzing…</div>}
      {error && <div className="row analysis-empty">Analysis unavailable: {error}</div>}
      {result && !loading && !error && <Body result={result} roadId={roadId} />}
    </div>
  )
}

function Body({ result, roadId }: { result: AnalysisResult; roadId: number }) {
  const a = roadAnalysis(result, roadId)
  if (a.empty) {
    return (
      <div className="row analysis-empty">
        No engineering findings for this road — it meets the analyzed standards,
        or no analysis applies to it yet.
      </div>
    )
  }
  return (
    <>
      {a.observations.length > 0 && (
        <Group label="Observations">
          {a.observations.map(({ result: r, perRoad }) => (
            <MetricRow key={r.id} result={r} perRoad={perRoad} />
          ))}
        </Group>
      )}
      {a.metrics.length > 0 && (
        <Group label="Metrics">
          {a.metrics.map(({ result: r, perRoad }) => (
            <MetricRow key={r.id} result={r} perRoad={perRoad} />
          ))}
        </Group>
      )}
      {a.findings.length > 0 && (
        <Group label="Findings">
          {a.findings.map(({ finding, row }) => (
            <FindingCard key={`${finding.id}-${row.road_id}`}
                         finding={finding} row={row} />
          ))}
        </Group>
      )}
      {a.recommendations.length > 0 && (
        <Group label="Recommendations">
          {a.recommendations.flatMap(({ rec, items }) =>
            items.map((item, i) => (
              <RecommendationCard key={`${rec.id}-${i}`} item={item} />
            )))}
        </Group>
      )}
    </>
  )
}

function Group({ label, children }:
               { label: string; children: React.ReactNode }) {
  return (
    <div className="analysis-group">
      <div className="analysis-group-label">{label}</div>
      {children}
    </div>
  )
}
