import { useCallback, useEffect, useRef, useState } from 'react'
import './App.css'
import * as api from './api'
import { Camera } from './camera'
import { buildingAt, nodeAt, roadAt } from './hitTest'
import Inspector, { type Selection } from './Inspector'
import AnalysisPanel from './AnalysisPanel'
import DesignPanel from './DesignPanel'
import { drawScene, type EditorOverlay } from './renderer'
import { Icon, HeritageDefs } from './HeritageIcons'
import { inkBorderUri } from './heritageArt'
import ControlBar from './ControlBar'
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
  // Heritage Atlas docked layout: adjustable, collapsible, pinnable regions
  // plus a resizable bottom simulation control bar.
  const [leftW, setLeftW] = useState(60)
  const [rightW, setRightW] = useState(272)
  const [leftCollapsed, setLeftCollapsed] = useState(false)
  const [rightCollapsed, setRightCollapsed] = useState(false)
  const [leftPinned, setLeftPinned] = useState(false)
  const [rightPinned, setRightPinned] = useState(false)
  const [barH, setBarH] = useState(56)
  const [barExpanded, setBarExpanded] = useState(false)
  const [uiConfig, setUiConfig] = useState<UIConfig>(() => {
    const cfg = loadConfig()
    applyConfig(cfg)          // saved default (or dev default) at startup
    return cfg
  })
  const heritage = uiConfig.preset === 'Heritage Atlas'
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
            categories(), overlayRef.current, heritage)
        }
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [stream, buildingTypes, heritage])

  // Boil the whole hand-inked chrome on one slow timer (~3x/sec): step the
  // shared SVG filter seeds (icons, compass, corners, gauges, sparkles) and the
  // panel/button border-image seed together, so the UI outlines re-draw in step
  // with the map. Re-rendering happens only when a seed changes (not per frame),
  // so it stays cheap. Runs only while Heritage is active and the tab is visible.
  useEffect(() => {
    if (!heritage) return
    const seeds = [5, 14, 26, 33, 41, 19]
    let i = 0
    const root = document.documentElement
    const id = window.setInterval(() => {
      if (document.hidden) return
      i = (i + 1) % seeds.length
      const s = seeds[i]
      document.querySelector('#ha-ink feTurbulence')?.setAttribute('seed', String(s))
      document.querySelector('#ha-water feTurbulence')?.setAttribute('seed', String(s + 3))
      root.style.setProperty('--ha-ink-border', inkBorderUri(s))
    }, 320)
    return () => {
      window.clearInterval(id)
      root.style.removeProperty('--ha-ink-border')
    }
  }, [heritage])

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

  // Drag-to-resize a docked side region. Window-level listeners so the drag
  // keeps tracking even when the pointer leaves the thin handle.
  const startResize = (side: 'left' | 'right') => (e: React.PointerEvent) => {
    e.preventDefault()
    const startX = e.clientX
    const from = side === 'left' ? leftW : rightW
    const move = (ev: PointerEvent) => {
      const d = ev.clientX - startX
      if (side === 'left') setLeftW(Math.max(48, Math.min(180, from + d)))
      else setRightW(Math.max(210, Math.min(460, from - d)))
    }
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  // Drag the control bar's top edge to grow/shrink its height.
  const startResizeBar = (e: React.PointerEvent) => {
    e.preventDefault()
    const startY = e.clientY
    const from = barH
    const move = (ev: PointerEvent) =>
      setBarH(Math.max(44, Math.min(280, from - (ev.clientY - startY))))
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  // Editing controls shared by the horizontal editbar (default presets) and the
  // vertical Heritage tool rail; orientation and labels are handled in CSS.
  const editControls = (
    <>
      {tools.map(([t, label]) => (
        <button key={t} className={tool === t ? 'active' : ''} title={label}
                onClick={() => { setTool(t); setRoadAnchorId(null) }}>
          {heritage && <Icon name={t} />}<span>{label}</span>
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
      <button onClick={() => runEdit(api.undo)} title="Undo">
        {heritage ? <Icon name="undo" /> : '↶'}<span>Undo</span></button>
      <button onClick={() => runEdit(api.redo)} title="Redo">
        {heritage ? <Icon name="redo" /> : '↷'}<span>Redo</span></button>
      {/* Default presets toggle a floating analysis panel; Heritage Atlas
          docks it permanently, so no toggle there. */}
      {!heritage && (
        <button className={showAnalysis ? 'active' : ''} title="Analysis"
                onClick={() => setShowAnalysis((v) => !v)}>
          <span>Analysis</span></button>
      )}
      {tool === 'road' && (
        <span className="hint">
          {roadAnchorId == null ? 'click the first node' : 'click the second node'}
        </span>
      )}
    </>
  )

  const inspectorPanel = !showDesign && selection && geometryRef.current && (
    <Inspector
      key={`${selection.kind}-${selection.id}-${geoVersion}`}
      selection={selection}
      heritage={heritage}
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
  )
  // Heritage docks analysis permanently (no show/hide toggle); default presets
  // show it only when toggled.
  const analysisEl = <AnalysisPanel geoVersion={geoVersion} heritage={heritage} />
  const designPanel = showDesign && (
    <DesignPanel config={uiConfig} onChange={setUiConfig} />
  )

  // Grid template drives the docked layout; collapsed regions shrink to zero
  // and a floating tab offers to re-open them. The bottom control bar occupies
  // its own row whose height the user can drag.
  const barEff = barExpanded ? Math.max(barH, 150) : barH
  const dockedStyle = heritage
    ? ({ '--ha-left': `${leftCollapsed ? 0 : leftW}px`,
         '--ha-right': `${rightCollapsed ? 0 : rightW}px`,
         '--ha-bar': `${barEff}px` } as React.CSSProperties)
    : undefined

  return (
    <div className={`app${heritage ? ' ha-docked' : ''}`} style={dockedStyle}>
      {heritage && <HeritageDefs />}
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
        {/* In Heritage Atlas playback + live stats live in the bottom bar. */}
        {!heritage && !running && <button onClick={() => runEdit(api.simStart)}>▶ Start</button>}
        {!heritage && running && !paused && <button onClick={() => runEdit(api.simPause)}>⏸ Pause</button>}
        {!heritage && running && paused && <button onClick={() => runEdit(api.simResume)}>▶ Resume</button>}
        {!heritage && running && <button onClick={() => runEdit(api.simStop)}>■ Stop</button>}
        {!heritage && (
          <span className="status">
            {running
              ? `${meta.day_name} (Day ${meta.day}) ${meta.clock} · cars: ` +
                `${meta.vehicles?.length ?? 0} · queue: ${meta.queue_depth ?? 0}`
              : 'sim stopped'}
          </span>
        )}
        <span className="status dim">{mapLabel}</span>
        <button className={showDesign ? 'active' : ''} title="UI design"
                onClick={() => setShowDesign((v) => !v)}>
          {heritage ? <Icon name="design" /> : '🎨'}</button>
        <span className={connected ? 'dot ok' : 'dot bad'} title="backend link" />
      </div>

      {heritage ? (
        <>
          {/* Left tool rail (docked, icon-first). */}
          {!leftCollapsed && (
            <aside className="tool-rail">
              {editControls}
              <div className="rail-foot">
                <button className="dock-pin" aria-pressed={leftPinned}
                        title={leftPinned ? 'Unpin tools' : 'Pin tools open'}
                        onClick={() => setLeftPinned((p) => !p)}>
                  {leftPinned ? '★' : '☆'}</button>
                {!leftPinned && (
                  <button className="dock-collapse" title="Collapse tools"
                          onClick={() => setLeftCollapsed(true)}>‹</button>
                )}
              </div>
              <div className="dock-resize left" onPointerDown={startResize('left')} />
            </aside>
          )}
          {leftCollapsed && (
            <button className="dock-tab left" title="Show tools"
                    onClick={() => setLeftCollapsed(false)}>›</button>
          )}

          {/* Right analysis & inspector dock (docked, scrollable). */}
          {!rightCollapsed && (
            <aside className="right-dock">
              <div className="dock-head">
                <button className="dock-pin" aria-pressed={rightPinned}
                        title={rightPinned ? 'Unpin panel' : 'Pin panel open'}
                        onClick={() => setRightPinned((p) => !p)}>
                  {rightPinned ? '★' : '☆'}</button>
                {!rightPinned && (
                  <button className="dock-collapse" title="Collapse panel"
                          onClick={() => setRightCollapsed(true)}>›</button>
                )}
              </div>
              {designPanel}
              {inspectorPanel}
              {analysisEl}
              <div className="dock-resize right" onPointerDown={startResize('right')} />
            </aside>
          )}
          {rightCollapsed && (
            <button className="dock-tab right" title="Show panel"
                    onClick={() => setRightCollapsed(false)}>‹</button>
          )}

          {/* Bottom simulation control bar (resizable height). */}
          <ControlBar
            meta={meta}
            expanded={barExpanded}
            onToggleExpand={() => setBarExpanded((v) => !v)}
            onResizeStart={startResizeBar}
            onStart={() => runEdit(api.simStart)}
            onPause={() => runEdit(api.simPause)}
            onResume={() => runEdit(api.simResume)}
            onStop={() => runEdit(api.simStop)}
          />
        </>
      ) : (
        <>
          <div className="editbar">{editControls}</div>
          {showAnalysis && analysisEl}
          {designPanel}
          {inspectorPanel}
        </>
      )}

      {error && <div className="error" onClick={() => setError(null)}>{error}</div>}
    </div>
  )
}
