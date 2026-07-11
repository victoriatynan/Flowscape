// Heritage Atlas hand-drawn art helpers (non-component), kept out of the
// component modules so React fast-refresh stays happy.
//
// One shared "waver" gives every hand-inked line the same dip-pen character —
// the canvas roads/junctions/buildings in renderer.ts AND the CSS panel/button
// border-image below both run through it. The wander is smoothly rounded (not
// blocky) and its undulations vary in length, instead of a mechanical wave.

export type P2 = [number, number]

// Deterministic hash in [0,1) from a float seed.
export function hash01(n: number): number {
  const s = Math.sin(n * 127.1 + 311.7) * 43758.5453
  return s - Math.floor(s)
}

// Smooth 1-D value noise in [-1,1]: hash the integer lattice and smoothstep
// between neighbours, so the offset curves continuously instead of jumping —
// this is what turns a blocky wander into a rounded one.
export function vnoise(x: number, seed = 0): number {
  const o = seed * 53.17
  const i = Math.floor(x)
  const f = x - i
  const t = f * f * (3 - 2 * f)
  const a = hash01(i + o) * 2 - 1
  const b = hash01(i + 1 + o) * 2 - 1
  return a + (b - a) * t
}

export interface WaverOpts {
  amp: number        // sideways offset amplitude (px)
  step: number       // mean spacing between samples (px) ≈ mean undulation length
  seed?: number      // change to boil / animate
  closed?: boolean   // treat the polyline as a loop
}

// Resample a polyline and push each sample sideways to hand-draw it. Samples
// are spaced at IRREGULAR intervals (0.55..1.45 * step, from noise) so the
// undulations vary in length, and the sideways offset comes from the smooth
// noise above so the line curves rather than zig-zags.
export function waver(pts: readonly P2[], o: WaverOpts): P2[] {
  const n = pts.length
  if (n < 2) return pts.map((p) => [p[0], p[1]] as P2)
  const seed = o.seed ?? 0
  const segs = o.closed ? n : n - 1
  const out: P2[] = []
  let dist = 0                       // cumulative arc length → continuous phase
  for (let s = 0; s < segs; s++) {
    const a = pts[s], b = pts[(s + 1) % n]
    const dx = b[0] - a[0], dy = b[1] - a[1]
    const len = Math.hypot(dx, dy) || 1e-6
    const nx = -dy / len, ny = dx / len            // unit normal
    let t = 0
    do {
      const phase = (dist + t) / o.step
      const off = vnoise(phase, seed) * o.amp
      const f = t / len
      out.push([a[0] + dx * f + nx * off, a[1] + dy * f + ny * off])
      t += o.step * (0.55 + 0.9 * hash01(phase * 1.7 + seed * 9.13))
    } while (t < len)
    dist += len
  }
  if (!o.closed) out.push([pts[n - 1][0], pts[n - 1][1]])
  return out
}

// Draw a smooth curve THROUGH the points (quadratics anchored on each point,
// joined at edge midpoints) on a canvas context. `closed` joins the ends.
export function strokeSmooth(ctx: CanvasRenderingContext2D,
                            pts: readonly P2[], closed: boolean): void {
  const n = pts.length
  if (n < 2) return
  ctx.beginPath()
  if (closed) {
    ctx.moveTo((pts[n - 1][0] + pts[0][0]) / 2, (pts[n - 1][1] + pts[0][1]) / 2)
    for (let i = 0; i < n; i++) {
      const j = (i + 1) % n
      ctx.quadraticCurveTo(pts[i][0], pts[i][1],
        (pts[i][0] + pts[j][0]) / 2, (pts[i][1] + pts[j][1]) / 2)
    }
    ctx.closePath()
  } else {
    ctx.moveTo(pts[0][0], pts[0][1])
    for (let i = 1; i < n - 1; i++)
      ctx.quadraticCurveTo(pts[i][0], pts[i][1],
        (pts[i][0] + pts[i + 1][0]) / 2, (pts[i][1] + pts[i + 1][1]) / 2)
    ctx.lineTo(pts[n - 1][0], pts[n - 1][1])
  }
  ctx.stroke()
}

// The same smooth curve as an SVG path `d` string (used by the border-image).
function smoothPathD(pts: readonly P2[], closed: boolean): string {
  const n = pts.length
  if (n < 2) return ''
  const r = (v: number) => Math.round(v * 100) / 100
  if (closed) {
    let d = `M${r((pts[n - 1][0] + pts[0][0]) / 2)} ${r((pts[n - 1][1] + pts[0][1]) / 2)}`
    for (let i = 0; i < n; i++) {
      const j = (i + 1) % n
      d += `Q${r(pts[i][0])} ${r(pts[i][1])} ${r((pts[i][0] + pts[j][0]) / 2)} ${r((pts[i][1] + pts[j][1]) / 2)}`
    }
    return d + 'Z'
  }
  let d = `M${r(pts[0][0])} ${r(pts[0][1])}`
  for (let i = 1; i < n - 1; i++)
    d += `Q${r(pts[i][0])} ${r(pts[i][1])} ${r((pts[i][0] + pts[i + 1][0]) / 2)} ${r((pts[i][1] + pts[i + 1][1]) / 2)}`
  return d + `L${r(pts[n - 1][0])} ${r(pts[n - 1][1])}`
}

// A rounded-rectangle outline as a point list, ready to waver. Straight edges
// are sampled coarsely; each corner is a short arc so it stays gently rounded.
function roundedRectPts(x: number, y: number, w: number, h: number, r: number): P2[] {
  const p: P2[] = []
  const edge = (x0: number, y0: number, x1: number, y1: number) => {
    const N = Math.max(2, Math.round(Math.hypot(x1 - x0, y1 - y0) / 12))
    for (let i = 0; i < N; i++)
      p.push([x0 + (x1 - x0) * i / N, y0 + (y1 - y0) * i / N])
  }
  const arc = (cx: number, cy: number, a0: number, a1: number) => {
    for (let i = 0; i < 4; i++) {
      const a = a0 + (a1 - a0) * i / 4
      p.push([cx + r * Math.cos(a), cy + r * Math.sin(a)])
    }
  }
  const x2 = x + w, y2 = y + h, H = Math.PI / 2
  edge(x + r, y, x2 - r, y);     arc(x2 - r, y + r, -H, 0)
  edge(x2, y + r, x2, y2 - r);   arc(x2 - r, y2 - r, 0, H)
  edge(x2 - r, y2, x + r, y2);   arc(x + r, y2 - r, H, Math.PI)
  edge(x, y2 - r, x, y + r);     arc(x + r, y + r, Math.PI, Math.PI + H)
  return p
}

// The panel/button border-image: a rounded-rect outline wavered by the SAME
// function the roads use, baked into an SVG path (no filters, so no blocky
// turbulence). Cycling `seed` on the app's slow timer boils the border in step
// with the map ink. stroke-width 10 in this 160-box, sliced 24 into a 7px
// border, renders ≈2.9px on screen — matched to the road ink weight.
export function inkBorderUri(seed: number): string {
  const d = smoothPathD(
    waver(roundedRectPts(13, 13, 134, 134, 9), { amp: 5, step: 17, seed, closed: true }),
    true)
  const svg = "<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'>"
    + "<path d='" + d + "' fill='none' stroke='#5a4632' stroke-width='10' "
    + "stroke-linejoin='round' stroke-linecap='round'/></svg>"
  return 'url("data:image/svg+xml,' + encodeURIComponent(svg) + '")'
}
