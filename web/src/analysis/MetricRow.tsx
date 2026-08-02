import type { StageValueResult } from '../types'
import { displayValue, humanize, isRecord } from './display'

// One metric's (or observation's — same serialized shape) value for the selected
// road. `perRoad` is this road's precomputed entry: a bare scalar (shown as
// `value units`) or a record of already-computed fields (shown as labeled rows).
// Display only — no math, no rounding.
export default function MetricRow({ result, perRoad }:
                                  { result: StageValueResult; perRoad: unknown }) {
  return (
    <div className="analysis-metric">
      <div className="analysis-metric-name">{humanize(result.id)}</div>
      {isRecord(perRoad) ? (
        <div className="analysis-fields">
          {Object.entries(perRoad).map(([k, v]) => (
            <div className="row analysis-field" key={k}>
              <label>{humanize(k)}</label>
              <span>{displayValue(v)}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="row analysis-field">
          <span>{displayValue(perRoad)}</span>
          {result.units && <span className="analysis-units">{result.units}</span>}
        </div>
      )}
    </div>
  )
}
