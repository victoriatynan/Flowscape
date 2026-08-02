// Shared presentation helpers for the Analysis region. Labeling and stringifying
// only — NO arithmetic, rounding, banding, or unit conversion. Numbers are shown
// exactly as the platform serialized them (the presentation-only invariant).

// snake_case id → human label, e.g. "required_ssd" → "Required ssd". Purely
// cosmetic; changes no value.
export function humanize(id: string): string {
  const s = id.replace(/_/g, ' ')
  return s.charAt(0).toUpperCase() + s.slice(1)
}

// Display a serialized value verbatim. null/undefined → em dash; everything else
// is String()'d with no rounding so rendered text equals the result field.
export function displayValue(v: unknown): string {
  if (v === null || v === undefined) return '—'
  return String(v)
}

// Is this per-road entry a record of labeled fields (vs. a bare scalar)?
export function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}
