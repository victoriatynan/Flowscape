import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, cleanup } from '@testing-library/react'
import type { AnalysisResult } from '../types'
import { makeFixture } from './fixtures'

// Mock the API so the component renders a known package. The presentation-only
// invariant is that whatever the platform serializes is what the DOM shows.
const fetchAnalysisV2 = vi.fn<() => Promise<AnalysisResult>>()
vi.mock('../api', () => ({ fetchAnalysisV2: () => fetchAnalysisV2() }))

// Imported after the mock is registered.
const { default: AnalysisSection } = await import('./AnalysisSection')

beforeEach(() => {
  cleanup()
  fetchAnalysisV2.mockReset()
})

describe('AnalysisSection (presentation only)', () => {
  it('renders the deficient road’s evidence numbers byte-for-byte', async () => {
    fetchAnalysisV2.mockResolvedValue(makeFixture())
    render(<AnalysisSection roadId={1} geoVersion={0} />)

    // Finding + its precomputed numbers, shown exactly as serialized. margin_ft
    // is unique to the finding; required/available also appear in the SSD
    // metrics, so those may render more than once (still consumed, never derived).
    await screen.findByText('Stopping sight distance deficiency')
    expect(screen.getByText('-70')).toBeInTheDocument()              // margin_ft (unique)
    expect(screen.getAllByText('180').length).toBeGreaterThan(0)     // available_ft
    expect(screen.getAllByText('250').length).toBeGreaterThan(0)     // required_ft
    // Recommendation text passed through verbatim.
    expect(screen.getByText('Increase the curve radius')).toBeInTheDocument()
  })

  it('recomputes nothing: mutating a result value moves the UI in lockstep', async () => {
    const mutated = makeFixture()
    mutated.findings.ssd_deficiency.evidence[0].margin_ft = -95
    fetchAnalysisV2.mockResolvedValue(mutated)
    render(<AnalysisSection roadId={1} geoVersion={0} />)

    await screen.findByText('Stopping sight distance deficiency')
    expect(screen.getByText('-95')).toBeInTheDocument()          // the new value
    expect(screen.queryByText('-70')).not.toBeInTheDocument()    // no stale/derived
  })

  it('selection mapping: a clear road shows metrics but no finding', async () => {
    fetchAnalysisV2.mockResolvedValue(makeFixture())
    render(<AnalysisSection roadId={2} geoVersion={0} />)

    await screen.findByText('Metrics')
    expect(screen.queryByText('Findings')).not.toBeInTheDocument()
    expect(screen.queryByText('Stopping sight distance deficiency')).not.toBeInTheDocument()
    expect(screen.queryByText('Recommendations')).not.toBeInTheDocument()
  })

  it('selection mapping: an unknown road shows the honest empty state', async () => {
    fetchAnalysisV2.mockResolvedValue(makeFixture())
    render(<AnalysisSection roadId={999} geoVersion={0} />)

    await waitFor(() =>
      expect(screen.getByText(/No engineering findings for this road/i))
        .toBeInTheDocument())
    expect(screen.queryByText('Findings')).not.toBeInTheDocument()
  })

  it('generic renderer: a new same-kind finding renders with no new code', async () => {
    // A plugin id the frontend has never heard of, of kind "finding", scoped to
    // road 1 — it must surface through the identical FindingCard.
    const fx = makeFixture()
    fx.findings.novel_intersection_finding = {
      id: 'novel_intersection_finding', category: 'geometry', kind: 'finding',
      name: 'A brand new finding', severity: 'low', flagged: true,
      evidence: [{ road_id: 1, some_new_number: 1234, severity: 'low' }],
      explanation: 'Surfaced without any component change.',
      supporting_metrics: [], supporting_observations: [], confidence: null,
    }
    fetchAnalysisV2.mockResolvedValue(fx)
    render(<AnalysisSection roadId={1} geoVersion={0} />)

    await screen.findByText('A brand new finding')
    expect(screen.getByText('Surfaced without any component change.'))
      .toBeInTheDocument()
    expect(screen.getByText('1234')).toBeInTheDocument()  // its opaque number
  })

  it('refetches when geoVersion bumps', async () => {
    fetchAnalysisV2.mockResolvedValue(makeFixture())
    const { rerender } = render(<AnalysisSection roadId={1} geoVersion={0} />)
    await screen.findByText('Stopping sight distance deficiency')
    expect(fetchAnalysisV2).toHaveBeenCalledTimes(1)

    rerender(<AnalysisSection roadId={1} geoVersion={1} />)
    await waitFor(() => expect(fetchAnalysisV2).toHaveBeenCalledTimes(2))
  })
})
