import type { GeometryBuilding, GeometryNode, GeometryRoad, MapGeometry } from './types'

// Selection hit-testing (temporary UI state — picking what a click refers
// to happens client-side; every actual mutation goes through the backend).

export function nodeAt(geo: MapGeometry, wx: number, wy: number,
                       maxDistFt: number): GeometryNode | null {
  let best: GeometryNode | null = null
  let bestD = maxDistFt
  for (const n of geo.nodes) {
    const d = Math.hypot(n.x - wx, n.y - wy)
    if (d <= bestD) { bestD = d; best = n }
  }
  return best
}

export function buildingAt(geo: MapGeometry, wx: number,
                           wy: number): GeometryBuilding | null {
  // Topmost (last drawn) footprint square containing the point.
  for (let i = geo.buildings.length - 1; i >= 0; i--) {
    const b = geo.buildings[i]
    const half = b.size_ft / 2
    if (Math.abs(wx - b.x) <= half && Math.abs(wy - b.y) <= half) return b
  }
  return null
}

export function roadAt(geo: MapGeometry, wx: number, wy: number,
                       thresholdFt: number): GeometryRoad | null {
  let best: GeometryRoad | null = null
  let bestD = thresholdFt
  for (const road of geo.roads) {
    const pts = road.centerline
    for (let i = 0; i < pts.length - 1; i++) {
      const d = pointSegDist(wx, wy, pts[i][0], pts[i][1],
                             pts[i + 1][0], pts[i + 1][1])
      if (d <= bestD) { bestD = d; best = road }
    }
  }
  return best
}

function pointSegDist(px: number, py: number, ax: number, ay: number,
                      bx: number, by: number): number {
  const dx = bx - ax, dy = by - ay
  const len2 = dx * dx + dy * dy
  const t = len2 === 0 ? 0
    : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2))
  return Math.hypot(px - (ax + dx * t), py - (ay + dy * t))
}
