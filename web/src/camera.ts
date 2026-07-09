import type { MapGeometry, Pt } from './types'

// World <-> screen transform for pan/zoom. World units are feet (y grows
// downward, matching the backend); screen units are canvas CSS pixels.
// This is view-only state — the camera never touches world data.
export class Camera {
  scale = 0.5 // px per foot
  cx = 0 // world x at the canvas center
  cy = 0 // world y at the canvas center

  toScreen(wx: number, wy: number, w: number, h: number): Pt {
    return [(wx - this.cx) * this.scale + w / 2,
            (wy - this.cy) * this.scale + h / 2]
  }

  toWorld(sx: number, sy: number, w: number, h: number): Pt {
    return [(sx - w / 2) / this.scale + this.cx,
            (sy - h / 2) / this.scale + this.cy]
  }

  panPx(dx: number, dy: number) {
    this.cx -= dx / this.scale
    this.cy -= dy / this.scale
  }

  zoomAt(sx: number, sy: number, w: number, h: number, factor: number) {
    const [wx, wy] = this.toWorld(sx, sy, w, h)
    this.scale = Math.min(20, Math.max(0.02, this.scale * factor))
    // Keep the world point under the cursor fixed on screen.
    this.cx = wx - (sx - w / 2) / this.scale
    this.cy = wy - (sy - h / 2) / this.scale
  }

  /** Center + zoom so the whole map is visible with a margin. */
  fit(geometry: MapGeometry, w: number, h: number) {
    const xs: number[] = []
    const ys: number[] = []
    for (const n of geometry.nodes) { xs.push(n.x); ys.push(n.y) }
    for (const b of geometry.buildings) { xs.push(b.x); ys.push(b.y) }
    if (xs.length === 0) return
    const minX = Math.min(...xs), maxX = Math.max(...xs)
    const minY = Math.min(...ys), maxY = Math.max(...ys)
    this.cx = (minX + maxX) / 2
    this.cy = (minY + maxY) / 2
    const spanX = Math.max(maxX - minX, 100)
    const spanY = Math.max(maxY - minY, 100)
    this.scale = Math.min(20, Math.max(0.02,
      0.85 * Math.min(w / spanX, h / spanY)))
  }
}
