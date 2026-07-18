import { Icon, Sparkle } from './HeritageIcons'
import type { SimSnapshot } from './types'

// Heritage Atlas bottom Simulation Control Bar (UI-Graphic-Design "MORE INFO"
// section). A fourth docked region spanning the bottom: engraved brass
// playback controls, a surveying-ruler timeline, a day/night indicator and
// live statistics. Drag its top edge to grow it into a taller dashboard.
// Presentation only — it drives the same sim endpoints the toolbar already
// used; no new simulation behaviour.

interface Props {
  meta: SimSnapshot
  expanded: boolean
  onToggleExpand: () => void
  onResizeStart: (e: React.PointerEvent) => void
  unified: boolean
  timeScale: number
  onUnifiedChange: (v: boolean) => void
  onTimeScaleChange: (v: number) => void
  onStart: () => void
  onPause: () => void
  onResume: () => void
  onStop: () => void
}

const TIME_SCALES = [1, 8, 60, 360]

// "HH:MM" → fraction of a 24h day (defensive: unknown clock ⇒ 0).
function dayFraction(clock?: string): number {
  if (!clock) return 0
  const [h, m] = clock.split(':').map(Number)
  if (Number.isNaN(h)) return 0
  return ((h + (m || 0) / 60) % 24) / 24
}

// An engraved surveying-rule timeline: hour graduations with brass detailing
// and a marker at the current time of day.
function RulerTimeline({ frac }: { frac: number }) {
  const W = 240, H = 30
  const ticks = Array.from({ length: 25 }, (_, i) => i)
  const mx = frac * W
  return (
    <svg className="ha-ruler" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none"
         aria-hidden="true">
      <g filter="url(#ha-ink)" stroke="currentColor" fill="none">
        <line x1="0" y1="10" x2={W} y2="10" strokeWidth="0.8" opacity="0.5" />
        {ticks.map((i) => {
          const x = (i / 24) * W
          const major = i % 6 === 0
          return <line key={i} x1={x} y1="10" x2={x} y2={major ? 20 : 15}
                       strokeWidth={major ? 1 : 0.6} />
        })}
      </g>
      {[0, 6, 12, 18, 24].map((h) => (
        <text key={h} x={(h / 24) * W} y="29" className="ha-ruler-num"
              textAnchor={h === 0 ? 'start' : h === 24 ? 'end' : 'middle'}>
          {h.toString().padStart(2, '0')}
        </text>
      ))}
      <g style={{ color: 'var(--ui-accent)' }}>
        <line x1={mx} y1="2" x2={mx} y2="22" stroke="currentColor" strokeWidth="1.4" />
        <path d={`M ${mx - 4} 2 L ${mx + 4} 2 L ${mx} 7 Z`} fill="currentColor" />
      </g>
    </svg>
  )
}

export default function ControlBar({ meta, expanded, onToggleExpand,
    onResizeStart, unified, timeScale, onUnifiedChange, onTimeScaleChange,
    onStart, onPause, onResume, onStop }: Props) {
  const running = meta.running
  const paused = meta.paused ?? false
  const frac = dayFraction(meta.clock)
  const hour = frac * 24
  const night = hour < 6 || hour >= 20

  return (
    <div className={`control-bar${expanded ? ' expanded' : ''}`}>
      <div className="dock-resize top" onPointerDown={onResizeStart} />
      <div className="control-row">
        <div className="playback">
          {!running && (
            <button className="brass" title="Start" onClick={onStart}>
              <Icon name="start" /></button>
          )}
          {running && !paused && (
            <button className="brass" title="Pause" onClick={onPause}>
              <Icon name="pause" /></button>
          )}
          {running && paused && (
            <button className="brass" title="Resume" onClick={onResume}>
              <Icon name="resume" /></button>
          )}
          {running && (
            <button className="brass" title="Stop" onClick={onStop}>
              <Icon name="stop" /></button>
          )}
          {!running && (
            <div className="sim-mode-cluster">
              <select className="ha-select sim-mode" value={unified ? 'sim' : 'preview'}
                      title="Simulation clock" onChange={(e) =>
                        onUnifiedChange(e.target.value === 'sim')}>
                <option value="preview">Preview (fast)</option>
                <option value="sim">Simulate (accurate)</option>
              </select>
              {unified && (
                <select className="ha-select sim-speed" value={timeScale}
                        title="Sim speed (× real time)" onChange={(e) =>
                          onTimeScaleChange(Number(e.target.value))}>
                  {TIME_SCALES.map((s) => (
                    <option key={s} value={s}>{s}×</option>
                  ))}
                </select>
              )}
            </div>
          )}
        </div>

        <div className="timeline">
          <span className="daynight" title={night ? 'night' : 'day'}>
            {night ? '☾' : '☀'}
          </span>
          <RulerTimeline frac={frac} />
          <span className="clock-read">{meta.clock ?? '--:--'}</span>
        </div>

        <div className="livestats">
          <span className="stat-chip"><label>Day</label>
            <b>{running ? meta.day ?? 1 : '—'}</b></span>
          <span className="stat-chip"><label>Cars</label>
            <b>{meta.vehicles?.length ?? 0}</b></span>
          <span className="stat-chip"><label>Queue</label>
            <b>{meta.queue_depth ?? 0}</b></span>
        </div>

        <button className="dock-collapse" title={expanded ? 'Collapse' : 'Expand'}
                onClick={onToggleExpand}>{expanded ? '▾' : '▴'}</button>
      </div>

      {expanded && (
        <div className="control-advanced">
          <Sparkle tone="rose" /><span className="ha-divider-label">Simulation Dashboard</span><Sparkle tone="sage" />
          <div className="advanced-grid">
            <span className="stat-chip"><label>Weekday</label>
              <b>{meta.day_name ?? '—'}</b></span>
            <span className="stat-chip"><label>Released</label>
              <b>{meta.released ?? 0}</b></span>
            <span className="stat-chip"><label>State</label>
              <b>{running ? (paused ? 'paused' : 'running') : 'stopped'}</b></span>
            <span className="stat-chip"><label>Tick</label>
              <b>{meta.tick ?? 0}</b></span>
            <span className="stat-chip"><label>Clock</label>
              <b>{meta.unified ? `${meta.time_scale ?? 0}× sim` : 'preview'}</b></span>
            {meta.unified && (
              <span className="stat-chip"><label>Substeps</label>
                <b>{meta.substeps ?? 1}</b></span>
            )}
          </div>
          <div className="advanced-note">
            Scenario, recording &amp; camera tools — reserved.
          </div>
        </div>
      )}
    </div>
  )
}
