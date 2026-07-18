// Mirror of the backend's mismatched-width fold limit
// (road_network.FOLD_MIN_ANGLE_DEG + violates_fold_limit). Two roads of
// DIFFERENT width meeting at one node may not fold below this inner angle:
// the continuation surface builder can't tessellate that case without a
// bowtie, so the editor keeps the pair near-straight. The server is
// authoritative and rejects any offending commit; this copy just lets a node
// drag STOP at the limit live, so the user feels the constraint instead of
// having the move snap back. Equal-width folds are never constrained.
//
// Tangents use the straight node-to-node direction (exact for straight roads,
// a close approximation for curved ones); the server's control-point-based
// check is the backstop for the curved edge cases.

import type { MapGeometry, Pt } from './types'

export const FOLD_MIN_ANGLE_DEG = 120
const MIN_DOT = Math.cos((FOLD_MIN_ANGLE_DEG * Math.PI) / 180) // = -0.5

interface V { x: number; y: number }

function sub(a: V, b: V): V { return { x: a.x - b.x, y: a.y - b.y } }
function norm(v: V): V {
  const L = Math.hypot(v.x, v.y)
  return L < 1e-9 ? { x: 0, y: 0 } : { x: v.x / L, y: v.y / L }
}

function nodePos(geo: MapGeometry, id: number): V | null {
  const n = geo.nodes.find((nd) => nd.id === id)
  return n ? { x: n.x, y: n.y } : null
}

/** The two roads touching `nodeId`, or null unless there are exactly two of
 *  differing width (the only nodes the limit constrains). Returns the fixed
 *  far endpoints of each road. */
function constrainedEnds(geo: MapGeometry, nodeId: number): [V, V] | null {
  const roads = geo.roads.filter(
    (r) => r.start_node_id === nodeId || r.end_node_id === nodeId,
  )
  if (roads.length !== 2) return null
  if (Math.abs(roads[0].total_width - roads[1].total_width) <= 1e-6) return null
  const ends: V[] = []
  for (const r of roads) {
    const otherId = r.start_node_id === nodeId ? r.end_node_id : r.start_node_id
    const p = nodePos(geo, otherId)
    if (!p) return null
    ends.push(p)
  }
  return [ends[0], ends[1]]
}

/** Inner angle at apex N subtending the segment P0–P1 is below the limit. */
function belowLimit(n: V, p0: V, p1: V): boolean {
  const a0 = norm(sub(p0, n))
  const a1 = norm(sub(p1, n))
  if ((a0.x === 0 && a0.y === 0) || (a1.x === 0 && a1.y === 0)) return false
  return a0.x * a1.x + a0.y * a1.y > MIN_DOT
}

/** Clamp apex N onto the arc where the inner angle equals the limit, keeping
 *  it on the side it is already on (inscribed-angle theorem). */
function clampToArc(n: V, p0: V, p1: V): V {
  const c = Math.hypot(p1.x - p0.x, p1.y - p0.y)
  if (c < 1e-6) return n
  const M = { x: (p0.x + p1.x) / 2, y: (p0.y + p1.y) / 2 }
  const chord = norm(sub(p1, p0))
  const perp = { x: -chord.y, y: chord.x }
  const s = (n.x - M.x) * perp.x + (n.y - M.y) * perp.y
  if (Math.abs(s) < 1e-9) return n // on the chord line => ~180deg, always valid
  const side = Math.sign(s)
  const R = c / (2 * Math.sin((FOLD_MIN_ANGLE_DEG * Math.PI) / 180))
  const d = Math.sqrt(Math.max(0, R * R - (c / 2) * (c / 2)))
  // Circle centre on the OPPOSITE side of the chord, so "inside" = angle >= limit.
  const C = { x: M.x - perp.x * side * d, y: M.y - perp.y * side * d }
  const dir = norm(sub(n, C))
  return { x: C.x + dir.x * R, y: C.y + dir.y * R }
}

/** Constrain a proposed position for `nodeId` so its two mismatched-width
 *  roads never fold below the limit. Unconstrained nodes pass through. */
export function clampNodeMove(
  geo: MapGeometry | null,
  nodeId: number,
  proposed: Pt,
): Pt {
  if (!geo) return proposed
  const ends = constrainedEnds(geo, nodeId)
  if (!ends) return proposed
  const n = { x: proposed[0], y: proposed[1] }
  if (!belowLimit(n, ends[0], ends[1])) return proposed
  const c = clampToArc(n, ends[0], ends[1])
  return [c.x, c.y]
}
