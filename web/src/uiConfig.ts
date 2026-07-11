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
  version: 1
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

// Developer defaults: the official Flowscape chrome (fantasy-24 tokens).
export const DEFAULT_THEME: Record<string, string> = {
  'panel-bg': '#1f240a',
  'panel-text': '#efd8a1',
  'accent': '#efac28',
  'button-bg': '#392a1c',
  'button-border': '#927e6a',
  'button-hover': '#684c3c',
  'danger': '#9b1a0a',
  'warn': '#efb775',
  'outline': '#36170c',
}

export const DEFAULT_CONFIG: UIConfig = {
  version: 1,
  preset: 'Default',
  theme: { ...DEFAULT_THEME },
  fontFamily: 'System',
  fontSize: 13,
  panelOpacity: 0.9,
  radius: 8,
  outlineWidth: 1,
}

// Built-in presets: each overrides only what changes (theme inheritance).
export const BUILT_IN_PRESETS: Record<string, Partial<UIConfig> & {
  theme?: Partial<Record<string, string>>
}> = {
  'Default': {},
  'Dark Simulation': {
    theme: { 'panel-bg': '#36170c', 'button-bg': '#2a1d0d',
             'accent': '#ef692f', 'button-border': '#684c3c' },
    panelOpacity: 0.96,
  },
  'Blueprint': {
    theme: { 'panel-bg': '#183f39', 'accent': '#3c9f9c',
             'button-bg': '#276468', 'button-border': '#3c9f9c',
             'panel-text': '#efd8a1', 'outline': '#3c9f9c' },
    radius: 2,
    fontFamily: 'Monospace',
    outlineWidth: 2,
  },
  'Minimal': {
    panelOpacity: 0.75,
    radius: 12,
    theme: { 'button-border': '#392a1c' },
    outlineWidth: 0,
  },
  // Heritage Atlas (UI-Graphic-Design brief): a late-1800s engineering-atlas
  // aesthetic — deep teal cloth binding, soft-parchment ink, antique brass.
  // The palette lives here; App.css adds preset-scoped decorative craftsmanship
  // (double-line frames, engraved uppercase headers, instrument-style numerals)
  // gated on [data-ui-preset], so only the chrome changes — never behavior.
  'Heritage Atlas': {
    theme: {
      'panel-bg': '#e9dcbb',      // aged ivory paper
      'panel-text': '#40301e',    // warm dark-brown dip-pen ink
      'accent': '#a8532c',        // painted terracotta / sienna
      'button-bg': '#e0d0a6',     // deeper cream wash
      'button-border': '#5a4632', // brown ink outline
      'button-hover': '#d6c294',  // warmer wash
      'danger': '#9c3a24',        // rust red
      'warn': '#8a6a2c',          // ochre
      'outline': '#5a4632',       // brown ink outline
    },
    fontFamily: 'Atlas Antique',  // old-style serif body; IM Fell headers via CSS
    fontSize: 15,
    panelOpacity: 0.98,
    radius: 3,
    outlineWidth: 2,
  },
}

const STORAGE_KEY = 'flowscape-ui'
const PRESETS_KEY = 'flowscape-ui-presets'

function mergeConfig(base: UIConfig,
                     over: Partial<UIConfig> | null | undefined): UIConfig {
  if (!over) return { ...base, theme: { ...base.theme } }
  return {
    ...base,
    ...over,
    version: 1,
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
    if (saved.version !== 1) return { ...DEFAULT_CONFIG } // future: migrate
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
  // Expose the preset name so App.css can scope decorative craftsmanship
  // (e.g. Heritage Atlas frames/headers) without affecting other presets.
  document.documentElement.dataset.uiPreset = cfg.preset
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
