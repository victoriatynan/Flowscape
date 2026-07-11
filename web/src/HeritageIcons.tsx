// Heritage Atlas — engraved icon set and decorative panel frame
// (UI-Graphic-Design brief, UPDATED INFORMATION). Original artwork: thin
// outlined "engraved" glyphs meant to sit inside brass medallions, plus a
// framing overlay with Art Nouveau corner flourishes and a compass rose.
// Everything is stroke=currentColor so the tokens/CSS drive the colour, and
// the frame is purely decorative (aria-hidden, pointer-events:none).

import type { ReactElement } from 'react'

export type IconName =
  | 'select' | 'node' | 'road' | 'building'
  | 'undo' | 'redo' | 'analysis' | 'design'
  | 'start' | 'pause' | 'resume' | 'stop' | 'save' | 'load'

const PATHS: Record<IconName, ReactElement> = {
  // Surveyor's pointer.
  select: <path d="M5 4 L5 17 L8.5 13.5 L11 19 L13 18 L10.5 12.5 L15 12 Z" />,
  // Survey marker: ringed dot with radiating ticks.
  node: (
    <g>
      <circle cx="12" cy="12" r="4.5" />
      <circle cx="12" cy="12" r="1.4" />
      <path d="M12 2 L12 5 M12 19 L12 22 M2 12 L5 12 M19 12 L22 12" />
    </g>
  ),
  // Inked road segment with a dashed centre line.
  road: (
    <g>
      <path d="M6 3 L4 21 M18 3 L20 21" />
      <path d="M12 4 L12 7 M12 11 L12 14 M12 18 L12 21" strokeDasharray="0" />
    </g>
  ),
  // Building with a hipped roof.
  building: (
    <g>
      <path d="M5 21 L5 9 L12 4 L19 9 L19 21 Z" />
      <path d="M9 21 L9 14 L15 14 L15 21" />
      <path d="M11 11 L13 11" />
    </g>
  ),
  undo: <path d="M9 7 L5 11 L9 15 M5 11 L14 11 A5 5 0 0 1 14 21 L11 21" />,
  redo: <path d="M15 7 L19 11 L15 15 M19 11 L10 11 A5 5 0 0 0 10 21 L13 21" />,
  // Instrument dial / graph.
  analysis: (
    <g>
      <path d="M4 20 L20 20 M4 20 L4 4" />
      <path d="M7 17 L7 13 M11 17 L11 9 M15 17 L15 11 M19 17 L19 6" />
    </g>
  ),
  // Drafting compass.
  design: (
    <g>
      <circle cx="12" cy="5" r="1.6" />
      <path d="M11 6.4 L6 20 M13 6.4 L18 20" />
      <path d="M8.5 14 A6 6 0 0 0 15.5 14" />
    </g>
  ),
  start: <path d="M7 5 L19 12 L7 19 Z" />,
  pause: <path d="M8 5 L8 19 M16 5 L16 19" />,
  resume: <path d="M7 5 L19 12 L7 19 Z" />,
  stop: <path d="M6 6 L18 6 L18 18 L6 18 Z" />,
  save: <path d="M5 4 L16 4 L20 8 L20 20 L5 20 Z M8 4 L8 9 L15 9 L15 4 M8 20 L8 14 L16 14 L16 20" />,
  load: <path d="M4 7 L10 7 L12 9 L20 9 L20 19 L4 19 Z M8 13 L16 13 M12 10 L12 16 M9.5 13.5 L12 16 L14.5 13.5" />,
}

export function Icon({ name, className }: { name: IconName; className?: string }) {
  return (
    <svg className={`ha-ico${className ? ` ${className}` : ''}`}
         viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"
         fill="none" stroke="currentColor" strokeWidth="1.9"
         strokeLinecap="round" strokeLinejoin="round" filter="url(#ha-ink)">
      {PATHS[name]}
    </svg>
  )
}

// Shared SVG defs, mounted once by the app. Two hand-drawn filters and a set
// of hand-painted gradients give every decorative SVG the look of the image-1
// botanical plate: organic linework with thickness variation (ha-ink) and
// soft watercolour fills with irregular pigment edges and gentle bleed
// (ha-water). Gradients supply the multi-toned colour shading (brass, sage,
// rose) rather than flat fills.
export function HeritageDefs() {
  return (
    <svg width="0" height="0" aria-hidden="true"
         style={{ position: 'absolute' }}>
      <defs>
        {/* Dip-pen ink: gentle line wobble. The seed is stepped by a slow JS
            timer (App effect) so the linework boils ~3x/sec — cheap, because
            filtered elements only re-render when the seed actually changes. */}
        <filter id="ha-ink" x="-40%" y="-40%" width="180%" height="180%">
          <feTurbulence type="fractalNoise" baseFrequency="0.035"
                        numOctaves="2" seed="7" result="n" />
          <feDisplacementMap in="SourceGraphic" in2="n" scale="2.2"
                             xChannelSelector="R" yChannelSelector="G" />
        </filter>
        {/* Watercolour: irregular pigment edges, pooling, granulation, bleed. */}
        <filter id="ha-water" x="-50%" y="-50%" width="200%" height="200%">
          <feTurbulence type="fractalNoise" baseFrequency="0.016"
                        numOctaves="3" seed="4" result="n" />
          <feDisplacementMap in="SourceGraphic" in2="n" scale="3.6"
                             xChannelSelector="R" yChannelSelector="G" result="d" />
          {/* granulation: mottle the pigment with fine noise */}
          <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2"
                        seed="3" result="g" />
          <feColorMatrix in="g" type="matrix"
            values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 0.7 0" result="ga" />
          <feComposite in="ga" in2="d" operator="in" result="grain" />
          <feMerge>
            <feMergeNode in="d" />
            <feMergeNode in="grain" />
          </feMerge>
          <feGaussianBlur stdDeviation="0.4" />
        </filter>
        {/* Hand-painted colour shading. */}
        <linearGradient id="ha-g-brass" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#dcb85f" />
          <stop offset="0.55" stopColor="#c7a049" />
          <stop offset="1" stopColor="#8a6a34" />
        </linearGradient>
        <linearGradient id="ha-g-sage" x1="0" y1="0" x2="0.7" y2="1">
          <stop offset="0" stopColor="#b3c07d" />
          <stop offset="1" stopColor="#5d6b2f" />
        </linearGradient>
        <linearGradient id="ha-g-rose" x1="0" y1="0" x2="0.6" y2="1">
          <stop offset="0" stopColor="#e0b0a6" />
          <stop offset="1" stopColor="#b0532f" />
        </linearGradient>
        <linearGradient id="ha-g-plum" x1="0" y1="0" x2="0.6" y2="1">
          <stop offset="0" stopColor="#a99bbd" />
          <stop offset="1" stopColor="#6f5f8a" />
        </linearGradient>
        <radialGradient id="ha-g-glow" cx="0.5" cy="0.4" r="0.7">
          <stop offset="0" stopColor="#e6c877" />
          <stop offset="1" stopColor="#9a7838" />
        </radialGradient>
      </defs>
    </svg>
  )
}

const SPARKLE_FILL: Record<string, string> = {
  brass: 'url(#ha-g-brass)', rose: 'url(#ha-g-rose)',
  sage: 'url(#ha-g-sage)', plum: 'url(#ha-g-plum)',
}

// Four-point "navigation star" sparkle (from the botanical reference plate) —
// a small watercolour accent for dividers and frames, in a chosen pigment.
export function Sparkle({ className, tone = 'brass' }:
    { className?: string; tone?: 'brass' | 'rose' | 'sage' | 'plum' }) {
  return (
    <svg className={`ha-sparkle${className ? ` ${className}` : ''}`}
         viewBox="0 0 24 24" width="12" height="12" aria-hidden="true"
         filter="url(#ha-water)">
      <path d="M12 1 L13.6 10.4 L23 12 L13.6 13.6 L12 23 L10.4 13.6 L1 12 L10.4 10.4 Z"
            fill={SPARKLE_FILL[tone]} />
    </svg>
  )
}

// Instrument dial (brief: "Circular gauges / Compass-style rings"): a 270°
// engraved gauge with tick graduations, a brass value arc, a needle, and a
// centred readout. Purely presentational — reads a value against a max.
function polar(cx: number, cy: number, r: number, deg: number): [number, number] {
  const a = (deg - 90) * Math.PI / 180
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)]
}
export function RadialGauge({ value, max, label, format }:
    { value: number; max: number; label: string; format?: (v: number) => string }) {
  const cx = 34, cy = 34, r = 25
  const START = -135, SWEEP = 270
  const frac = max > 0 ? Math.max(0, Math.min(1, value / max)) : 0
  const end = START + SWEEP * frac
  const arc = (a0: number, a1: number) => {
    const [x0, y0] = polar(cx, cy, r, a0)
    const [x1, y1] = polar(cx, cy, r, a1)
    return `M ${x0} ${y0} A ${r} ${r} 0 ${a1 - a0 > 180 ? 1 : 0} 1 ${x1} ${y1}`
  }
  const ticks = Array.from({ length: 11 }, (_, i) => START + (SWEEP * i) / 10)
  const [nx, ny] = polar(cx, cy, r - 6, end)
  return (
    <div className="ha-gauge">
      <svg viewBox="0 0 68 68" width="68" height="68" aria-hidden="true">
        <g filter="url(#ha-ink)" fill="none" stroke="currentColor">
          <path d={arc(START, START + SWEEP)} strokeWidth="1" opacity="0.4" />
          {ticks.map((a, i) => {
            const [x0, y0] = polar(cx, cy, r + 2, a)
            const [x1, y1] = polar(cx, cy, r - (i % 5 === 0 ? 5 : 3), a)
            return <line key={i} x1={x0} y1={y0} x2={x1} y2={y1}
                         strokeWidth={i % 5 === 0 ? 1.1 : 0.7} />
          })}
          <path d={arc(START, end)} strokeWidth="2.6" strokeLinecap="round"
                stroke="url(#ha-g-brass)" />
          <line x1={cx} y1={cy} x2={nx} y2={ny} strokeWidth="1.6"
                strokeLinecap="round" stroke="url(#ha-g-brass)" />
          <circle cx={cx} cy={cy} r="2.4" fill="url(#ha-g-glow)" stroke="none" />
        </g>
      </svg>
      <div className="ha-gauge-read">{format ? format(value) : value}</div>
      <div className="ha-gauge-label">{label}</div>
    </div>
  )
}

// A hand-painted botanical corner flourish (image-1 vines/leaves/buds), drawn
// pointing into the top-left corner; the other three corners are mirrored /
// rotated with CSS. Inked stem, watercolour leaf and bud.
function Corner({ pos }: { pos: 'tl' | 'tr' | 'bl' | 'br' }) {
  return (
    <svg className={`ha-corner ${pos}`} viewBox="0 0 34 34" width="46" height="46"
         aria-hidden="true">
      <g filter="url(#ha-ink)" fill="none" stroke="var(--ha-olive)"
         strokeWidth="1.9" strokeLinecap="round">
        <path d="M3 32 C 9 23, 9 15, 18 10" />          {/* main stem */}
        <path d="M8 24 C 4 22, 3 18, 5 14" />           {/* offshoot */}
        <path d="M12 18 C 15 17, 18 18, 21 22" />       {/* tendril */}
      </g>
      <g filter="url(#ha-water)" stroke="none">
        {/* leaf */}
        <path d="M5 14 C 0 10, 1 5, 7 4 C 10 9, 9 14, 5 14 Z" fill="url(#ha-g-sage)" />
        {/* bud */}
        <path d="M18 10 C 14 7, 15 2, 20 2 C 24 3, 23 9, 18 10 Z" fill="url(#ha-g-rose)" />
        {/* small berry */}
        <circle cx="21.5" cy="22.5" r="2.6" fill="url(#ha-g-brass)" />
      </g>
      {/* leaf midrib, inked over the wash */}
      <path d="M5 14 C 4 11, 5 8, 7 4" fill="none" stroke="var(--ha-olive)"
            strokeWidth="0.8" opacity="0.75" filter="url(#ha-ink)" />
    </svg>
  )
}

// Small compass rose for the top-centre of a framed panel — watercolour
// star points over an inked double ring.
function CompassRose() {
  return (
    <svg className="ha-compass" viewBox="0 0 32 32" width="30" height="30"
         aria-hidden="true">
      <g filter="url(#ha-ink)" fill="none" stroke="var(--ui-panel-text)"
         strokeWidth="1.4" strokeLinejoin="round">
        <circle cx="16" cy="16" r="10.5" />
        <circle cx="16" cy="16" r="6.5" />
      </g>
      <g filter="url(#ha-water)" stroke="none">
        <path d="M16 2 L19 16 L16 30 L13 16 Z" fill="url(#ha-g-brass)" />
        <path d="M2 16 L16 13 L30 16 L16 19 Z" fill="url(#ha-g-rose)"
              opacity="0.9" />
      </g>
    </svg>
  )
}

// Decorative overlay for the side panels: a fine framing rule, four corner
// flourishes, and a compass rose. Sits inside a position:relative/absolute
// panel and never intercepts pointer events.
export function HeritageFrame() {
  return (
    <div className="ha-frame" aria-hidden="true">
      <Corner pos="tl" />
      <Corner pos="tr" />
      <Corner pos="bl" />
      <Corner pos="br" />
      <CompassRose />
    </div>
  )
}
