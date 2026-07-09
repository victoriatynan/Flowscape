import type { Camera } from './camera'
import type { MapGeometry, Pt, VehicleSnap } from './types'

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
) {
  ctx.fillStyle = COLORS.background
  ctx.fillRect(0, 0, w, h)
  if (!geometry) return

  // All geometry below is backend-tessellated (build_node_surfaces — the
  // same pass the pygame editor draws from). Layering mirrors the editor:
  // shoulders under, asphalt on top, junction surfaces bridging the
  // trimmed road mouths, dead-end caps, then edge-line curves.

  // 1. Shoulder/sidewalk layer.
  for (const road of geometry.roads) {
    if (!road.shoulder_polygon) continue
    ctx.fillStyle = road.shoulder_color ?? COLORS.asphaltLight
    polyPath(ctx, road.shoulder_polygon, cam, w, h)
    ctx.closePath()
    ctx.fill()
  }
  for (const j of geometry.junctions) {
    if (!j.outer_polygon) continue
    ctx.fillStyle = j.outer_color ?? COLORS.asphaltLight
    polyPath(ctx, j.outer_polygon, cam, w, h)
    ctx.closePath()
    ctx.fill()
  }

  // 2. Asphalt layer: trimmed road bodies + junction surfaces + caps.
  ctx.fillStyle = COLORS.asphalt
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

  // 3. Junction edge-line curves (the fillet connectors), in the edge
  // color the backend served, once zoomed in enough to read them.
  if (cam.scale > 0.35) {
    for (const j of geometry.junctions) {
      for (const line of j.edge_lines) {
        ctx.strokeStyle = line.color
        ctx.lineWidth = Math.max(0.5, 0.6 * cam.scale)
        polyPath(ctx, line.points, cam, w, h)
        ctx.stroke()
      }
    }
  }

  // Lane markings, straight from the backend (road_style boundary layout):
  // amber center boundary, dashed separators between same-direction lanes,
  // cream edge lines. Dash on/off runs are pre-cut server-side by arc
  // length (marking_segments), so each served polyline is stroked solid --
  // no divider ever runs through the middle of a lane.
  if (cam.scale > 0.25) {
    ctx.lineCap = 'round'
    for (const road of geometry.roads) {
      ctx.lineWidth = Math.max(0.75, road.marking_width * cam.scale)
      for (const m of road.markings) {
        ctx.strokeStyle = m.color
        polyPath(ctx, m.points, cam, w, h)
        ctx.stroke()
      }
    }
    ctx.lineCap = 'butt'
  }

  // Buildings: category-colored footprint squares.
  for (const b of geometry.buildings) {
    const half = b.size_ft / 2
    const [sx, sy] = cam.toScreen(b.x - half, b.y - half, w, h)
    const side = b.size_ft * cam.scale
    ctx.fillStyle = CATEGORY_COLORS[categoryOf(b.building_type) ?? '']
      ?? COLORS.buildingDefault
    ctx.fillRect(sx, sy, side, side)
    ctx.strokeStyle = COLORS.buildingOutline
    ctx.lineWidth = Math.max(1, 0.8 * cam.scale)
    ctx.strokeRect(sx, sy, side, side)
  }

  // Nodes (small; controlled junctions get an accent ring).
  for (const n of geometry.nodes) {
    const [sx, sy] = cam.toScreen(n.x, n.y, w, h)
    ctx.beginPath()
    ctx.arc(sx, sy, Math.max(1.5, 1.5 * cam.scale), 0, Math.PI * 2)
    ctx.fillStyle = COLORS.node
    ctx.fill()
    if (n.control && n.control !== 'reservation') {
      ctx.beginPath()
      ctx.arc(sx, sy, Math.max(3, 3 * cam.scale), 0, Math.PI * 2)
      ctx.strokeStyle = COLORS.nodeControl
      ctx.lineWidth = Math.max(1, 0.6 * cam.scale)
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
    ctx.fillStyle = COLORS.buildingDefault
    ctx.fillRect(sx, sy, g.sizeFt * cam.scale, g.sizeFt * cam.scale)
    ctx.globalAlpha = 1
    ctx.strokeStyle = COLORS.buildingOutline
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
      ctx.fillStyle = v.state === 'blocked' ? COLORS.vehicleBlocked : COLORS.vehicleOutline
      ctx.fill()
      continue
    }
    ctx.save()
    ctx.translate(sx, sy)
    ctx.rotate(Math.atan2(v.heading[1], v.heading[0]))
    ctx.fillStyle = v.state === 'blocked' ? COLORS.vehicleBlocked : COLORS.vehicleBody
    ctx.strokeStyle = COLORS.vehicleOutline
    ctx.lineWidth = Math.max(1, 0.5 * cam.scale)
    ctx.beginPath()
    ctx.roundRect(-len / 2, -wid / 2, len, wid, wid * 0.25)
    ctx.fill()
    ctx.stroke()
    ctx.restore()
  }
}
