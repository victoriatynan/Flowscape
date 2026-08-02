import type { EvidenceRow, FindingResult, Severity } from '../types'
import { displayValue, humanize } from './display'
import { SEVERITY_COLOR } from './severity'

// Fields already shown as the card's structure — not repeated in the number grid.
const OMIT = new Set(['road_id', 'severity'])

// A fired finding for the selected road: severity badge, name, explanation, and
// the evidence row's precomputed numbers as labeled fields. Display only.
export default function FindingCard({ finding, row }:
                                    { finding: FindingResult; row: EvidenceRow }) {
  const severity: Severity = row.severity ?? finding.severity
  return (
    <div className="analysis-finding">
      <div className="analysis-finding-head">
        <span className="analysis-severity"
              style={{ background: SEVERITY_COLOR[severity] }}>
          {severity}
        </span>
        <span className="analysis-finding-name">{finding.name}</span>
      </div>
      <div className="row analysis-explanation">{finding.explanation}</div>
      <div className="analysis-fields">
        {Object.entries(row)
          .filter(([k]) => !OMIT.has(k))
          .map(([k, v]) => (
            <div className="row analysis-field" key={k}>
              <label>{humanize(k)}</label>
              <span>{displayValue(v)}</span>
            </div>
          ))}
      </div>
    </div>
  )
}
