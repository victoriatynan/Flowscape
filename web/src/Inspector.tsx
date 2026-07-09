import { useState } from 'react'
import * as api from './api'
import type { ControlSchema, MapGeometry, RoadPresetsSchema } from './types'

// Schema-driven property panel for the current selection — the browser
// counterpart of the pygame inspector. Control kinds and their settings
// come entirely from /api/schema/intersection-control (FieldSpec), so new
// controller types need no frontend changes.

export interface Selection {
  kind: 'node' | 'road' | 'building'
  id: number
}

interface Props {
  selection: Selection
  geometry: MapGeometry
  controlSchema: ControlSchema | null
  roadPresets: RoadPresetsSchema | null
  onMutated: () => void        // refetch geometry (keeps selection)
  onDeleted: () => void        // refetch + clear selection
  onError: (message: string) => void
}

export default function Inspector({ selection, geometry, controlSchema,
                                    roadPresets, onMutated, onDeleted,
                                    onError }: Props) {
  const [pendingControl, setPendingControl] = useState<string | null>(null)
  const [settings, setSettings] = useState<Record<string, number>>({})
  const [pendingProfile, setPendingProfile] = useState<{
    preset?: string
    lane_count_forward?: number
    lane_count_reverse?: number
  }>({})

  const run = (fn: () => Promise<unknown>, after: () => void) => {
    fn().then(after).catch((e) => onError(String(e)))
  }

  const del = () => run(
    () => api.deleteObject(selection.kind, selection.id), onDeleted)

  let body = null
  if (selection.kind === 'node') {
    const node = geometry.nodes.find((n) => n.id === selection.id)
    if (!node) return null
    const control = pendingControl ?? node.control ?? 'reservation'
    const specs = controlSchema?.settings[control] ?? []
    const apply = () => run(
      () => api.setNodeControl(node.id, control, settings),
      () => { setPendingControl(null); setSettings({}); onMutated() })
    body = (
      <>
        <div className="row"><b>Node {node.id}</b></div>
        <div className="row">
          <label>Control</label>
          <select value={control}
                  onChange={(e) => { setPendingControl(e.target.value); setSettings({}) }}>
            {(controlSchema?.order ?? []).map((kind) => (
              <option key={kind} value={kind}
                      disabled={!controlSchema?.implemented.includes(kind)}>
                {controlSchema?.labels[kind] ?? kind}
              </option>
            ))}
          </select>
        </div>
        {specs.map((spec) => (
          <div className="row" key={spec.key}>
            <label>{spec.label}</label>
            <input type="number" min={spec.minimum} max={spec.maximum}
                   step={spec.step}
                   value={settings[spec.key] ?? spec.default}
                   onChange={(e) => setSettings(
                     { ...settings, [spec.key]: Number(e.target.value) })} />
          </div>
        ))}
        <div className="row">
          <button onClick={apply}>Apply control</button>
        </div>
      </>
    )
  } else if (selection.kind === 'road') {
    const road = geometry.roads.find((r) => r.id === selection.id)
    if (!road) return null
    const preset = pendingProfile.preset
      ?? road.profile_data.preset ?? 'urban'
    const fwd = pendingProfile.lane_count_forward ?? road.lanes_forward
    const rev = pendingProfile.lane_count_reverse ?? road.lanes_reverse
    const applyProfile = () => run(
      () => api.setRoadProfile(road.id, {
        preset, lane_count_forward: fwd, lane_count_reverse: rev }),
      () => { setPendingProfile({}); onMutated() })
    body = (
      <>
        <div className="row"><b>Road {road.id}</b></div>
        <div className="row">width {road.total_width.toFixed(1)} ft</div>
        <div className="row">
          <label>Preset</label>
          <select value={preset}
                  onChange={(e) => setPendingProfile(
                    { ...pendingProfile, preset: e.target.value })}>
            {(roadPresets?.order ?? [preset]).map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
        </div>
        <div className="row">
          <label>Lanes fwd</label>
          <input type="number" min={1} max={6} step={1} value={fwd}
                 onChange={(e) => setPendingProfile(
                   { ...pendingProfile, lane_count_forward: Number(e.target.value) })} />
        </div>
        <div className="row">
          <label>Lanes rev</label>
          <input type="number" min={1} max={6} step={1} value={rev}
                 onChange={(e) => setPendingProfile(
                   { ...pendingProfile, lane_count_reverse: Number(e.target.value) })} />
        </div>
        <div className="row">
          <button onClick={applyProfile}>Apply profile</button>
        </div>
      </>
    )
  } else {
    const b = geometry.buildings.find((x) => x.id === selection.id)
    if (!b) return null
    body = (
      <>
        <div className="row"><b>Building {b.id}</b></div>
        <div className="row">{b.building_type}</div>
        <div className="row">{b.size_ft.toFixed(0)} ft footprint</div>
        <div className="row">
          driveway node{b.connection_node_ids.length === 1 ? '' : 's'}:{' '}
          {b.connection_node_ids.join(', ')}
        </div>
      </>
    )
  }

  return (
    <div className="inspector">
      {body}
      <div className="row">
        <button className="danger" onClick={del}>Delete {selection.kind}</button>
      </div>
    </div>
  )
}
