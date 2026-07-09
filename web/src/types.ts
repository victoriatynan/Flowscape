// Shapes served by the Flowscape backend. The frontend never computes any
// of this (Backend Authority / Geometry Ownership invariants) — it renders
// exactly what it is told.

export type Pt = [number, number]

export interface GeometryNode {
  id: number
  x: number
  y: number
  control: string | null
}

export interface GeometryRoad {
  id: number
  centerline: Pt[]
  control_point: Pt
  profile_data: { preset?: string; lane_count_forward?: number;
                  lane_count_reverse?: number }
  polygon: Pt[]
  markings: EdgeLine[]
  marking_width: number
  shoulder_polygon: Pt[] | null
  shoulder_color: string | null
  total_width: number
  lanes_forward: number
  lanes_reverse: number
}

export interface EdgeLine {
  points: Pt[]
  color: string
}

export interface JunctionSurface {
  node_id: number
  kind: 'junction' | 'continuation' | 'taper'
  polygon: Pt[]
  edge_lines: EdgeLine[]
  mouth_width: number
  outer_polygon: Pt[] | null
  outer_edge_lines: EdgeLine[]
  outer_color: string | null
}

export interface DeadEndCap {
  node_id: number
  pos: Pt
  radius: number
}

export interface GeometryLane {
  lane_id: [number, string, number]
  points: Pt[]
}

export interface GeometryBuilding {
  id: number
  x: number
  y: number
  building_type: string
  size_ft: number
  connection_node_ids: number[]
}

export interface MapGeometry {
  nodes: GeometryNode[]
  roads: GeometryRoad[]
  lanes: GeometryLane[]
  buildings: GeometryBuilding[]
  junctions: JunctionSurface[]
  caps: DeadEndCap[]
}

export interface VehicleSnap {
  id: number
  pos: Pt
  heading: Pt
  speed: number
  state: string
  dest_node: number | null
  dest_building: number | null
}

export interface SimSnapshot {
  running: boolean
  paused?: boolean
  tick?: number
  time?: number
  day?: number
  day_name?: string
  clock?: string
  vehicles?: VehicleSnap[]
  queue_depth?: number
  released?: number
  occupancy?: Record<string, number>
}

export interface FieldSpec {
  key: string
  label: string
  type: 'float' | 'int'
  minimum: number
  maximum: number
  step: number
  default: number
}

export interface ControlSchema {
  order: string[]
  labels: Record<string, string>
  implemented: string[]
  settings: Record<string, FieldSpec[]>
}

export interface RoadPresetsSchema {
  order: string[]
  presets: Record<string, {
    lane_width: number
    lanes_per_direction: number
    shoulder_type: string
    shoulder_width: number
    median_width: number
  }>
}

export interface BuildingTypesSchema {
  order: string[]
  types: Record<string, {
    category: string
    size: string
    size_ft: number
    capacity: number
    count_range: [number, number]
    open_hour: number
    close_hour: number
  }>
}
