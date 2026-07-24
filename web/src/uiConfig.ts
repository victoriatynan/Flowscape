// UI configuration system (UI_PLAN.md, rescoped for the web client).
//
// The plan's framework collapses onto the platform: themes are CSS custom
// properties (inheritance = a preset overrides only what changes on top of
// the developer defaults), user preferences live in localStorage layered
// over the shipped defaults, and the config is versioned so future format
// changes migrate instead of breaking.
//
// Scope note: these tokens style the UI CHROME (toolbars, panels, inspector).
// The world/canvas colors are the map's visual identity — fantasy-24, owned
// by the backend palette — and are deliberately not user-themable here.

export interface UIConfig {
  version: 2
  preset: string
  theme: Record<string, string>   // CSS variable name (sans --ui-) -> value
  fontFamily: string              // key into FONT_FAMILIES
  fontSize: number                // px
  panelOpacity: number            // 0..1
  radius: number                  // px corner radius
  outlineWidth: number            // px; outlines on panels/buttons (0 = none)
}

// Named font stacks (web-safe on Windows/mac/Linux; no webfont downloads).
export const FONT_FAMILIES: Record<string, string> = {
  'System': 'system-ui, "Segoe UI", sans-serif',
  'Humanist': 'Verdana, Geneva, sans-serif',
  'Display': '"Trebuchet MS", "Segoe UI", sans-serif',
  'Serif': 'Georgia, "Times New Roman", serif',
  'Engraved': '"Bookman Old Style", "Palatino Linotype", Palatino, Georgia, serif',
  'Atlas Antique': '"EB Garamond", "Cormorant Garamond", "Constantia", "Palatino Linotype", Georgia, serif',
  'Monospace': '"Cascadia Mono", Consolas, "Courier New", monospace',
}

// Developer defaults = the Heritage Atlas manuscript skin, now the ONLY skin
// (UI-Graphic-Design brief): aged-ivory paper, warm-brown dip-pen ink, antique
// brass/terracotta. Every UI line is hand-drawn (heritageArt.ts) to match the
// map's inked linework. The Design panel still lets you retune these tokens; it
// no longer switches skins, because there is only one.
export const DEFAULT_THEME: Record<string, string> = {
  'panel-bg': '#e9dcbb',      // aged ivory paper
  'panel-text': '#40301e',    // warm dark-brown dip-pen ink
  'accent': '#a8532c',        // painted terracotta / sienna
  'button-bg': '#e0d0a6',     // deeper cream wash
  'button-border': '#5a4632', // brown ink outline
  'button-hover': '#d6c294',  // warmer wash
  'danger': '#9c3a24',        // rust red
  'warn': '#8a6a2c',          // ochre
  'outline': '#5a4632',       // brown ink outline
}

export const DEFAULT_CONFIG: UIConfig = {
  version: 2,
  preset: 'Heritage Atlas',
  theme: { ...DEFAULT_THEME },
  fontFamily: 'Atlas Antique',  // old-style serif body; IM Fell headers via CSS
  fontSize: 15,
  panelOpacity: 0.98,
  radius: 3,
  outlineWidth: 2,
}

// The single built-in skin. Kept as a (now trivial) map so presetConfig /
// resetToDefaults keep working; retuning tokens in the Design panel produces a
// 'Custom' variant of this same skin rather than a different look.
export const BUILT_IN_PRESETS: Record<string, Partial<UIConfig> & {
  theme?: Partial<Record<string, string>>
}> = {
  'Heritage Atlas': {},
}

const STORAGE_KEY = 'flowscape-ui'
const PRESETS_KEY = 'flowscape-ui-presets'

function mergeConfig(base: UIConfig,
                     over: Partial<UIConfig> | null | undefined): UIConfig {
  if (!over) return { ...base, theme: { ...base.theme } }
  return {
    ...base,
    ...over,
    version: 2,
    theme: { ...base.theme, ...(over.theme ?? {}) },
  }
}

export function presetConfig(name: string): UIConfig {
  const builtIn = BUILT_IN_PRESETS[name]
  if (builtIn) return { ...mergeConfig(DEFAULT_CONFIG, builtIn), preset: name }
  const user = userPresets()[name]
  return user ? { ...mergeConfig(DEFAULT_CONFIG, user), preset: name }
              : { ...DEFAULT_CONFIG }
}

/** Developer defaults <- saved user preferences (versioned). */
export function loadConfig(): UIConfig {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...DEFAULT_CONFIG }
    const saved = JSON.parse(raw) as Partial<UIConfig>
    // v2 dropped multi-preset support for the single Heritage skin; discard any
    // older saved chrome (it predates the hand-drawn UI) instead of restoring it.
    if (saved.version !== 2) return { ...DEFAULT_CONFIG }
    return mergeConfig(DEFAULT_CONFIG, saved)
  } catch {
    return { ...DEFAULT_CONFIG }
  }
}

export function saveAsDefault(cfg: UIConfig) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(cfg))
}

export function resetToDefaults(): UIConfig {
  localStorage.removeItem(STORAGE_KEY)
  return { ...DEFAULT_CONFIG, theme: { ...DEFAULT_THEME } }
}

export function userPresets(): Record<string, Partial<UIConfig>> {
  try {
    return JSON.parse(localStorage.getItem(PRESETS_KEY) ?? '{}')
  } catch {
    return {}
  }
}

export function saveUserPreset(name: string, cfg: UIConfig) {
  const all = userPresets()
  all[name] = { ...cfg, preset: name }
  localStorage.setItem(PRESETS_KEY, JSON.stringify(all))
}

export function presetNames(): string[] {
  return [...Object.keys(BUILT_IN_PRESETS), ...Object.keys(userPresets())]
}

/** Push the config into the live UI (CSS custom properties on :root). */
export function applyConfig(cfg: UIConfig) {
  const root = document.documentElement.style
  // Heritage Atlas is the only skin, so its decorative CSS (frames, engraved
  // headers, the hand-drawn ink borders) is always active — even when the user
  // retunes tokens into a 'Custom' variant. Kept as a fixed data attribute so
  // the existing [data-ui-preset='Heritage Atlas'] rules keep matching.
  document.documentElement.dataset.uiPreset = 'Heritage Atlas'
  for (const [key, value] of Object.entries(cfg.theme)) {
    root.setProperty(`--ui-${key}`, value)
  }
  root.setProperty('--ui-font-size', `${cfg.fontSize}px`)
  root.setProperty('--ui-font-family',
                   FONT_FAMILIES[cfg.fontFamily] ?? FONT_FAMILIES['System'])
  root.setProperty('--ui-panel-opacity', String(cfg.panelOpacity))
  root.setProperty('--ui-radius', `${cfg.radius}px`)
  root.setProperty('--ui-outline-width', `${cfg.outlineWidth}px`)
}
