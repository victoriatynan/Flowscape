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

// Linear interpolation: the value `t` (0..1) of the way from a to b — t=0 → a,
// t=1 → b, t=0.5 → midpoint. The single primitive behind every taper in this
// module (position along an edge, and weight between vertices), matching
// lerp() in hand_drawn_lines.py / line_weight.py.
export function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t
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
  return lerp(a, b, t)
}

// A per-vertex ink colour. Matches line_weight.py's (r, g, b) tuples that
// lerp_color/draw_lit_shape interpolate — here so a stroke can shade from a
// pale (lit) to a dark (shadow) end along its length.
export type RGB = [number, number, number]

// Parse a canvas colour string to RGB. Handles the '#rrggbb' the palette uses
// and the 'rgb(...)' some canvas implementations echo back from strokeStyle.
export function hexToRgb(s: string): RGB {
  const h = /#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})/i.exec(s)
  if (h) return [parseInt(h[1], 16), parseInt(h[2], 16), parseInt(h[3], 16)]
  const r = /rgba?\((\d+)[,\s]+(\d+)[,\s]+(\d+)/i.exec(s)
  if (r) return [+r[1], +r[2], +r[3]]
  return [40, 34, 28]
}

// Lerp between two colours channel-by-channel (lerp_color in line_weight.py).
export function lerpColor(c0: RGB, c1: RGB, t: number): RGB {
  return [lerp(c0[0], c1[0], t), lerp(c0[1], c1[1], t), lerp(c0[2], c1[2], t)]
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
      out.push([lerp(a[0], b[0], f) + nx * off, lerp(a[1], b[1], f) + ny * off])
      t += o.step * (0.55 + 0.9 * hash01(phase * 1.7 + seed * 9.13))
    } while (t < len)
    dist += len
  }
  if (!o.closed) out.push([pts[n - 1][0], pts[n - 1][1]])
  return out
}

// Build a smooth curve THROUGH the points (quadratics anchored on each point,
// joined at edge midpoints) as the current canvas path. `closed` joins the
// ends. Callers stroke OR fill it — hand-drawn node dots fill this same path
// their outline strokes, so the two always share one wobble.
export function pathSmooth(ctx: CanvasRenderingContext2D,
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
}

// Draw a smooth curve through the points at the current lineWidth.
export function strokeSmooth(ctx: CanvasRenderingContext2D,
                            pts: readonly P2[], closed: boolean): void {
  if (pts.length < 2) return
  pathSmooth(ctx, pts, closed)
  ctx.stroke()
}

// ---------------------------------------------------------------------------
// Line weight as visual hierarchy — the model from line_weight.py, ported to
// the canvas. Every hand-inked line carries a PER-VERTEX weight; the stroke
// lerps thickness between vertices (a swell, not a step), and the weight itself
// grows where the path turns tightly, so ink "pools" at corners exactly as a
// dip pen does. Hero outlines (roads) run thick/dark; internal detail (lane
// lines, edge lines) runs thin/pale — the four line-weight principles.
// ---------------------------------------------------------------------------

function unit(vx: number, vy: number): P2 {
  const l = Math.hypot(vx, vy) || 1
  return [vx / l, vy / l]
}

// Gaussian-blur a list of numbers ALONG the path (smooth_series). Smears a
// corner's curvature spike over its neighbours so the extra weight ramps up
// toward the bend and eases off after it — a gradual swell, not a blob.
export function smoothSeries(vals: readonly number[], radius = 4,
                             closed = true): number[] {
  const n = vals.length
  if (radius <= 0 || n === 0) return vals.slice()
  const sigma = radius / 2
  const ker: number[] = []
  for (let d = -radius; d <= radius; d++) ker.push(Math.exp(-(d * d) / (2 * sigma * sigma)))
  const out: number[] = []
  for (let i = 0; i < n; i++) {
    let acc = 0, wsum = 0
    for (let k = 0; k < ker.length; k++) {
      let idx = i + (k - radius)
      if (closed) idx = ((idx % n) + n) % n
      else if (idx < 0 || idx >= n) continue
      acc += vals[idx] * ker[k]; wsum += ker[k]
    }
    out.push(wsum ? acc / wsum : 0)
  }
  return out
}

// Approx local curvature (1/radius) at p: big where the turn is tight, ~0 on a
// straight run. turn angle / mean adjacent segment length (local_curvature).
export function localCurvature(a: P2, p: P2, b: P2): number {
  const [v1x, v1y] = unit(p[0] - a[0], p[1] - a[1])
  const [v2x, v2y] = unit(b[0] - p[0], b[1] - p[1])
  const dot = Math.max(-1, Math.min(1, v1x * v2x + v1y * v2y))
  const ang = Math.acos(dot)
  const seg = 0.5 * (Math.hypot(p[0] - a[0], p[1] - a[1])
    + Math.hypot(b[0] - p[0], b[1] - p[1]))
  return seg > 1e-6 ? ang / seg : 0
}

export interface WeightOpts {
  base: number          // thickness on straight runs (px)
  scale?: number        // curvature → extra weight gain
  cap?: number          // ceiling on the corner bulge (px)
  spread?: number       // how many neighbours the bulge ramps over
  closed?: boolean
}

// Per-vertex weight = base thickness + a capped, smeared corner bulge
// (draw_curvature_shape). Open paths carry no bend at their two endpoints.
export function curvatureWeights(pts: readonly P2[], o: WeightOpts): number[] {
  const n = pts.length
  const scale = o.scale ?? 34, cap = o.cap ?? o.base * 1.5
  const spread = o.spread ?? 4, closed = o.closed ?? true
  const bonus: number[] = []
  for (let i = 0; i < n; i++) {
    if (!closed && (i === 0 || i === n - 1)) { bonus.push(0); continue }
    const k = localCurvature(pts[(i - 1 + n) % n], pts[i], pts[(i + 1) % n])
    bonus.push(Math.min(cap, scale * k))
  }
  return smoothSeries(bonus, spread, closed).map((b) => o.base + b)
}

export interface LitOpts {
  light: P2             // vector pointing TOWARD the light (screen space, y down)
  minW: number          // thickness on the fully-lit edge
  maxW: number          // thickness on the fully-shadowed edge
  litColor: RGB         // pale ink where the edge faces the light
  shadowColor: RGB      // dark ink where the edge faces away
  scale?: number        // curvature → extra corner weight
  cap?: number          // ceiling on the corner bulge (px)
  spread?: number       // how many neighbours the bulge ramps over
  closed?: boolean
}

// Port of line_weight.py's draw_lit_shape: the "line weight from ANGLE" half of
// the model that curvatureWeights alone was missing. Each vertex gets BOTH a
// weight and a colour from the light angle — the edge facing the light thins &
// pales, the edge facing away thickens & darkens — with the curvature corner-
// bulge added on top. inkStroke then lerps both between vertices, so one stroke
// shades light→shadow around its loop exactly like the Python renders (the
// figure-8, the star, the Didot/Rockwell glyphs). Returns weights + colours
// aligned to `pts`; feed both to inkStroke.
export function litShape(pts: readonly P2[], o: LitOpts):
    { weights: number[]; colors: RGB[] } {
  const n = pts.length
  const closed = o.closed ?? true
  const spread = o.spread ?? 4
  const scale = o.scale ?? 34
  const cap = o.cap ?? (o.maxW - o.minW)
  let cx = 0, cy = 0
  for (const p of pts) { cx += p[0]; cy += p[1] }
  cx /= n || 1; cy /= n || 1
  const [lx, ly] = unit(o.light[0], o.light[1])
  const litW: number[] = [], colors: RGB[] = [], bonus: number[] = []
  for (let i = 0; i < n; i++) {
    const [px, py] = pts[i]
    // Outward normal: from the centroid on a closed shape; the tangent's
    // left-hand normal on an open path (which has no inside), so both still
    // shade by angle instead of collapsing to a flat colour.
    let nx: number, ny: number
    if (closed) { [nx, ny] = unit(px - cx, py - cy) }
    else {
      const a = pts[Math.max(0, i - 1)], b = pts[Math.min(n - 1, i + 1)]
      const [tx, ty] = unit(b[0] - a[0], b[1] - a[1])
      nx = -ty; ny = tx
    }
    const lighting = nx * lx + ny * ly    // +1 faces light, -1 faces away
    const shade = (1 - lighting) / 2       // 0 = fully lit, 1 = full shadow
    litW.push(lerp(o.minW, o.maxW, shade))
    colors.push(lerpColor(o.litColor, o.shadowColor, shade))
    if (closed || (i > 0 && i < n - 1)) {
      const k = localCurvature(pts[(i - 1 + n) % n], pts[i], pts[(i + 1) % n])
      bonus.push(Math.min(cap, scale * k))
    } else bonus.push(0)
  }
  const sm = smoothSeries(bonus, spread, closed)
  return { weights: litW.map((w, i) => w + sm[i]), colors }
}

export interface InkOpts {
  amp: number           // hand-drawn sideways wander amplitude (px)
  step: number          // mean sample spacing (px)
  seed?: number         // change to boil / animate
  closed?: boolean
  sizeJitter?: number   // edge raggedness: ± fray on each side as a fraction of half-width
  density?: number      // edge-sample resolution (1 = default; >1 = finer/crisper grain)
  colors?: readonly RGB[]  // per-vertex ink colour (light→shadow sweep); flat when absent
}

// Ink a polyline as a weight-tapered hand-drawn stroke, built as a SOLID RIBBON
// whose CENTRELINE, THICKNESS and COLOUR all lerp between vertices (exactly the
// draw_textured_line taper), with a small ragged offset applied ONLY to the two
// EDGES. The core stays a single confident dip-pen line and only its boundary
// varies — instead of the old dot-cloud, where the whole width dissolved into
// grain. Each pair of resampled stations becomes one filled quad between the
// left and right edge points; flat strokes fill in ONE path, coloured strokes
// bucket their quads by a quantised colour and fill dark last, so a stroke can
// still shade light→shadow along its length like line_weight.py's lit shapes.
export function inkStroke(ctx: CanvasRenderingContext2D, pts: readonly P2[],
                          weights: readonly number[], o: InkOpts): void {
  const n = pts.length
  if (n < 2) return
  const seed = o.seed ?? 0
  const closed = o.closed ?? false
  const edgeVar = o.sizeJitter ?? 0.22          // edge raggedness (fraction of half-width)
  const cols = o.colors && o.colors.length === n ? o.colors : null
  const BLACK: RGB = [0, 0, 0]
  const segs = closed ? n : n - 1

  // Resample the path at a fine, roughly even interval so the edge grain stays
  // crisp no matter how far apart the vertices are; the low-frequency hand
  // wander still rides on o.step. Each station carries its lerped half-width and
  // (optionally) its lerped ink colour.
  const res = Math.max(1.4, 2.2 / (o.density ?? 1))
  const CX: number[] = [], CY: number[] = [], HW: number[] = [], CO: RGB[] = []
  let dist = 0
  for (let s = 0; s < segs; s++) {
    const a = pts[s], b = pts[(s + 1) % n]
    const wa = weights[s], wb = weights[(s + 1) % n]
    const ca = cols ? cols[s] : BLACK, cb = cols ? cols[(s + 1) % n] : BLACK
    const dx = b[0] - a[0], dy = b[1] - a[1]
    const len = Math.hypot(dx, dy) || 1e-6
    const nx = -dy / len, ny = dx / len
    let t = 0
    do {
      const f = t / len
      const off = vnoise((dist + t) / o.step, seed) * o.amp   // smooth centreline wander
      CX.push(lerp(a[0], b[0], f) + nx * off)
      CY.push(lerp(a[1], b[1], f) + ny * off)
      HW.push(Math.max(0.35, lerp(wa, wb, f) * 0.5))
      if (cols) CO.push(lerpColor(ca, cb, f))
      t += res
    } while (t < len)
    dist += len
  }
  if (closed) {
    CX.push(CX[0]); CY.push(CY[0]); HW.push(HW[0]); if (cols) CO.push(CO[0])
  } else {
    CX.push(pts[n - 1][0]); CY.push(pts[n - 1][1])
    HW.push(Math.max(0.35, weights[n - 1] * 0.5)); if (cols) CO.push(cols[n - 1])
  }
  const m = CX.length
  if (m < 2) return

  // Left / right edge points (and the unit normal that made them): straddle the
  // wavered centreline by ±half-width, each side nudged by its OWN blend of
  // smooth + fine noise, so the two boundaries wander and fray independently
  // while the interior stays solid.
  const LX = new Float64Array(m), LY = new Float64Array(m)
  const RX = new Float64Array(m), RY = new Float64Array(m)
  const NX = new Float64Array(m), NY = new Float64Array(m)
  for (let i = 0; i < m; i++) {
    const pi = i > 0 ? i - 1 : 0, qi = i < m - 1 ? i + 1 : m - 1
    const tx = CX[qi] - CX[pi], ty = CY[qi] - CY[pi]
    const tl = Math.hypot(tx, ty) || 1
    const nx = -ty / tl, ny = tx / tl
    NX[i] = nx; NY[i] = ny
    const grain = (kk: number) =>
      (vnoise(i * 0.5, seed + kk) * 0.5
        + (hash01(i * 1.87 + seed * (kk + 1)) * 2 - 1) * 0.5) * edgeVar * HW[i]
    const hwL = Math.max(0.16, HW[i] + grain(11))
    const hwR = Math.max(0.16, HW[i] + grain(29))
    LX[i] = CX[i] + nx * hwL; LY[i] = CY[i] + ny * hwL
    RX[i] = CX[i] - nx * hwR; RY[i] = CY[i] - ny * hwR
  }

  // Edge speckle: a fine scatter of ink grains hugging each boundary, just
  // beyond the solid core, so the rim breaks up into textured dip-pen grain
  // (like the line_weight.py plates) rather than a clean filled edge. The core
  // stays solid — only the boundary frays. Emitted deterministically per
  // station so the grain is baked, not boiling. Routed to `emit`: flat strokes
  // add arcs straight to the current path, coloured strokes bucket them by tone.
  let gk = (seed * 977) | 0
  const speckle = (emit: (x: number, y: number, r: number, ci: number) => void) => {
    for (let i = 0; i < m; i++) {
      const tx = -NY[i], ty = NX[i]                 // tangent
      for (let side = 1; side >= -1; side -= 2) {    // +1 = left rim, -1 = right rim
        const bx = side > 0 ? LX[i] : RX[i]
        const by = side > 0 ? LY[i] : RY[i]
        const count = 1 + (hash01(gk * 1.3 + 0.5) < 0.45 ? 1 : 0)
        for (let g = 0; g < count; g++) {
          gk++
          const out = (hash01(gk * 1.7) - 0.28) * (0.9 + 1.5 * edgeVar * HW[i])
          const along = (hash01(gk * 2.3 + 5.1) * 2 - 1) * 1.5
          const r = 0.5 * (0.65 + 0.7 * hash01(gk * 3.1 + 1.7))
          emit(bx + side * NX[i] * out + tx * along,
               by + side * NY[i] * out + ty * along, r, i)
        }
      }
    }
  }

  if (!cols) {
    ctx.fillStyle = ctx.strokeStyle
    ctx.beginPath()
    for (let i = 0; i < m - 1; i++) {
      ctx.moveTo(LX[i], LY[i]); ctx.lineTo(LX[i + 1], LY[i + 1])
      ctx.lineTo(RX[i + 1], RY[i + 1]); ctx.lineTo(RX[i], RY[i]); ctx.closePath()
    }
    speckle((x, y, r) => { ctx.moveTo(x + r, y); ctx.arc(x, y, r, 0, Math.PI * 2) })
    ctx.fill()
    return
  }

  // Coloured: bucket each quad by its (quantised) mean colour, then paint the
  // lightest first so the darkest ink lands on top where quads overlap — the
  // solid-ribbon analogue of line_weight.py's order-independent dark splat. Edge
  // grains bucket the same way (by their station colour) and paint on top.
  const quantKey = (r: number, g: number, b: number) =>
    ((Math.min(252, Math.round(r / 12) * 12)) << 16)
    | ((Math.min(252, Math.round(g / 12) * 12)) << 8)
    | (Math.min(252, Math.round(b / 12) * 12))
  const buckets = new Map<number, number[]>()
  for (let i = 0; i < m - 1; i++) {
    const c0 = CO[i], c1 = CO[i + 1]
    const key = quantKey((c0[0] + c1[0]) / 2, (c0[1] + c1[1]) / 2, (c0[2] + c1[2]) / 2)
    let arr = buckets.get(key)
    if (!arr) { arr = []; buckets.set(key, arr) }
    arr.push(LX[i], LY[i], LX[i + 1], LY[i + 1], RX[i + 1], RY[i + 1], RX[i], RY[i])
  }
  const dotB = new Map<number, number[]>()
  speckle((x, y, r, ci) => {
    const c = CO[ci]
    const key = quantKey(c[0], c[1], c[2])
    let arr = dotB.get(key)
    if (!arr) { arr = []; dotB.set(key, arr) }
    arr.push(x, y, r)
  })
  const bright = (key: number) => ((key >> 16) & 255) + ((key >> 8) & 255) + (key & 255)
  for (const [key, arr] of [...buckets].sort((a, b) => bright(b[0]) - bright(a[0]))) {
    ctx.fillStyle = `rgb(${(key >> 16) & 255},${(key >> 8) & 255},${key & 255})`
    ctx.beginPath()
    for (let i = 0; i < arr.length; i += 8) {
      ctx.moveTo(arr[i], arr[i + 1]); ctx.lineTo(arr[i + 2], arr[i + 3])
      ctx.lineTo(arr[i + 4], arr[i + 5]); ctx.lineTo(arr[i + 6], arr[i + 7]); ctx.closePath()
    }
    ctx.fill()
  }
  for (const [key, arr] of [...dotB].sort((a, b) => bright(b[0]) - bright(a[0]))) {
    ctx.fillStyle = `rgb(${(key >> 16) & 255},${(key >> 8) & 255},${key & 255})`
    ctx.beginPath()
    for (let i = 0; i < arr.length; i += 3) {
      ctx.moveTo(arr[i] + arr[i + 2], arr[i + 1]); ctx.arc(arr[i], arr[i + 1], arr[i + 2], 0, Math.PI * 2)
    }
    ctx.fill()
  }
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

// The panel/button border-image: a rounded-rect outline run through the SAME
// hand-drawn pipeline the roads use — `waver` for the wobble AND the
// line_weight.py model for the thickness. Every vertex carries a curvature
// weight (base thickness + a capped, smeared corner swell), and the outline is
// baked as a run of round-capped SVG segments whose stroke-width lerps between
// vertices — the SVG cousin of inkStroke's dot batch. So the frame thins on the
// straights and pools at the corners, matching the map ink instead of tracing a
// uniform line. base 10 in this 160-box, sliced 24 into a 7px border, renders
// ≈2.9px on screen (swelling at the corners) — matched to the road ink weight.
export function inkBorderUri(seed: number): string {
  const wav = waver(roundedRectPts(13, 13, 134, 134, 9),
                    { amp: 5, step: 17, seed, closed: true })
  const base = 10
  // Same light-angle model as the map ink: the frame thins/pales on the edges
  // facing the top-left light and thickens/darkens on the ones facing away,
  // plus the curvature swell at the corners. #3a322a is the mid ink colour —
  // charcoal-brown, matching the map's charcoal-on-cream dip-pen strokes.
  const mid = hexToRgb('#3a322a')
  const { weights, colors } = litShape(wav, {
    light: [-1, -1], minW: base * 0.85, maxW: base * 1.5,
    litColor: lerpColor(mid, [206, 192, 162], 0.5),
    shadowColor: lerpColor(mid, [20, 16, 12], 0.5),
    scale: 34, cap: base * 1.7, spread: 4, closed: true,
  })
  const r = (v: number) => Math.round(v * 100) / 100
  const rgb = (c: RGB) => `rgb(${Math.round(c[0])},${Math.round(c[1])},${Math.round(c[2])})`
  const n = wav.length
  let segs = ''
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n
    const a = wav[i], b = wav[j]
    // size jitter on each segment, like inkStroke, so the weight breathes.
    const wob = 1 + 0.16 * (hash01(i * 2.3 + seed * 5.1) - 0.5) * 2
    const wt = Math.max(0.6, ((weights[i] + weights[j]) / 2) * wob)
    const col = rgb(lerpColor(colors[i], colors[j], 0.5))
    segs += `<line x1='${r(a[0])}' y1='${r(a[1])}' x2='${r(b[0])}' y2='${r(b[1])}' stroke='${col}' stroke-width='${r(wt)}'/>`
  }
  const svg = "<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'>"
    + "<g fill='none' stroke-linejoin='round' "
    + "stroke-linecap='round'>" + segs + "</g></svg>"
  return 'url("data:image/svg+xml,' + encodeURIComponent(svg) + '")'
}
