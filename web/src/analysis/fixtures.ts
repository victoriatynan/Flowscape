import type { AnalysisResult } from '../types'

// A deterministic AnalysisResult mirroring real backend output (analysis/**
// to_dict shapes), used by the presentation-layer tests. Road 1 is deficient
// (fired ssd_deficiency + over_capacity, with recommendations); road 2 is clear
// (carries metrics but trips no finding). Per-entity keys are strings on the
// wire (JSON object keys); evidence/recommendation road_id values are numbers —
// exactly the mixed-typing the loose projection must handle.
export function makeFixture(): AnalysisResult {
  return {
    observations: {
      road_count: {
        id: 'road_count', category: 'network', kind: 'observation',
        value: 2, units: 'count',
      },
      horizontal_curvature: {
        id: 'horizontal_curvature', category: 'geometry', kind: 'observation',
        value: null, units: 'ft',
        detail: {
          per_road: {
            '1': { radius_ft: 150, deflection_deg: 42 },
            '2': { radius_ft: 900, deflection_deg: 8 },
          },
        },
      },
    },
    metrics: {
      road_capacity: {
        id: 'road_capacity', category: 'traffic', kind: 'metric',
        value: 1800, units: 'veh/hr',
        detail: { per_road: { '1': 1800, '2': 1800 } },
      },
      vc_ratio: {
        id: 'vc_ratio', category: 'traffic', kind: 'metric',
        value: 1.2, units: 'ratio',
        detail: { per_road: { '1': { vc: 1.2, volume: 2160, capacity: 1800 } } },
      },
      required_ssd: {
        id: 'required_ssd', category: 'geometry', kind: 'metric',
        value: 250, units: 'ft',
        detail: {
          per_road: {
            '1': { required_ft: 250, design_speed_mph: 30 },
            '2': { required_ft: 200, design_speed_mph: 25 },
          },
        },
      },
      available_ssd: {
        id: 'available_ssd', category: 'geometry', kind: 'metric',
        value: 180, units: 'ft',
        detail: { per_road: { '1': { available_ft: 180, radius_ft: 150 } } },
      },
    },
    findings: {
      ssd_deficiency: {
        id: 'ssd_deficiency', category: 'geometry', kind: 'finding',
        name: 'Stopping sight distance deficiency', severity: 'high',
        flagged: true,
        evidence: [
          {
            road_id: 1, required_ft: 250, available_ft: 180, margin_ft: -70,
            design_speed_mph: 30, radius_ft: 150, severity: 'high',
          },
        ],
        explanation: '1 curved road(s) provide less than the required SSD.',
        supporting_metrics: ['required_ssd', 'available_ssd'],
        supporting_observations: ['horizontal_curvature'],
        confidence: null,
      },
      over_capacity: {
        id: 'over_capacity', category: 'traffic', kind: 'finding',
        name: 'Road over capacity', severity: 'moderate', flagged: true,
        evidence: [
          { road_id: 1, vc: 1.2, volume: 2160, capacity: 1800, severity: 'moderate' },
        ],
        explanation: '1 road is operating over its capacity.',
        supporting_metrics: ['vc_ratio'],
        supporting_observations: ['traffic_volume'],
        confidence: null,
      },
    },
    recommendations: {
      improve_sight_distance: {
        id: 'improve_sight_distance', category: 'geometry', kind: 'recommendation',
        items: [
          {
            road_id: 1, title: 'Increase the curve radius',
            expected_benefit: 'Flattens the curve, raising available sight distance.',
            tradeoffs: 'More right-of-way and earthwork.',
            supporting_evidence: { road_id: 1, margin_ft: -70 },
          },
        ],
        supporting_findings: ['ssd_deficiency'],
        confidence: null,
      },
    },
    metadata: { source_kind: 'static', is_running: false },
  }
}
