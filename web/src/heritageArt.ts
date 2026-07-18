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
  sizeJitter?: number   // random ± fraction on each dot's weight (0 = none)
  colors?: readonly RGB[]  // per-vertex ink colour (light→shadow sweep); flat when absent
}

// A fixed, fine nib radius (px): the whole stroke is built from dots this size,
// so a thick line is many nib dots packed across its width rather than one fat
// mark — that packing (plus per-dot jitter) is what reads as grainy dip-pen ink.
const NIB = 0.6

// Ink a polyline as a weight-tapered, GRAINY hand-drawn stroke. Resamples the
// path at irregular intervals with the shared `waver` wander, lerps the weight
// between vertices (draw_textured_line's taper), then fills each span's cross-
// section with fine nib dots — jittered in position and size — instead of a
// clean segment. This is the canvas port of line_weight.py's stamp_weighted_path
// dot batch: overlapping opaque dots give a solid core with a ragged, speckled
// edge, and the weight (which swells at corners) just adds more dots across, so
// ink "pools" heavier there. Every dot is batched into ONE Path2D + a single
// fill() per stroke, so a whole road casing is one fill, not thousands.
export function inkStroke(ctx: CanvasRenderingContext2D, pts: readonly P2[],
                          weights: readonly number[], o: InkOpts): void {
  const n = pts.length
  if (n < 2) return
  const seed = o.seed ?? 0
  const closed = o.closed ?? false
  const sj = o.sizeJitter ?? 0.22
  const cols = o.colors && o.colors.length === n ? o.colors : null
  const segs = closed ? n : n - 1
  const S: [number, number, number][] = []   // [x, y, weight] per sample
  const SC: RGB[] = []                         // per-sample ink colour (if cols)
  let dist = 0
  for (let s = 0; s < segs; s++) {
    const a = pts[s], b = pts[(s + 1) % n]
    const wa = weights[s], wb = weights[(s + 1) % n]
    const ca = cols ? cols[s] : null, cb = cols ? cols[(s + 1) % n] : null
    const dx = b[0] - a[0], dy = b[1] - a[1]
    const len = Math.hypot(dx, dy) || 1e-6
    const nx = -dy / len, ny = dx / len
    let t = 0
    do {
      const phase = (dist + t) / o.step
      const off = vnoise(phase, seed) * o.amp
      const f = t / len
      const wob = 1 + sj * (hash01(phase * 2.3 + seed * 5.1) - 0.5) * 2
      const w = Math.max(0.4, lerp(wa, wb, f) * wob)
      S.push([lerp(a[0], b[0], f) + nx * off, lerp(a[1], b[1], f) + ny * off, w])
      if (cols) SC.push(lerpColor(ca as RGB, cb as RGB, f))
      t += o.step * (0.55 + 0.9 * hash01(phase * 1.7 + seed * 9.13))
    } while (t < len)
    dist += len
  }
  if (closed && S.length) { S.push(S[0]); if (cols) SC.push(SC[0]) }
  else if (!closed) {
    S.push([pts[n - 1][0], pts[n - 1][1], weights[n - 1]])
    if (cols) SC.push(cols[n - 1])
  }

  // Stamp nib dots along and across each span. Flat strokes batch into ONE
  // fill(); coloured strokes bucket dots by a quantised colour and fill once
  // per bucket (dark buckets last, so overlaps darken like the Python splat) —
  // the canvas analogue of line_weight.py grouping its dot splat by radius.
  const along = NIB * 2.0                      // dot spacing along the path
  let k = (seed * 131) | 0                      // deterministic per-dot RNG index
  const buckets = cols ? new Map<number, number[]>() : null
  if (!cols) { ctx.fillStyle = ctx.strokeStyle; ctx.beginPath() }
  for (let i = 0; i < S.length - 1; i++) {
    const p = S[i], q = S[i + 1]
    const dx = q[0] - p[0], dy = q[1] - p[1]
    const len = Math.hypot(dx, dy) || 1e-6
    const ux = dx / len, uy = dy / len          // tangent
    const nx = -uy, ny = ux                      // normal
    const steps = Math.max(1, Math.round(len / along))
    for (let s = 0; s < steps; s++) {
      const f = s / steps
      const cx = lerp(p[0], q[0], f), cy = lerp(p[1], q[1], f)
      const half = Math.max(0.5, lerp(p[2], q[2], f) * 0.5)
      // dots across the thickness (more where the line is thicker / at corners)
      const ribs = Math.min(12, Math.max(1, Math.round((2 * half) / (NIB * 1.3))))
      // this station's colour (same across the thickness), quantised to a bucket
      let arr: number[] | null = null
      if (cols) {
        const cc = lerpColor(SC[i], SC[i + 1], f)
        const qr = Math.min(252, Math.round(cc[0] / 12) * 12)
        const qg = Math.min(252, Math.round(cc[1] / 12) * 12)
        const qb = Math.min(252, Math.round(cc[2] / 12) * 12)
        const key = (qr << 16) | (qg << 8) | qb
        arr = buckets!.get(key) ?? null
        if (!arr) { arr = []; buckets!.set(key, arr) }
      }
      for (let m = 0; m < ribs; m++) {
        k++
        const frac = ribs > 1 ? m / (ribs - 1) - 0.5 : 0     // -0.5..0.5 across
        const jN = hash01(k * 1.73) * 2 - 1
        const jT = hash01(k * 2.91 + 7.1) * 2 - 1
        const jR = hash01(k * 3.57 + 3.3)
        const offN = frac * 2 * half + jN * NIB * 0.85       // across + jitter
        const offT = jT * NIB * 0.85                          // along jitter
        const rr = Math.max(0.3, NIB * (0.7 + 0.55 * jR))
        const x = cx + nx * offN + ux * offT
        const y = cy + ny * offN + uy * offT
        if (arr) { arr.push(x, y, rr) }
        else {
          ctx.moveTo(x + rr, y)                               // avoid connector
          ctx.arc(x, y, rr, 0, Math.PI * 2)
        }
      }
    }
  }
  if (!buckets) { ctx.fill(); return }
  // Paint lightest buckets first so the darkest ink lands on top at overlaps.
  const bright = (key: number) => ((key >> 16) & 255) + ((key >> 8) & 255) + (key & 255)
  for (const [key, arr] of [...buckets].sort((a, b) => bright(b[0]) - bright(a[0]))) {
    ctx.fillStyle = `rgb(${(key >> 16) & 255},${(key >> 8) & 255},${key & 255})`
    ctx.beginPath()
    for (let i = 0; i < arr.length; i += 3) {
      ctx.moveTo(arr[i] + arr[i + 2], arr[i + 1])
      ctx.arc(arr[i], arr[i + 1], arr[i + 2], 0, Math.PI * 2)
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
  // plus the curvature swell at the corners. #5a4632 is the mid ink colour.
  const mid = hexToRgb('#5a4632')
  const { weights, colors } = litShape(wav, {
    light: [-1, -1], minW: base * 0.85, maxW: base * 1.5,
    litColor: lerpColor(mid, [214, 198, 166], 0.5),
    shadowColor: lerpColor(mid, [26, 20, 14], 0.5),
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
