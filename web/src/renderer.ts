import type { Camera } from './camera'
import type { MapGeometry, Pt, VehicleSnap } from './types'
import { hash01, waver, strokeSmooth } from './heritageArt'

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
  background: '#e9dcbb',      // aged ivory paper (matches the panels)
  asphalt: '#5a6b52',         // washed sage-green route body
  asphaltLight: '#d8c79c',    // buff casing / shoulder
  node: '#4a3826',            // brown ink survey point
  nodeControl: '#a8532c',     // terracotta control ring
  vehicleBody: '#e7d8b4',     // parchment
  vehicleOutline: '#40301e',  // warm brown ink
  vehicleBlocked: '#9c3a24',  // rust red
  buildingOutline: '#40301e', // warm brown ink
}

// Warm dip-pen ink for the manuscript outline pass.
const HERITAGE_INK = '#40301e'

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
  // gently waved (drawn as a jittered polyline that boils) so it reads as
  // hand-drafted rather than a mechanical grid. Amplitude is small to stay a
  // calm background.
  const boil = Math.floor(performance.now() / 260)
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
      const jx = (hash01(k * 5.3 + s * 1.7 + boil * 0.13) - 0.5) * 2 * amp
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
      const jy = (hash01(k * 5.3 + s * 1.7 + boil * 0.19 + 400) - 0.5) * 2 * amp
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

export function drawScene(
  ctx: CanvasRenderingContext2D,
  w: number, h: number,
  cam: Camera,
  geometry: MapGeometry | null,
  vehicles: VehicleSnap[],
  categoryOf: (buildingType: string) => string | undefined,
  overlay: EditorOverlay = {},
  heritage = false,
) {
  const pal = heritage ? { ...COLORS, ...HERITAGE } : COLORS
  ctx.fillStyle = pal.background
  ctx.fillRect(0, 0, w, h)
  if (heritage) drawSurveyGrid(ctx, w, h, cam)
  if (!geometry) return

  // Shared manuscript ink stroke: a bold, solid, continuous outline that
  // wanders with the same hand-drawn waver as the UI border-image (rounded,
  // irregular undulations) and gently boils over time. Reused for roads,
  // junctions and building footprints so every outline is hand-drawn alike.
  const boil = Math.floor(performance.now() / 155)
  const strokePolyInk = (pts: Pt[], seed: number, widthMul = 1) => {
    const base = Math.max(3, 3.4 * cam.scale) * widthMul
    ctx.lineWidth = base * (0.85 + 0.32 * hash01(seed + boil * 0.07))
    const scr = pts.map((p) => cam.toScreen(p[0], p[1], w, h) as Pt)
    const wav = waver(scr, {
      amp: Math.min(1.7, 0.6 + 0.45 * cam.scale),
      step: Math.max(10, 7 * cam.scale),
      seed: seed + boil,
      closed: true,
    })
    strokeSmooth(ctx, wav, true)
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

  // 2b. Heritage manuscript: ink the route bodies. A warm dip-pen outline
  // around every road and junction turns the flat CAD fills into inked
  // illustration on the paper. (Prohibition on "clean vector graphics".)
  if (heritage) {
    ctx.strokeStyle = HERITAGE_INK
    ctx.lineJoin = 'round'
    ctx.lineCap = 'round'
    for (const road of geometry.roads) strokePolyInk(road.polygon, road.id + 1)
    geometry.junctions.forEach((j, idx) => strokePolyInk(j.polygon, idx * 31 + 5000))
    ctx.lineCap = 'butt'
  }

  // 3. Junction edge-line curves (the fillet connectors), in the edge color the
  // backend served. Skipped in the manuscript view for pale (cream) lines.
  if (cam.scale > 0.35) {
    for (const j of geometry.junctions) {
      for (const line of j.edge_lines) {
        if (heritage && luminance(line.color) > 0.8) continue
        ctx.strokeStyle = line.color
        ctx.lineWidth = Math.max(0.5, 0.6 * cam.scale)
        polyPath(ctx, line.points, cam, w, h)
        ctx.stroke()
      }
    }
  }

  // Lane markings from the backend: amber centre boundary, dashed separators,
  // cream edge lines. In the manuscript view the pale cream EDGE lines are
  // dropped (they read as unwanted straight white lines on inked routes); the
  // amber centre/lane lines stay.
  if (cam.scale > 0.25) {
    ctx.lineCap = 'round'
    for (const road of geometry.roads) {
      ctx.lineWidth = Math.max(0.75, road.marking_width * cam.scale)
      for (const m of road.markings) {
        if (heritage && luminance(m.color) > 0.8) continue
        ctx.strokeStyle = m.color
        polyPath(ctx, m.points, cam, w, h)
        ctx.stroke()
      }
    }
    ctx.lineCap = 'butt'
  }

  // Buildings: category-colored footprints. In the manuscript view each gets
  // the same bold hand-inked, boiling outline as the roads.
  for (const b of geometry.buildings) {
    const half = b.size_ft / 2
    const [sx, sy] = cam.toScreen(b.x - half, b.y - half, w, h)
    const side = b.size_ft * cam.scale
    ctx.fillStyle = CATEGORY_COLORS[categoryOf(b.building_type) ?? '']
      ?? pal.buildingDefault
    ctx.fillRect(sx, sy, side, side)
    if (heritage) {
      ctx.strokeStyle = pal.buildingOutline
      ctx.lineJoin = 'round'
      ctx.lineCap = 'round'
      strokePolyInk([[b.x - half, b.y - half], [b.x + half, b.y - half],
                     [b.x + half, b.y + half], [b.x - half, b.y + half]],
                    b.id * 13 + 777, 0.7)
      ctx.lineCap = 'butt'
    } else {
      ctx.strokeStyle = pal.buildingOutline
      ctx.lineWidth = Math.max(1, 0.8 * cam.scale)
      ctx.strokeRect(sx, sy, side, side)
    }
  }

  // Nodes (small; controlled junctions get an accent ring).
  for (const n of geometry.nodes) {
    const [sx, sy] = cam.toScreen(n.x, n.y, w, h)
    ctx.beginPath()
    ctx.arc(sx, sy, Math.max(1.5, 1.5 * cam.scale), 0, Math.PI * 2)
    ctx.fillStyle = pal.node
    ctx.fill()
    if (n.control && n.control !== 'reservation') {
      ctx.beginPath()
      ctx.arc(sx, sy, Math.max(3, 3 * cam.scale), 0, Math.PI * 2)
      ctx.strokeStyle = pal.nodeControl
      ctx.lineWidth = heritage
        ? Math.max(2, 1.6 * cam.scale) : Math.max(1, 0.6 * cam.scale)
      ctx.stroke()
    }
  }

  // ---------------- editor overlay (selection + tool previews) ----------------

  const selRoad = overlay.selectedRoadId != null
    ? geometry.roads.find((r) => r.id === overlay.selectedRoadId) : null
  if (selRoad) {
    ctx.strokeStyle = '#ef692f'
    ctx.lineWidth = Math.max(2, 1.5 * cam.scale)
    polyPath(ctx, selRoad.centerline, cam, w, h)
    ctx.stroke()
    // Bezier control handle (drag to bend; the backend recomputes the
    // curve from wherever it lands).
    const cp = overlay.dragCurve && overlay.dragCurve.roadId === selRoad.id
      ? [overlay.dragCurve.x, overlay.dragCurve.y] as Pt
      : selRoad.control_point
    const [hx, hy] = cam.toScreen(cp[0], cp[1], w, h)
    ctx.beginPath()
    ctx.arc(hx, hy, 6, 0, Math.PI * 2)
    ctx.fillStyle = '#ef3a0c'
    ctx.fill()
    ctx.strokeStyle = '#36170c'
    ctx.lineWidth = 1.5
    ctx.stroke()
  }

  const selBuilding = overlay.selectedBuildingId != null
    ? geometry.buildings.find((b) => b.id === overlay.selectedBuildingId) : null
  if (selBuilding) {
    const half = selBuilding.size_ft / 2
    const [sx, sy] = cam.toScreen(selBuilding.x - half, selBuilding.y - half, w, h)
    ctx.strokeStyle = '#ef692f'
    ctx.lineWidth = Math.max(2, 1.2 * cam.scale)
    ctx.strokeRect(sx, sy, selBuilding.size_ft * cam.scale,
                   selBuilding.size_ft * cam.scale)
  }

  const selNode = overlay.selectedNodeId != null
    ? geometry.nodes.find((n) => n.id === overlay.selectedNodeId) : null
  if (selNode) {
    const p = overlay.dragNode && overlay.dragNode.id === selNode.id
      ? [overlay.dragNode.x, overlay.dragNode.y] as Pt
      : [selNode.x, selNode.y] as Pt
    const [sx, sy] = cam.toScreen(p[0], p[1], w, h)
    ctx.beginPath()
    ctx.arc(sx, sy, Math.max(5, 4 * cam.scale), 0, Math.PI * 2)
    ctx.strokeStyle = '#39571c'
    ctx.lineWidth = Math.max(2, cam.scale)
    ctx.stroke()
  }

  // Road-tool preview: anchor node -> cursor.
  if (overlay.roadAnchorId != null && overlay.cursorWorld) {
    const anchor = geometry.nodes.find((n) => n.id === overlay.roadAnchorId)
    if (anchor) {
      const [ax, ay] = cam.toScreen(anchor.x, anchor.y, w, h)
      const [cx, cy] = cam.toScreen(overlay.cursorWorld[0],
                                    overlay.cursorWorld[1], w, h)
      ctx.strokeStyle = '#ef692f'
      ctx.lineWidth = 2
      ctx.setLineDash([8, 6])
      ctx.beginPath()
      ctx.moveTo(ax, ay)
      ctx.lineTo(cx, cy)
      ctx.stroke()
      ctx.setLineDash([])
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
    ctx.lineWidth = 1
    ctx.strokeRect(sx, sy, g.sizeFt * cam.scale, g.sizeFt * cam.scale)
  }

  // Vehicles: oriented rectangles; a dot when too small to read.
  for (const v of vehicles) {
    const [sx, sy] = cam.toScreen(v.pos[0], v.pos[1], w, h)
    const len = VEHICLE_LENGTH_FT * cam.scale
    const wid = VEHICLE_WIDTH_FT * cam.scale
    if (len < 5) {
      ctx.beginPath()
      ctx.arc(sx, sy, 2.5, 0, Math.PI * 2)
      ctx.fillStyle = v.state === 'blocked' ? pal.vehicleBlocked : pal.vehicleOutline
      ctx.fill()
      continue
    }
    ctx.save()
    ctx.translate(sx, sy)
    ctx.rotate(Math.atan2(v.heading[1], v.heading[0]))
    ctx.fillStyle = v.state === 'blocked' ? pal.vehicleBlocked : pal.vehicleBody
    ctx.strokeStyle = pal.vehicleOutline
    // Bolder ink outline in the manuscript view (no jitter — they move, so a
    // per-frame wobble would shimmer).
    ctx.lineWidth = heritage ? Math.max(1.6, 1.1 * cam.scale) : Math.max(1, 0.5 * cam.scale)
    ctx.lineJoin = 'round'
    ctx.beginPath()
    ctx.roundRect(-len / 2, -wid / 2, len, wid, wid * 0.25)
    ctx.fill()
    ctx.stroke()
    ctx.restore()
  }
}
