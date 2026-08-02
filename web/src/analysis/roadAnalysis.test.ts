import { describe, it, expect } from 'vitest'
import { roadAnalysis } from './roadAnalysis'
import { makeFixture } from './fixtures'
import type { AnalysisResult } from '../types'

describe('roadAnalysis projection', () => {
  it('selects the deficient road’s full four-stage slice', () => {
    const a = roadAnalysis(makeFixture(), 1)
    expect(a.empty).toBe(false)
    // horizontal_curvature is the only per-road observation.
    expect(a.observations.map((o) => o.result.id)).toEqual(['horizontal_curvature'])
    // all four per-road metrics apply to road 1.
    expect(a.metrics.map((m) => m.result.id).sort()).toEqual(
      ['available_ssd', 'required_ssd', 'road_capacity', 'vc_ratio'])
    // both findings fired for road 1.
    expect(a.findings.map((f) => f.finding.id).sort()).toEqual(
      ['over_capacity', 'ssd_deficiency'])
    // the recommendation item addressing road 1 is kept.
    expect(a.recommendations[0].items).toHaveLength(1)
  })

  it('carries this road’s precomputed values unchanged (no math)', () => {
    const a = roadAnalysis(makeFixture(), 1)
    const vc = a.metrics.find((m) => m.result.id === 'vc_ratio')!
    expect(vc.perRoad).toEqual({ vc: 1.2, volume: 2160, capacity: 1800 })
    const cap = a.metrics.find((m) => m.result.id === 'road_capacity')!
    expect(cap.perRoad).toBe(1800) // scalar per-road value preserved as-is
    const ssd = a.findings.find((f) => f.finding.id === 'ssd_deficiency')!
    expect(ssd.row.margin_ft).toBe(-70)
  })

  it('a clear road keeps its metrics but trips no finding', () => {
    const a = roadAnalysis(makeFixture(), 2)
    expect(a.empty).toBe(false)
    expect(a.observations.map((o) => o.result.id)).toEqual(['horizontal_curvature'])
    expect(a.metrics.map((m) => m.result.id).sort()).toEqual(
      ['required_ssd', 'road_capacity'])
    expect(a.findings).toHaveLength(0)
    expect(a.recommendations).toHaveLength(0)
  })

  it('an unknown road id projects to the empty state', () => {
    const a = roadAnalysis(makeFixture(), 999)
    expect(a.empty).toBe(true)
    expect(a.metrics).toHaveLength(0)
    expect(a.findings).toHaveLength(0)
  })

  it('matches ids loosely: string per_road keys vs number evidence ids', () => {
    // Per-entity keys are strings; a numeric roadId must still match them, and a
    // numeric evidence road_id must match too. Both sides go through String().
    const fx = makeFixture()
    const a = roadAnalysis(fx, 1)
    expect(a.metrics.length).toBeGreaterThan(0) // matched string key "1"
    expect(a.findings.length).toBeGreaterThan(0) // matched numeric road_id 1
  })

  it('tolerates missing stages without throwing', () => {
    const empty = { metadata: {} } as unknown as AnalysisResult
    expect(() => roadAnalysis(empty, 1)).not.toThrow()
    expect(roadAnalysis(empty, 1).empty).toBe(true)
  })
})
