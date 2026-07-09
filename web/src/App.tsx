import { useCallback, useEffect, useRef, useState } from 'react'
import './App.css'
import * as api from './api'
import { Camera } from './camera'
import { buildingAt, nodeAt, roadAt } from './hitTest'
import Inspector, { type Selection } from './Inspector'
import AnalysisPanel from './AnalysisPanel'
import DesignPanel from './DesignPanel'
import { drawScene, type EditorOverlay } from './renderer'
import { type UIConfig, applyConfig, loadConfig } from './uiConfig'
import { interpolateVehicles, useSimStream } from './useSimStream'
import type { BuildingTypesSchema, ControlSchema, MapGeometry,
              RoadPresetsSchema } from './types'

type Tool = 'select' | 'node' | 'road' | 'building'

const NODE_HIT_FT = 14
const ROAD_HIT_FT = 10
const BUILDING_MAIN_NODE_FT = 250

export default function App() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const cameraRef = useRef(new Camera())
  const geometryRef = useRef<MapGeometry | null>(null)
  const overlayRef = useRef<EditorOverlay>({})
  const dragRef = useRef<
    | { mode: 'pan'; x: number; y: number; moved: boolean }
    | { mode: 'node'; id: number; moved: boolean }
    | { mode: 'curve'; roadId: number; moved: boolean }
    | null
  >(null)

  const [tool, setTool] = useState<Tool>('select')
  const [selection, setSelection] = useState<Selection | null>(null)
  const [roadAnchorId, setRoadAnchorId] = useState<number | null>(null)
  const [buildingType, setBuildingType] = useState('Small House')
  const [buildingTypes, setBuildingTypes] = useState<BuildingTypesSchema | null>(null)
  const [controlSchema, setControlSchema] = useState<ControlSchema | null>(null)
  const [roadPresets, setRoadPresets] = useState<RoadPresetsSchema | null>(null)
  const [geoVersion, setGeoVersion] = useState(0)
  const [mapFiles, setMapFiles] = useState<string[]>([])
  const [showAnalysis, setShowAnalysis] = useState(false)
  const [showDesign, setShowDesign] = useState(false)
  const [uiConfig, setUiConfig] = useState<UIConfig>(() => {
    const cfg = loadConfig()
    applyConfig(cfg)          // saved default (or dev default) at startup
    return cfg
  })
  const [mapLabel, setMapLabel] = useState('empty map')
  const [error, setError] = useState<string | null>(null)
  const { stream, meta, connected } = useSimStream()

  const refreshGeometry = useCallback(async (fit: boolean) => {
    const geo = await api.fetchGeometry()
    geometryRef.current = geo
    if (fit && canvasRef.current) {
      const c = canvasRef.current
      cameraRef.current.fit(geo, c.clientWidth, c.clientHeight)
    }
    setMapLabel(`${geo.roads.length} roads · ${geo.buildings.length} buildings`)
    setGeoVersion((v) => v + 1)
  }, [])

  // Selection / tool state → overlay the render loop reads.
  useEffect(() => {
    const o = overlayRef.current
    o.selectedNodeId = selection?.kind === 'node' ? selection.id : null
    o.selectedRoadId = selection?.kind === 'road' ? selection.id : null
    o.selectedBuildingId = selection?.kind === 'building' ? selection.id : null
    o.roadAnchorId = roadAnchorId
    if (tool !== 'building') o.buildingGhost = null
  }, [selection, roadAnchorId, tool])

  // Drop selection if its object disappeared (delete/undo/map load).
  useEffect(() => {
    const geo = geometryRef.current
    if (!geo || !selection) return
    const exists =
      (selection.kind === 'node' && geo.nodes.some((n) => n.id === selection.id)) ||
      (selection.kind === 'road' && geo.roads.some((r) => r.id === selection.id)) ||
      (selection.kind === 'building' && geo.buildings.some((b) => b.id === selection.id))
    if (!exists) setSelection(null)
  }, [geoVersion, selection])

  const refreshMapFiles = useCallback(() => {
    api.listMapFiles().then((r) => setMapFiles(r.files)).catch(() => {})
  }, [])

  useEffect(() => {
    api.fetchBuildingTypes().then(setBuildingTypes).catch((e) => setError(String(e)))
    api.fetchControlSchema().then(setControlSchema).catch((e) => setError(String(e)))
    api.fetchRoadPresets().then(setRoadPresets).catch((e) => setError(String(e)))
    refreshMapFiles()
    refreshGeometry(true).catch((e) => setError(String(e)))
  }, [refreshGeometry, refreshMapFiles])

  const saveMapAs = () => {
    const name = window.prompt('Save map as (filename):', 'my_city')
    if (!name) return
    setError(null)
    api.saveMap(name).then(refreshMapFiles).catch((e) => setError(String(e)))
  }

  // Render loop.
  useEffect(() => {
    let raf = 0
    const categories = () => {
      const types = buildingTypes?.types ?? {}
      return (bt: string) => types[bt]?.category
    }
    const tick = () => {
      const canvas = canvasRef.current
      if (canvas) {
        const dpr = window.devicePixelRatio || 1
        const w = canvas.clientWidth
        const h = canvas.clientHeight
        if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
          canvas.width = w * dpr
          canvas.height = h * dpr
        }
        const ctx = canvas.getContext('2d')
        if (ctx) {
          ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
          drawScene(ctx, w, h, cameraRef.current, geometryRef.current,
            interpolateVehicles(stream.current, performance.now()),
            categories(), overlayRef.current)
        }
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [stream, buildingTypes])

  const runEdit = useCallback((fn: () => Promise<unknown>, fit = false) => {
    setError(null)
    fn().then(() => refreshGeometry(fit)).catch((e) => setError(String(e)))
  }, [refreshGeometry])

  const canvasWorld = (e: { clientX: number; clientY: number }): [number, number] => {
    const canvas = canvasRef.current!
    const rect = canvas.getBoundingClientRect()
    return cameraRef.current.toWorld(e.clientX - rect.left, e.clientY - rect.top,
                                     rect.width, rect.height)
  }

  const onPointerDown = (e: React.PointerEvent) => {
    try { (e.target as Element).setPointerCapture(e.pointerId) } catch { /* synthetic events have no active pointer */ }
    const geo = geometryRef.current
    const [wx, wy] = canvasWorld(e)

    if (tool === 'select' && geo) {
      const hitScale = 1 / Math.max(0.2, cameraRef.current.scale)
      // Curve handle of the already-selected road takes priority.
      if (selection?.kind === 'road') {
        const road = geo.roads.find((r) => r.id === selection.id)
        if (road) {
          const d = Math.hypot(road.control_point[0] - wx,
                               road.control_point[1] - wy)
          if (d <= NODE_HIT_FT * Math.max(1, hitScale)) {
            dragRef.current = { mode: 'curve', roadId: road.id, moved: false }
            overlayRef.current.dragCurve =
              { roadId: road.id, x: road.control_point[0], y: road.control_point[1] }
            return
          }
        }
      }
      const node = nodeAt(geo, wx, wy, NODE_HIT_FT * Math.max(1, hitScale))
      if (node) {
        dragRef.current = { mode: 'node', id: node.id, moved: false }
        overlayRef.current.dragNode = { id: node.id, x: node.x, y: node.y }
        setSelection({ kind: 'node', id: node.id })
        return
      }
    }
    dragRef.current = { mode: 'pan', x: e.clientX, y: e.clientY, moved: false }
  }

  const onPointerMove = (e: React.PointerEvent) => {
    const [wx, wy] = canvasWorld(e)
    overlayRef.current.cursorWorld = [wx, wy]
    if (tool === 'building') {
      const sizeFt = buildingTypes?.types[buildingType]?.size_ft ?? 30
      overlayRef.current.buildingGhost = { x: wx, y: wy, sizeFt }
    }

    const drag = dragRef.current
    if (!drag) return
    if (drag.mode === 'pan') {
      cameraRef.current.panPx(e.clientX - drag.x, e.clientY - drag.y)
      if (Math.abs(e.clientX - drag.x) + Math.abs(e.clientY - drag.y) > 2) drag.moved = true
      drag.x = e.clientX
      drag.y = e.clientY
    } else if (drag.mode === 'node') {
      // Non-authoritative move preview; the backend applies it on release.
      drag.moved = true
      overlayRef.current.dragNode = { id: drag.id, x: wx, y: wy }
    } else {
      drag.moved = true
      overlayRef.current.dragCurve = { roadId: drag.roadId, x: wx, y: wy }
    }
  }

  const onPointerUp = (e: React.PointerEvent) => {
    const drag = dragRef.current
    dragRef.current = null
    const geo = geometryRef.current
    const [wx, wy] = canvasWorld(e)

    if (drag?.mode === 'node') {
      overlayRef.current.dragNode = null
      if (drag.moved) runEdit(() => api.moveNode(drag.id, wx, wy))
      return
    }
    if (drag?.mode === 'curve') {
      overlayRef.current.dragCurve = null
      if (drag.moved) runEdit(() => api.setRoadCurve(drag.roadId, wx, wy))
      return
    }
    if (drag?.mode === 'pan' && drag.moved) return   // it was a camera drag
    if (!geo) return

    if (tool === 'select') {
      const b = buildingAt(geo, wx, wy)
      if (b) { setSelection({ kind: 'building', id: b.id }); return }
      const r = roadAt(geo, wx, wy, ROAD_HIT_FT / Math.min(1, cameraRef.current.scale))
      if (r) { setSelection({ kind: 'road', id: r.id }); return }
      setSelection(null)
    } else if (tool === 'node') {
      runEdit(() => api.createNode(wx, wy))
    } else if (tool === 'road') {
      const node = nodeAt(geo, wx, wy, NODE_HIT_FT / Math.min(1, cameraRef.current.scale))
      if (roadAnchorId == null) {
        if (node) setRoadAnchorId(node.id)
        return
      }
      if (node && node.id === roadAnchorId) return
      // Continuous drawing: connect to the hit node, or let the backend
      // create the endpoint (node + road = one undo step); either way the
      // anchor advances to the endpoint so drawing continues. Esc stops.
      const from = roadAnchorId
      setError(null)
      const call = node
        ? api.createRoad(from, node.id)
        : api.createRoadToPoint(from, wx, wy)
      call
        .then(async (resp) => {
          await refreshGeometry(false)
          const created = resp['created_node'] as { id: number } | null
          setRoadAnchorId(node ? node.id : created?.id ?? null)
        })
        .catch((e) => { setRoadAnchorId(null); setError(String(e)) })
    } else if (tool === 'building') {
      const main = nodeAt(geo, wx, wy, BUILDING_MAIN_NODE_FT)
      if (!main) { setError('No road node within reach for the driveway'); return }
      runEdit(() => api.createBuilding(wx, wy, main.id, buildingType))
    }
  }

  // Keyboard: Esc cancels, Delete removes the selection, Ctrl+Z / Ctrl+Y.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === 'INPUT'
          || (e.target as HTMLElement)?.tagName === 'SELECT') return
      if (e.key === 'Escape') {
        setRoadAnchorId(null)
        setSelection(null)
      } else if ((e.key === 'Delete' || e.key === 'Backspace') && selection) {
        runEdit(() => api.deleteObject(selection.kind, selection.id))
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && !e.shiftKey) {
        runEdit(api.undo)
      } else if ((e.ctrlKey || e.metaKey)
                 && (e.key.toLowerCase() === 'y'
                     || (e.shiftKey && e.key.toLowerCase() === 'z'))) {
        runEdit(api.redo)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selection, runEdit])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const rect = canvas.getBoundingClientRect()
      cameraRef.current.zoomAt(e.clientX - rect.left, e.clientY - rect.top,
        rect.width, rect.height, e.deltaY < 0 ? 1.15 : 1 / 1.15)
    }
    canvas.addEventListener('wheel', onWheel, { passive: false })
    return () => canvas.removeEventListener('wheel', onWheel)
  }, [])

  const running = meta.running
  const paused = meta.paused ?? false
  const tools: [Tool, string][] = [
    ['select', 'Select'], ['node', 'Node'], ['road', 'Road'], ['building', 'Building'],
  ]

  return (
    <div className="app">
      <canvas
        ref={canvasRef}
        className="world"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
      />
      <div className="toolbar">
        <span className="brand">Flowscape</span>
        <button onClick={() => runEdit(api.loadTestCity, true)}>Load Test City</button>
        <button onClick={saveMapAs}>Save…</button>
        <select value="" onChange={(e) => {
          const f = e.target.value
          if (f) runEdit(() => api.loadMapFile(f), true)
        }}>
          <option value="">Load…</option>
          {mapFiles.map((f) => <option key={f} value={f}>{f}</option>)}
        </select>
        {!running && <button onClick={() => runEdit(api.simStart)}>▶ Start</button>}
        {running && !paused && <button onClick={() => runEdit(api.simPause)}>⏸ Pause</button>}
        {running && paused && <button onClick={() => runEdit(api.simResume)}>▶ Resume</button>}
        {running && <button onClick={() => runEdit(api.simStop)}>■ Stop</button>}
        <span className="status">
          {running
            ? `${meta.day_name} (Day ${meta.day}) ${meta.clock} · cars: ` +
              `${meta.vehicles?.length ?? 0} · queue: ${meta.queue_depth ?? 0}`
            : 'sim stopped'}
        </span>
        <span className="status dim">{mapLabel}</span>
        <button className={showDesign ? 'active' : ''} title="UI design"
                onClick={() => setShowDesign((v) => !v)}>🎨</button>
        <span className={connected ? 'dot ok' : 'dot bad'} title="backend link" />
      </div>
      <div className="editbar">
        {tools.map(([t, label]) => (
          <button key={t} className={tool === t ? 'active' : ''}
                  onClick={() => { setTool(t); setRoadAnchorId(null) }}>
            {label}
          </button>
        ))}
        {tool === 'building' && (
          <select value={buildingType}
                  onChange={(e) => setBuildingType(e.target.value)}>
            {(buildingTypes?.order ?? []).map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
        )}
        <button onClick={() => runEdit(api.undo)}>↶ Undo</button>
        <button onClick={() => runEdit(api.redo)}>↷ Redo</button>
        <button className={showAnalysis ? 'active' : ''}
                onClick={() => setShowAnalysis((v) => !v)}>Analysis</button>
        {tool === 'road' && (
          <span className="hint">
            {roadAnchorId == null ? 'click the first node' : 'click the second node'}
          </span>
        )}
      </div>
      {showAnalysis && <AnalysisPanel geoVersion={geoVersion} />}
      {showDesign && <DesignPanel config={uiConfig} onChange={setUiConfig} />}
      {!showDesign && selection && geometryRef.current && (
        <Inspector
          key={`${selection.kind}-${selection.id}-${geoVersion}`}
          selection={selection}
          geometry={geometryRef.current}
          controlSchema={controlSchema}
          roadPresets={roadPresets}
          onMutated={() => refreshGeometry(false).catch((e) => setError(String(e)))}
          onDeleted={() => {
            setSelection(null)
            refreshGeometry(false).catch((e) => setError(String(e)))
          }}
          onError={setError}
        />
      )}
      {error && <div className="error" onClick={() => setError(null)}>{error}</div>}
    </div>
  )
}
