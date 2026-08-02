import type { RecommendationItem } from '../types'

// One proposed fix for the selected road: title, expected benefit, trade-offs —
// all authored by the recommendation plugin and shown verbatim. Display only.
export default function RecommendationCard({ item }:
                                          { item: RecommendationItem }) {
  return (
    <div className="analysis-rec">
      <div className="analysis-rec-title">{item.title}</div>
      <div className="row analysis-rec-benefit">
        <label>Benefit</label>
        <span>{item.expected_benefit}</span>
      </div>
      <div className="row analysis-rec-tradeoffs">
        <label>Trade-offs</label>
        <span>{item.tradeoffs}</span>
      </div>
    </div>
  )
}
