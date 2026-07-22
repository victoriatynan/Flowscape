import type { Camera } from './camera'
import type { MapGeometry, Pt, VehicleSnap } from './types'
import { hash01, waver, pathSmooth, litShape, inkStroke,
         hexToRgb, lerpColor, type P2, type RGB } from './heritageArt'
import { DEFAULT_INK, type InkConfig } from './uiConfig'

// Editor overlay state (all temporary UI state; previews are visual only —
// the backend re-validates and applies every commit).
export interface EditorOverlay {
  selectedNodeId?: number | null
  selectedRoadId?: number | null
  selectedBuildingId?: number | null
  dragNode?: { id: number; x: number; y: number } | null
  dragCurve?: { roadId: number; x: number; y: number } | null
  roadAnchorId?: number | null
  cursorWorld?: Pt | null
  buildingGhost?: { x: number; y: number; sizeFt: number } | null
}

// All colors are fantasy-24 palette values (palette.py; also served at
// /api/palette) — the project's palette-only rule extends to the browser.
const COLORS = {
  background: '#efd8a1',
  asphalt: '#4e4843',
  asphaltLight: '#655e56',
  laneLine: '#efb775',
  node: '#392a1c',
  nodeControl: '#ef692f',
  vehicleBody: '#efd8a1',
  vehicleOutline: '#36170c',
  vehicleBlocked: '#ef3a0c',
  buildingDefault: '#927e6a',
  buildingOutline: '#2a1d0d',
}

// Building fill by demand category (fantasy-24 picks; keys are the exact
// category strings destinations.py serves in the building-types schema).
const CATEGORY_COLORS: Record<string, string> = {
  'Residential': '#efac28',
  'Commercial': '#3c9f9c',
  'Industrial': '#927e6a',
  'Education': '#ef692f',
  'Public Services': '#a58c27',
  'Recreation': '#39571c',
}

// Heritage Atlas viewport skin (UI-Graphic-Design brief, Phase 3): the same
// geometry re-inked as an antique transportation atlas — aged paper, deep
// blue-green route ink, buff casings, sepia/brass detailing. Only the colours
// change; every shape is still the backend's tessellation, so the simulation
// stays exactly as readable. Applied when `heritage` is passed to drawScene.
const HERITAGE: Partial<typeof COLORS> = {
  background: '#e9dcbb',      // warm cream paper (matches the panels & the plates)
  asphalt: '#cabf9f',         // faint greige road body — read by its charcoal casing
  asphaltLight: '#dcd0ac',    // buff casing / shoulder, sits between paper and road
  node: '#2b2620',            // charcoal ink survey point
  nodeControl: '#a8532c',     // terracotta control ring (the one warm accent)
  vehicleBody: '#ece1c0',     // parchment
  vehicleOutline: '#2b2620',  // charcoal ink
  vehicleBlocked: '#9c3a24',  // rust red
  buildingOutline: '#2b2620', // charcoal ink
}

// One shared light for the whole scene, so every inked line follows the SAME
// line-weight model (line_weight.py's draw_lit_shape): top-left, screen space
// with y pointing down — matching LIGHT=(-1,-1) in the Python. Edges facing it
// thin & pale; edges facing away thicken & darken.
const LIGHT_DIR: P2 = [-1, -1]
// The light sweep runs between these anchors. A stroke's base colour is treated
// as the midtone and split into a paper-lit (pale) and a shadow (dark) end
// centred on it, so the line keeps its identity while gaining the tonal turn.
const INK_PAPER: RGB = [232, 224, 202]
const INK_DARK: RGB = [24, 19, 14]
// contrast 1 for hero silhouettes; <1 for thin detail so it stays pale. The
// lit end pulls well toward the paper (a pale grey line where the edge faces the
// light) and the shadow end well toward near-black, so a single stroke sweeps
// from faint to bold around a form like the line_weight.py circle.
function inkAnchors(hex: string, contrast: number): [RGB, RGB] {
  const mid = hexToRgb(hex)
  return [lerpColor(mid, INK_PAPER, 0.6 * contrast),
          lerpColor(mid, INK_DARK, 0.68 * contrast)]
}

// hash01 (per-element weight jitter) and the shared hand-drawn waver both come
// from heritageArt, so the road ink and the UI border-image wander alike.

// Perceived lightness [0,1] of a #rrggbb colour — used to drop the pale
// cream edge-line markings in the manuscript viewport.
function luminance(hex: string): number {
  const m = /([0-9a-f]{6})/i.exec(hex)
  if (!m) return 0.5
  const n = parseInt(m[1], 16)
  return (0.299 * ((n >> 16) & 255) + 0.587 * ((n >> 8) & 255)
    + 0.114 * (n & 255)) / 255
}

// A faint surveying grid drawn under the map: minor coordinate lines, stronger
// major lines every fifth division, and small brass drafting ticks at the
// major crossings. Kept well below readability threshold (low alpha) so it
// frames the workspace without competing with roads or vehicles.
function drawSurveyGrid(ctx: CanvasRenderingContext2D, w: number, h: number,
                        cam: Camera) {
  const steps = [5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000]
  let minor = steps[steps.length - 1]
  for (const s of steps) { if (s * cam.scale >= 26) { minor = s; break } }
  const major = minor * 5
  const [x0, y0] = cam.toWorld(0, 0, w, h)
  const [x1, y1] = cam.toWorld(w, h, w, h)
  const sx0 = Math.floor(x0 / minor) * minor
  const sy0 = Math.floor(y0 / minor) * minor

  // Warm brown surveying ink — each ruled line a randomly varied weight and
  // gently waved (a jittered polyline baked from its own line index) so it
  // reads as hand-drafted rather than a mechanical grid. The wander is static,
  // like all the map ink. Amplitude is small to stay a calm background.
  const amp = 0.9
  const seg = 34
  for (let x = sx0; x <= x1; x += minor) {
    const [px] = cam.toScreen(x, 0, w, h)
    const k = Math.round(x / minor)
    ctx.lineWidth = 0.6 + 0.8 * hash01(k * 3.7 + 1)
    ctx.strokeStyle = (k % 5 === 0)
      ? 'rgba(74, 56, 38, 0.30)' : 'rgba(74, 56, 38, 0.14)'
    ctx.beginPath()
    for (let py = 0, s = 0; py <= h + seg; py += seg, s++) {
      const jx = (hash01(k * 5.3 + s * 1.7) - 0.5) * 2 * amp
      if (py === 0) ctx.moveTo(px + jx, 0); else ctx.lineTo(px + jx, Math.min(py, h))
    }
    ctx.stroke()
  }
  for (let y = sy0; y <= y1; y += minor) {
    const [, py] = cam.toScreen(0, y, w, h)
    const k = Math.round(y / minor)
    ctx.lineWidth = 0.6 + 0.8 * hash01(k * 3.7 + 91)
    ctx.strokeStyle = (k % 5 === 0)
      ? 'rgba(74, 56, 38, 0.30)' : 'rgba(74, 56, 38, 0.14)'
    ctx.beginPath()
    for (let px = 0, s = 0; px <= w + seg; px += seg, s++) {
      const jy = (hash01(k * 5.3 + s * 1.7 + 400) - 0.5) * 2 * amp
      if (px === 0) ctx.moveTo(0, py + jy); else ctx.lineTo(Math.min(px, w), py + jy)
    }
    ctx.stroke()
  }
  // Terracotta drafting ticks at the major crossings.
  ctx.strokeStyle = 'rgba(168, 83, 44, 0.45)'
  const mx0 = Math.floor(x0 / major) * major
  const my0 = Math.floor(y0 / major) * major
  for (let x = mx0; x <= x1; x += major) {
    for (let y = my0; y <= y1; y += major) {
      const [px, py] = cam.toScreen(x, y, w, h)
      ctx.beginPath()
      ctx.moveTo(px - 3, py); ctx.lineTo(px + 3, py)
      ctx.moveTo(px, py - 3); ctx.lineTo(px, py + 3)
      ctx.stroke()
    }
  }
}

const VEHICLE_LENGTH_FT = 14
const VEHICLE_WIDTH_FT = 7

function polyPath(ctx: CanvasRenderingContext2D, pts: Pt[],
                  cam: Camera, w: number, h: number) {
  ctx.beginPath()
  pts.forEach(([x, y], i) => {
    const [sx, sy] = cam.toScreen(x, y, w, h)
    if (i === 0) ctx.moveTo(sx, sy)
    else ctx.lineTo(sx, sy)
  })
}

// Draw everything that is STATIC between camera / geometry / overlay changes —
// background, survey grid, roads, junctions, markings, buildings, nodes, and the
// editor overlay. drawScene() renders this into an offscreen cache and only
// re-runs it when the view actually changes, because the grainy dot-stamp ink is
// far too heavy to re-lay every animation frame. Vehicles are NOT drawn here;
// they move every frame and are painted live over the cached image.
function renderStatic(
  ctx: CanvasRenderingContext2D,
  w: number, h: number,
  cam: Camera,
  geometry: MapGeometry | null,
  categoryOf: (buildingType: string) => string | undefined,
  overlay: EditorOverlay,
  heritage: boolean,
  ink: InkConfig,
) {
  const pal = heritage ? { ...COLORS, ...HERITAGE } : COLORS
  // Dark dip-pen ink for every closed body outline (roads/junctions/buildings),
  // used in BOTH presets so all linework is hand-drawn — only the colour differs
  // (line_weight.py's hero-silhouette weight). In Heritage the user's ink-colour
  // knob replaces the default warm brown.
  const INK = heritage ? ink.ink : pal.buildingOutline
  ctx.fillStyle = pal.background
  ctx.fillRect(0, 0, w, h)
  if (heritage) drawSurveyGrid(ctx, w, h, cam)
  if (!geometry) return

  // Shared manuscript ink toolkit: every hand-inked line in the viewport runs
  // through these, so roads, junctions, buildings, nodes, lane markings, the
  // selection overlay and the tool previews all share one dip-pen character —
  // the same wander (waver) AND the same line-weight model (line_weight.py):
  // per-vertex weight that lerps between vertices and swells at tight corners,
  // hero outlines thick, internal detail thin.
  //
  // Each element's wobble is BAKED ONCE from a fixed per-element `seed` (no
  // time term), exactly like the vehicle bodies below: the lerp-based dot
  // stamp lays a randomly blobbing, hand-drawn stroke that stays put, so the
  // map reads as still ink on paper instead of every line shimmering.
  const toScr = (pts: readonly Pt[]) =>
    pts.map((p) => cam.toScreen(p[0], p[1], w, h) as P2)

  // Bold closed outline (roads / junctions / buildings): thick hero weight that
  // pools at corners. `strokeStyle` is set by the caller.
  const strokePolyInk = (pts: readonly Pt[], seed: number, widthMul = 1) => {
    const scr = toScr(pts)
    // A fine, confident dip-pen line like the line_weight.py plates: modest
    // weight that stays a LINE (capped so it can't balloon into a fat band at
    // high zoom), a gentle light→shadow taper, and only a slight swell at
    // corners — not the heavy pooling that clumps junctions into ink blobs.
    const base = Math.min(4.5, Math.max(1.8, 1.9 * cam.scale)) * widthMul
      * (0.9 + 0.22 * hash01(seed)) * ink.weight
    const [lit, shadow] = inkAnchors(ctx.strokeStyle as string, 1)
    // Wide weight swing (thin lit edge → thick shadow edge) is what reads as a
    // lit form rather than an even outline — the circle in line_weight.py.
    const { weights, colors } = litShape(scr, {
      light: LIGHT_DIR, minW: base * 0.55, maxW: base * 1.9,
      litColor: lit, shadowColor: shadow,
      scale: 16, cap: base * 0.7, spread: 5, closed: true,
    })
    inkStroke(ctx, scr, weights, {
      amp: Math.min(0.85, 0.3 + 0.22 * cam.scale) * ink.wobble,
      step: Math.max(10, 7 * cam.scale), seed,
      closed: true, sizeJitter: 0.4 * ink.wobble, density: ink.density, colors,
    })
  }

  // Thin detail line (lane markings, edge-line fillets, previews). Open or
  // closed; the pale internal-detail weight so it never fights a silhouette.
  const strokeInkLine = (pts: readonly Pt[], seed: number, weight: number,
                         closed = false, worldPts = true) => {
    const scr = worldPts ? toScr(pts) : (pts as readonly P2[])
    const wt = weight * ink.weight
    const [lit, shadow] = inkAnchors(ctx.strokeStyle as string, 0.6)
    const { weights, colors } = litShape(scr, {
      light: LIGHT_DIR, minW: wt * 0.95, maxW: wt * 1.2,
      litColor: lit, shadowColor: shadow,
      scale: 10, cap: wt * 0.8, spread: 3, closed,
    })
    inkStroke(ctx, scr, weights, {
      amp: Math.min(0.7, 0.25 + 0.2 * cam.scale) * ink.wobble,
      step: Math.max(8, 6 * cam.scale), seed,
      closed, sizeJitter: 0.35 * ink.wobble, density: ink.density, colors,
    })
  }

  // A hand-drawn ring (node control rings, selection rings, curve handle).
  // Centre + radius in SCREEN px so it works for overlay handles too.
  const inkRing = (cxp: number, cyp: number, r: number, seed: number,
                   weight: number) => {
    const N = Math.max(10, Math.round(r * 0.9))
    const cp: P2[] = []
    for (let i = 0; i < N; i++) {
      const a = (i / N) * Math.PI * 2
      cp.push([cxp + r * Math.cos(a), cyp + r * Math.sin(a)])
    }
    strokeInkLine(cp, seed, weight, true, false)
  }

  // A small filled node dot with a wobbly rim (fills the same smooth path it
  // would stroke, so the blob and its edge share one wobble).
  const inkBlob = (cxp: number, cyp: number, r: number, seed: number) => {
    const N = Math.max(8, Math.round(r * 1.4))
    const cp: P2[] = []
    for (let i = 0; i < N; i++) {
      const a = (i / N) * Math.PI * 2
      cp.push([cxp + r * Math.cos(a), cyp + r * Math.sin(a)])
    }
    const wav = waver(cp, {
      amp: Math.max(0.4, r * 0.16), step: Math.max(3, r * 0.7),
      seed, closed: true,
    })
    pathSmooth(ctx, wav, true)
    ctx.fill()
  }

  // All geometry below is backend-tessellated (build_node_surfaces — the
  // same pass the pygame editor draws from). Layering mirrors the editor:
  // shoulders under, asphalt on top, junction surfaces bridging the
  // trimmed road mouths, dead-end caps, then edge-line curves.

  // 1. Shoulder/sidewalk layer.
  for (const road of geometry.roads) {
    if (!road.shoulder_polygon) continue
    ctx.fillStyle = heritage ? pal.asphaltLight
      : (road.shoulder_color ?? COLORS.asphaltLight)
    polyPath(ctx, road.shoulder_polygon, cam, w, h)
    ctx.closePath()
    ctx.fill()
  }
  for (const j of geometry.junctions) {
    if (!j.outer_polygon) continue
    ctx.fillStyle = heritage ? pal.asphaltLight
      : (j.outer_color ?? COLORS.asphaltLight)
    polyPath(ctx, j.outer_polygon, cam, w, h)
    ctx.closePath()
    ctx.fill()
  }

  // 2. Asphalt layer: trimmed road bodies + junction surfaces + caps.
  ctx.fillStyle = pal.asphalt
  for (const road of geometry.roads) {
    polyPath(ctx, road.polygon, cam, w, h)
    ctx.closePath()
    ctx.fill()
  }
  for (const j of geometry.junctions) {
    polyPath(ctx, j.polygon, cam, w, h)
    ctx.closePath()
    ctx.fill()
  }
  for (const cap of geometry.caps) {
    const [sx, sy] = cam.toScreen(cap.pos[0], cap.pos[1], w, h)
    ctx.beginPath()
    ctx.arc(sx, sy, cap.radius * cam.scale, 0, Math.PI * 2)
    ctx.fill()
  }

  // 2b. Ink the route bodies. A dip-pen outline around every road and junction
  // turns the flat CAD fills into inked illustration — always on, so the default
  // and Heritage presets share identical hand-drawn linework (only the palette
  // differs). Matches the outlined, weight-tapered shapes line_weight.py makes.
  ctx.strokeStyle = INK
  ctx.lineJoin = 'round'
  ctx.lineCap = 'round'
  for (const road of geometry.roads) strokePolyInk(road.polygon, road.id + 1)
  geometry.junctions.forEach((j, idx) => strokePolyInk(j.polygon, idx * 31 + 5000))
  ctx.lineCap = 'butt'

  // 3. Junction edge-line curves (the fillet connectors), in the edge color the
  // backend served. Skipped in the manuscript view for pale (cream) lines.
  if (cam.scale > 0.35) {
    geometry.junctions.forEach((j, ji) => {
      j.edge_lines.forEach((line, li) => {
        if (heritage && luminance(line.color) > 0.8) return
        ctx.strokeStyle = line.color
        // Inked as thin internal detail so the fillets read hand-drawn too.
        strokeInkLine(line.points, ji * 97 + li * 7 + 20000,
                      Math.max(0.7, 0.7 * cam.scale))
      })
    })
  }

  // Lane markings from the backend: amber centre boundary, dashed separators,
  // cream edge lines. In the manuscript view the pale cream EDGE lines are
  // dropped (they read as unwanted straight white lines on inked routes); the
  // amber centre/lane lines stay.
  if (cam.scale > 0.25) {
    ctx.lineCap = 'round'
    geometry.roads.forEach((road) => {
      const mw = Math.max(0.75, road.marking_width * cam.scale)
      road.markings.forEach((m, mi) => {
        if (heritage && luminance(m.color) > 0.8) return
        ctx.strokeStyle = m.color
        // Centre/lane lines drawn as a thin, gently wandering pen line.
        strokeInkLine(m.points, road.id * 131 + mi * 11 + 40000, mw)
      })
    })
    ctx.lineCap = 'butt'
  }

  // Buildings: category-colored footprints. In the manuscript view each gets
  // the same bold hand-inked, boiling outline as the roads.
  // In the manuscript view the saturated category colours are pulled halfway to
  // the cream paper so each footprint reads as a soft watercolour wash under the
  // charcoal ink, not a flat digital swatch.
  const paperRgb = hexToRgb(pal.background)
  const fillFor = (hex: string) =>
    heritage ? `rgb(${lerpColor(hexToRgb(hex), paperRgb, 0.5)
      .map((c) => Math.round(c)).join(',')})` : hex
  for (const b of geometry.buildings) {
    const half = b.size_ft / 2
    const [sx, sy] = cam.toScreen(b.x - half, b.y - half, w, h)
    const side = b.size_ft * cam.scale
    ctx.fillStyle = fillFor(CATEGORY_COLORS[categoryOf(b.building_type) ?? '']
      ?? pal.buildingDefault)
    ctx.fillRect(sx, sy, side, side)
    ctx.strokeStyle = pal.buildingOutline
    ctx.lineJoin = 'round'
    ctx.lineCap = 'round'
    strokePolyInk([[b.x - half, b.y - half], [b.x + half, b.y - half],
                   [b.x + half, b.y + half], [b.x - half, b.y + half]],
                  b.id * 13 + 777, 0.7)
    ctx.lineCap = 'butt'
  }

  // Nodes (small; controlled junctions get an accent ring). In the manuscript
  // view the survey point is a hand-inked blob and its control ring a wobbly
  // pen circle, so even these tiny marks read as drawn rather than plotted.
  for (const n of geometry.nodes) {
    const [sx, sy] = cam.toScreen(n.x, n.y, w, h)
    ctx.fillStyle = pal.node
    inkBlob(sx, sy, Math.max(1.8, 1.7 * cam.scale), n.id * 17 + 60000)
    if (n.control && n.control !== 'reservation') {
      ctx.strokeStyle = pal.nodeControl
      inkRing(sx, sy, Math.max(3, 3 * cam.scale), n.id * 29 + 61000,
              Math.max(1.6, 1.4 * cam.scale))
    }
  }

  // ---------------- editor overlay (selection + tool previews) ----------------

  // The selection accent, inked as its own seed so the highlight boils in step
  // with the map. worldRect: the four corners of a footprint, ready to ink.
  const worldRect = (cx: number, cy: number, half: number): Pt[] =>
    [[cx - half, cy - half], [cx + half, cy - half],
     [cx + half, cy + half], [cx - half, cy + half]]

  const selRoad = overlay.selectedRoadId != null
    ? geometry.roads.find((r) => r.id === overlay.selectedRoadId) : null
  if (selRoad) {
    ctx.strokeStyle = '#ef692f'
    strokeInkLine(selRoad.centerline, selRoad.id * 53 + 70000,
                  Math.max(2, 1.5 * cam.scale))
    // Bezier control handle (drag to bend; the backend recomputes the
    // curve from wherever it lands).
    const cp = overlay.dragCurve && overlay.dragCurve.roadId === selRoad.id
      ? [overlay.dragCurve.x, overlay.dragCurve.y] as Pt
      : selRoad.control_point
    const [hx, hy] = cam.toScreen(cp[0], cp[1], w, h)
    ctx.fillStyle = '#ef3a0c'
    inkBlob(hx, hy, 6, 71000)
    ctx.strokeStyle = '#36170c'
    inkRing(hx, hy, 6, 71500, 1.5)
  }

  const selBuilding = overlay.selectedBuildingId != null
    ? geometry.buildings.find((b) => b.id === overlay.selectedBuildingId) : null
  if (selBuilding) {
    const half = selBuilding.size_ft / 2
    ctx.strokeStyle = '#ef692f'
    strokeInkLine(worldRect(selBuilding.x, selBuilding.y, half),
                  selBuilding.id * 43 + 72000,
                  Math.max(2, 1.2 * cam.scale), true)
  }

  const selNode = overlay.selectedNodeId != null
    ? geometry.nodes.find((n) => n.id === overlay.selectedNodeId) : null
  if (selNode) {
    const p = overlay.dragNode && overlay.dragNode.id === selNode.id
      ? [overlay.dragNode.x, overlay.dragNode.y] as Pt
      : [selNode.x, selNode.y] as Pt
    const [sx, sy] = cam.toScreen(p[0], p[1], w, h)
    ctx.strokeStyle = '#39571c'
    inkRing(sx, sy, Math.max(5, 4 * cam.scale), selNode.id * 37 + 73000,
            Math.max(2, cam.scale))
  }

  // Road-tool preview: anchor node -> cursor.
  if (overlay.roadAnchorId != null && overlay.cursorWorld) {
    const anchor = geometry.nodes.find((n) => n.id === overlay.roadAnchorId)
    if (anchor) {
      const [ax, ay] = cam.toScreen(anchor.x, anchor.y, w, h)
      const [cx, cy] = cam.toScreen(overlay.cursorWorld[0],
                                    overlay.cursorWorld[1], w, h)
      ctx.strokeStyle = '#ef692f'
      // The rubber-band preview inked as a wandering pen line.
      strokeInkLine([[ax, ay], [cx, cy]], 74000, 2, false, false)
    }
  }

  // Building-tool ghost footprint at the cursor.
  if (overlay.buildingGhost) {
    const g = overlay.buildingGhost
    const half = g.sizeFt / 2
    const [sx, sy] = cam.toScreen(g.x - half, g.y - half, w, h)
    ctx.globalAlpha = 0.45
    ctx.fillStyle = pal.buildingDefault
    ctx.fillRect(sx, sy, g.sizeFt * cam.scale, g.sizeFt * cam.scale)
    ctx.globalAlpha = 1
    ctx.strokeStyle = pal.buildingOutline
    strokeInkLine(worldRect(g.x, g.y, half), 75000, Math.max(1.4, cam.scale), true)
  }

}

// A rounded-rectangle outline in the vehicle's local frame, ready to ink.
// Sampled so the hand-drawn outline stays smooth at any size.
function carPts(len: number, wid: number, r: number): P2[] {
  const x0 = -len / 2, y0 = -wid / 2, x1 = len / 2, y1 = wid / 2
  const p: P2[] = []
  const arc = (cx: number, cy: number, a0: number, a1: number) => {
    for (let i = 0; i <= 3; i++) {
      const a = a0 + (a1 - a0) * i / 3
      p.push([cx + r * Math.cos(a), cy + r * Math.sin(a)])
    }
  }
  p.push([x0 + r, y0]); p.push([x1 - r, y0]); arc(x1 - r, y0 + r, -Math.PI / 2, 0)
  p.push([x1, y1 - r]); arc(x1 - r, y1 - r, 0, Math.PI / 2)
  p.push([x0 + r, y1]); arc(x0 + r, y1 - r, Math.PI / 2, Math.PI)
  p.push([x0, y0 + r]); arc(x0 + r, y0 + r, Math.PI, Math.PI * 1.5)
  return p
}

// A small filled node/vehicle dot with a wobbly, grainy rim (screen-space).
function inkBlobAt(ctx: CanvasRenderingContext2D, cxp: number, cyp: number,
                  r: number, seed: number) {
  const N = Math.max(8, Math.round(r * 1.4))
  const cp: P2[] = []
  for (let i = 0; i < N; i++) {
    const a = (i / N) * Math.PI * 2
    cp.push([cxp + r * Math.cos(a), cyp + r * Math.sin(a)])
  }
  const wav = waver(cp, {
    amp: Math.max(0.4, r * 0.16), step: Math.max(3, r * 0.7), seed, closed: true,
  })
  pathSmooth(ctx, wav, true)
  ctx.fill()
}

// Vehicles: oriented rectangles with a grainy inked outline; a dot when too
// small to read. Painted LIVE every frame over the cached static map. Each body
// is wavered ONCE with a fixed per-vehicle seed (no boil) so the wobble is baked
// in and rotates rigidly with the car — inked, never shimmering.
function drawVehicles(ctx: CanvasRenderingContext2D, w: number, h: number,
                      cam: Camera, vehicles: VehicleSnap[], pal: typeof COLORS) {
  for (const v of vehicles) {
    const [sx, sy] = cam.toScreen(v.pos[0], v.pos[1], w, h)
    const len = VEHICLE_LENGTH_FT * cam.scale
    const wid = VEHICLE_WIDTH_FT * cam.scale
    if (len < 5) {
      ctx.fillStyle = v.state === 'blocked' ? pal.vehicleBlocked : pal.vehicleOutline
      inkBlobAt(ctx, sx, sy, 2.5, v.id * 7)
      continue
    }
    ctx.save()
    ctx.translate(sx, sy)
    const hd = Math.atan2(v.heading[1], v.heading[0])
    ctx.rotate(hd)
    ctx.fillStyle = v.state === 'blocked' ? pal.vehicleBlocked : pal.vehicleBody
    ctx.strokeStyle = pal.vehicleOutline
    const wav = waver(carPts(len, wid, wid * 0.25), {
      amp: Math.min(1.1, 0.5 * cam.scale), step: Math.max(6, 4 * cam.scale),
      seed: v.id * 13, closed: true,
    })
    pathSmooth(ctx, wav, true)
    ctx.fill()
    const wt = Math.max(1.4, 1.0 * cam.scale)
    // Rotate the global light into the car's local frame (the context is rotated
    // by heading), so every car shades from the SAME world-space light source.
    const cL = Math.cos(-hd), sL = Math.sin(-hd)
    const ll: P2 = [LIGHT_DIR[0] * cL - LIGHT_DIR[1] * sL,
                    LIGHT_DIR[0] * sL + LIGHT_DIR[1] * cL]
    const [lit, shadow] = inkAnchors(ctx.strokeStyle as string, 0.85)
    const { weights, colors } = litShape(wav, {
      light: ll, minW: wt * 0.85, maxW: wt * 1.5,
      litColor: lit, shadowColor: shadow,
      scale: 14, cap: wt * 1.4, spread: 3, closed: true,
    })
    inkStroke(ctx, wav, weights, {
      amp: 0, step: Math.max(4, 3 * cam.scale), seed: v.id * 13,
      closed: true, sizeJitter: 0.18, colors,
    })
    ctx.restore()
  }
}

// ---------------------------------------------------------------------------
// Offscreen cache: the static map is re-inked only when the view, geometry, or
// overlay changes; otherwise every frame just blits the cached bitmap and draws
// the moving vehicles on top. Keeps the grainy dot-stamp ink affordable during
// the simulation (which redraws at animation frame rate).
// ---------------------------------------------------------------------------
let cacheCanvas: HTMLCanvasElement | null = null
let cacheKey = ''
let cacheGeom: MapGeometry | null = null

export function drawScene(
  ctx: CanvasRenderingContext2D,
  w: number, h: number,
  cam: Camera,
  geometry: MapGeometry | null,
  vehicles: VehicleSnap[],
  categoryOf: (buildingType: string) => string | undefined,
  overlay: EditorOverlay = {},
  heritage = false,
  ink: InkConfig = DEFAULT_INK,
) {
  const pal = heritage ? { ...COLORS, ...HERITAGE } : COLORS
  const dpr = ctx.getTransform().a || 1

  // No geometry yet: just the paper (+ grid), nothing to cache.
  if (!geometry) {
    ctx.fillStyle = pal.background
    ctx.fillRect(0, 0, w, h)
    if (heritage) drawSurveyGrid(ctx, w, h, cam)
    return
  }

  // Cache key: everything the STATIC layer depends on except geometry identity
  // (compared by reference). Camera pan is captured via the screen origin.
  const [ox, oy] = cam.toScreen(0, 0, w, h)
  const key = `${ox.toFixed(2)}|${oy.toFixed(2)}|${cam.scale}|${w}|${h}|${dpr}`
    + `|${heritage}|${JSON.stringify(overlay)}`
    + `|${ink.wobble}|${ink.weight}|${ink.density}|${ink.ink}`
  const cw = Math.max(1, Math.round(w * dpr))
  const chh = Math.max(1, Math.round(h * dpr))

  if (geometry !== cacheGeom || key !== cacheKey || !cacheCanvas
      || cacheCanvas.width !== cw || cacheCanvas.height !== chh) {
    if (!cacheCanvas) cacheCanvas = document.createElement('canvas')
    cacheCanvas.width = cw
    cacheCanvas.height = chh
    const cctx = cacheCanvas.getContext('2d')!
    cctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    cctx.clearRect(0, 0, w, h)
    renderStatic(cctx, w, h, cam, geometry, categoryOf, overlay, heritage, ink)
    cacheGeom = geometry
    cacheKey = key
  }

  // Blit the cached static map 1:1 (device px), then vehicles live on top.
  ctx.save()
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  ctx.drawImage(cacheCanvas, 0, 0)
  ctx.restore()
  drawVehicles(ctx, w, h, cam, vehicles, pal)
}
