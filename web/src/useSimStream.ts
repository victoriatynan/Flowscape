import { useEffect, useRef, useState } from 'react'
import type { Pt, SimSnapshot, VehicleSnap } from './types'

// Live simulation stream over /ws/sim, with client-side interpolation:
// the backend broadcasts ~15 snapshots/sec; rendering runs at the display
// rate and lerps vehicle positions between the last two snapshots (matched
// by stable vehicle id). Interpolation is VISUAL ONLY — no simulation
// behavior is ever computed here.

interface StreamState {
  prev: SimSnapshot | null
  next: SimSnapshot | null
  nextAt: number      // performance.now() when `next` arrived
  intervalMs: number  // measured gap between the last two snapshots
}

const lerp = (a: number, b: number, t: number) => a + (b - a) * t

export function interpolateVehicles(s: StreamState, now: number): VehicleSnap[] {
  const next = s.next
  if (!next || !next.vehicles) return []
  const prev = s.prev
  if (!prev || !prev.vehicles) return next.vehicles
  const t = Math.min(1, Math.max(0, (now - s.nextAt) / s.intervalMs))
  const before = new Map(prev.vehicles.map((v) => [v.id, v]))
  return next.vehicles.map((v) => {
    const p = before.get(v.id)
    if (!p) return v
    const pos: Pt = [lerp(p.pos[0], v.pos[0], t), lerp(p.pos[1], v.pos[1], t)]
    const heading: Pt = [lerp(p.heading[0], v.heading[0], t),
                         lerp(p.heading[1], v.heading[1], t)]
    return { ...v, pos, heading }
  })
}

export function useSimStream() {
  const stream = useRef<StreamState>({
    prev: null, next: null, nextAt: 0, intervalMs: 67,
  })
  const [meta, setMeta] = useState<SimSnapshot>({ running: false })
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    let ws: WebSocket | null = null
    let closed = false
    let retry: number | undefined

    const connect = () => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${location.host}/ws/sim`)
      ws.onopen = () => setConnected(true)
      ws.onmessage = (ev) => {
        const snap = JSON.parse(ev.data) as SimSnapshot
        const s = stream.current
        const now = performance.now()
        if (s.next && s.nextAt > 0) {
          s.intervalMs = Math.min(500, Math.max(30, now - s.nextAt))
        }
        s.prev = s.next
        s.next = snap
        s.nextAt = now
        setMeta(snap)
      }
      ws.onclose = () => {
        setConnected(false)
        if (!closed) retry = window.setTimeout(connect, 1000)
      }
    }
    connect()
    return () => {
      closed = true
      if (retry !== undefined) window.clearTimeout(retry)
      ws?.close()
    }
  }, [])

  return { stream, meta, connected }
}
