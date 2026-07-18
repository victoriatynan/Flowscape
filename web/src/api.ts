import type { BuildingTypesSchema, ControlSchema, MapGeometry,
              RoadPresetsSchema } from './types'

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, init)
  if (!resp.ok) {
    const body = await resp.text()
    throw new Error(`${init?.method ?? 'GET'} ${path} -> ${resp.status}: ${body}`)
  }
  return resp.json() as Promise<T>
}

const post = (path: string, body?: unknown) =>
  req<Record<string, unknown>>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  })

export const fetchGeometry = () => req<MapGeometry>('/api/geometry')
export const fetchBuildingTypes = () =>
  req<BuildingTypesSchema>('/api/schema/building-types')

export const fetchControlSchema = () =>
  req<ControlSchema>('/api/schema/intersection-control')

export const loadTestCity = () => post('/api/map/test-city')

// Sim start options. Default (no args) = the fast decoupled preview. Pass
// { unified: true, time_scale } for the accurate single-clock "real simulator":
// one clock drives motion/demand/expiry, physics sub-steps to stay stable.
export interface SimStartOpts {
  unified?: boolean
  time_scale?: number
}
export const simStart = (opts: SimStartOpts = {}) => post('/api/sim/start', opts)
export const simPause = () => post('/api/sim/pause')
export const simResume = () => post('/api/sim/resume')
export const simStop = () => post('/api/sim/stop')

// Editing: every mutation is a backend command (authoritative + undoable).
export const createNode = (x: number, y: number) =>
  post('/api/edit/node', { x, y })
export const moveNode = (id: number, x: number, y: number) =>
  post(`/api/edit/node/${id}/move`, { x, y })
export const setNodeControl = (id: number, control: string,
                               settings: Record<string, number>) =>
  post(`/api/edit/node/${id}/control`, { control, settings })
export const createRoad = (startNodeId: number, endNodeId: number) =>
  post('/api/edit/road', { start_node_id: startNodeId, end_node_id: endNodeId })
export const createRoadToPoint = (startNodeId: number, x: number, y: number) =>
  post('/api/edit/road', { start_node_id: startNodeId, end_pos: [x, y] })
export const createBuilding = (x: number, y: number, mainNodeId: number,
                               buildingType: string) =>
  post('/api/edit/building', { x, y, main_node_id: mainNodeId,
                               building_type: buildingType })
export const setRoadCurve = (id: number, controlX: number, controlY: number) =>
  post(`/api/edit/road/${id}/curve`, { control_x: controlX, control_y: controlY })
export const setRoadProfile = (id: number, profile: {
  preset?: string
  lane_count_forward?: number
  lane_count_reverse?: number
}) => post(`/api/edit/road/${id}/profile`, profile)
export const deleteObject = (kind: 'node' | 'road' | 'building', id: number) =>
  req<Record<string, unknown>>(`/api/edit/${kind}/${id}`, { method: 'DELETE' })
export const undo = () => post('/api/edit/undo')
export const redo = () => post('/api/edit/redo')

export const fetchRoadPresets = () =>
  req<RoadPresetsSchema>('/api/schema/road-presets')
export const listMapFiles = () =>
  req<{ files: string[] }>('/api/map/files')
export const saveMap = (filename: string) =>
  post('/api/map/save', { filename })
export const loadMapFile = (filename: string) =>
  post('/api/map/load', { filename })
