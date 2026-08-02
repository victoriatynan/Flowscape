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
  start_node_id: number
  end_node_id: number
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
  // Clock mode (unified "real simulator" vs decoupled preview) + compute cost.
  unified?: boolean
  time_scale?: number
  substeps?: number
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

// ---------------------------------------------------------------------------
// Analysis Platform (M4) — serialized AnalysisResult shapes.
//
// These mirror the backend `to_dict()` field-for-field (analysis/**/base.py and
// analysis/models/result.py). The frontend is a PRESENTATION LAYER ONLY: it
// renders these already-computed values and never derives, bands, converts, or
// judges any of them. Adding a field here means the platform serialized it.
// ---------------------------------------------------------------------------

export type Severity = 'none' | 'low' | 'moderate' | 'high'
export type Stage = 'observation' | 'metric' | 'finding' | 'recommendation'

// Per-entity detail is keyed by road id. NOTE: JSON object keys are strings, so
// these come back stringified — look up with String(roadId). Values are opaque
// to the presentation layer: a scalar, or a record of already-computed fields.
export type PerRoad = Record<string, number | string | Record<string, unknown> | null>

// Observations and metrics share the same serialized shape (base.py).
export interface StageValueResult {
  id: string
  category: string
  kind: 'observation' | 'metric'
  value: number | string | null           // network roll-up; null = honest N/A
  units: string | null
  detail?: { per_road?: PerRoad } & Record<string, unknown>
}
export type ObservationResult = StageValueResult & { kind: 'observation' }
export type MetricResult = StageValueResult & { kind: 'metric' }

// One flagged instance. Always carries road_id; the rest are plugin-specific,
// already display-ready (e.g. vc, volume, capacity | required_ft, available_ft,
// margin_ft, design_speed_mph, radius_ft). The UI never interprets them.
export interface EvidenceRow {
  road_id: number
  severity?: Severity
  [field: string]: unknown
}

export interface FindingResult {
  id: string
  category: string
  kind: 'finding'
  name: string
  severity: Severity                       // network roll-up severity
  flagged?: boolean                        // == evidence.length > 0
  evidence: EvidenceRow[]
  explanation: string
  supporting_metrics: string[]
  supporting_observations: string[]
  confidence: number | null
}

export interface RecommendationItem {
  title: string
  expected_benefit: string
  tradeoffs: string
  supporting_evidence?: unknown            // the road / finding it addresses
  [field: string]: unknown
}

export interface RecommendationResult {
  id: string
  category: string
  kind: 'recommendation'
  items: RecommendationItem[]
  supporting_findings: string[]
  confidence: number | null
}

export interface AnalysisResult {
  observations: Record<string, ObservationResult>
  metrics: Record<string, MetricResult>
  findings: Record<string, FindingResult>
  recommendations: Record<string, RecommendationResult>
  metadata: {
    source_kind?: string
    is_running?: boolean
    snapshot_hash?: string
    generated_at?: string
    [k: string]: unknown
  }
}
