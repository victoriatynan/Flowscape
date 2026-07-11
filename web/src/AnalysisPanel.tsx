import { useEffect, useState, type ReactNode } from 'react'
import { HeritageFrame, RadialGauge } from './HeritageIcons'

// Read-only Map Analysis panel (EDITOR_IMPROVEMENT_PLAN.md): building mix,
// exact deterministic day-0 demand, network totals, and connectivity
// warnings, refreshed automatically whenever the map changes (geoVersion).
//
// Sections are collapsible "chapter cards" (Heritage Atlas brief). The
// `heritage` flag adds the decorative framing overlay; the collapse behaviour
// itself is preset-agnostic and harmless in every theme.

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

function Card({ title, warn, children }:
              { title: string; warn?: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(true)
  return (
    <div className={`analysis-card${open ? '' : ' collapsed'}`}>
      <button className={`section${warn ? ' warn' : ''}`}
              aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <span>{title}</span>
        <span className="chevron">{open ? '▾' : '▸'}</span>
      </button>
      {open && <div className="analysis-card-body">{children}</div>}
    </div>
  )
}

export default function AnalysisPanel({ geoVersion, heritage }:
                       { geoVersion: number; heritage?: boolean }) {
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
      {heritage && <HeritageFrame />}
      <Card title={`Buildings · ${data.buildings.total}`}>
        {cats.map(([cat, n]) => (
          <div className="stat" key={cat}><span>{cat}</span><span>{n}</span></div>
        ))}
        <div className="stat"><span>Population</span><span>{data.buildings.population}</span></div>
        <div className="stat"><span>Jobs</span><span>{data.buildings.jobs}</span></div>
      </Card>

      <Card title="Daily demand (exact)">
        <div className="stat"><span>Trips / day</span><span>{data.demand.daily_trips}</span></div>
        <div className="stat"><span>Morning peak</span><span>{data.demand.morning_peak_trips}</span></div>
        <div className="stat"><span>Evening peak</span><span>{data.demand.evening_peak_trips}</span></div>
        {heritage && (
          <div className="ha-gauge-row">
            <RadialGauge label="AM peak" value={data.demand.morning_peak_trips}
                         max={data.demand.daily_trips} />
            <RadialGauge label="PM peak" value={data.demand.evening_peak_trips}
                         max={data.demand.daily_trips} />
          </div>
        )}
      </Card>

      <Card title="Network">
        <div className="stat"><span>Roads</span><span>{data.network.roads}</span></div>
        <div className="stat"><span>Intersections</span><span>{data.network.intersections}</span></div>
        <div className="stat"><span>Lane miles</span><span>{data.network.lane_miles.toFixed(2)}</span></div>
      </Card>

      {data.warnings.length > 0 && (
        <Card title="Warnings" warn>
          {data.warnings.map((w, i) => (
            <div className="warning" key={i}>{w}</div>
          ))}
        </Card>
      )}
    </div>
  )
}
