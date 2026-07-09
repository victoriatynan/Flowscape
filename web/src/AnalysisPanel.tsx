import { useEffect, useState } from 'react'

// Read-only Map Analysis panel (EDITOR_IMPROVEMENT_PLAN.md): building mix,
// exact deterministic day-0 demand, network totals, and connectivity
// warnings, refreshed automatically whenever the map changes (geoVersion).

export interface Analysis {
  buildings: {
    total: number
    by_category: Record<string, number>
    population: number
    jobs: number
  }
  demand: {
    daily_trips: number
    morning_peak_trips: number
    evening_peak_trips: number
  }
  network: {
    roads: number
    nodes: number
    intersections: number
    lane_miles: number
  }
  warnings: string[]
}

export default function AnalysisPanel({ geoVersion }: { geoVersion: number }) {
  const [data, setData] = useState<Analysis | null>(null)

  useEffect(() => {
    let cancelled = false
    fetch('/api/analysis')
      .then((r) => r.json())
      .then((a: Analysis) => { if (!cancelled) setData(a) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [geoVersion])

  if (!data) return null
  const cats = Object.entries(data.buildings.by_category).filter(([, n]) => n > 0)

  return (
    <div className="analysis">
      <div className="section">Buildings · {data.buildings.total}</div>
      {cats.map(([cat, n]) => (
        <div className="stat" key={cat}><span>{cat}</span><span>{n}</span></div>
      ))}
      <div className="stat"><span>Population</span><span>{data.buildings.population}</span></div>
      <div className="stat"><span>Jobs</span><span>{data.buildings.jobs}</span></div>

      <div className="section">Daily demand (exact)</div>
      <div className="stat"><span>Trips / day</span><span>{data.demand.daily_trips}</span></div>
      <div className="stat"><span>Morning peak</span><span>{data.demand.morning_peak_trips}</span></div>
      <div className="stat"><span>Evening peak</span><span>{data.demand.evening_peak_trips}</span></div>

      <div className="section">Network</div>
      <div className="stat"><span>Roads</span><span>{data.network.roads}</span></div>
      <div className="stat"><span>Intersections</span><span>{data.network.intersections}</span></div>
      <div className="stat"><span>Lane miles</span><span>{data.network.lane_miles.toFixed(2)}</span></div>

      {data.warnings.length > 0 && (
        <>
          <div className="section warn">Warnings</div>
          {data.warnings.map((w, i) => (
            <div className="warning" key={i}>{w}</div>
          ))}
        </>
      )}
    </div>
  )
}
