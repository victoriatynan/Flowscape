import type { Severity } from '../types'

// The ONLY place a severity meets a color. A fixed lookup over the four platform
// severities — NOT a judgement: WHICH severity a finding has was decided by the
// finding plugin and rides in the result. Mapping an already-decided severity to
// a swatch is presentation; deciding the severity would be engineering and never
// happens in the frontend.
export const SEVERITY_COLOR: Record<Severity, string> = {
  none: '#4a8f5b',      // green   — clear
  low: '#c9a227',       // amber   — minor
  moderate: '#d9822b',  // orange  — notable
  high: '#c0392b',      // red     — serious
}
