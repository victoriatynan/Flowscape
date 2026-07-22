import { useState } from 'react'
import {
  type UIConfig, type InkConfig, FONT_FAMILIES, INK_CHARACTERS, DEFAULT_INK,
  characterInk, applyConfig, presetConfig, presetNames,
  resetToDefaults, saveAsDefault, saveUserPreset,
} from './uiConfig'

// In-app UI Design panel (UI_PLAN.md's "design sandbox", living inside the
// real interface so the preview can never drift from the product): edit the
// chrome tokens live, switch presets, save your own, and Save as Default so
// Flowscape starts with your design.

const TOKEN_LABELS: [string, string][] = [
  ['panel-bg', 'Panel background'],
  ['panel-text', 'Panel text'],
  ['accent', 'Accent'],
  ['button-bg', 'Button background'],
  ['button-border', 'Button border'],
  ['button-hover', 'Button hover'],
  ['danger', 'Danger'],
  ['warn', 'Warning text'],
  ['outline', 'Outline'],
]

interface Props {
  config: UIConfig
  onChange: (cfg: UIConfig) => void
}

export default function DesignPanel({ config, onChange }: Props) {
  const [savedFlash, setSavedFlash] = useState(false)

  const update = (cfg: UIConfig) => {
    applyConfig(cfg)
    onChange(cfg)
  }

  const setToken = (key: string, value: string) =>
    update({ ...config, preset: 'Custom',
             theme: { ...config.theme, [key]: value } })

  // Map-ink character. Nudging a slider flips `character` to 'Custom'; picking a
  // named character resets the three multipliers to its preset (colour is kept).
  const ink: InkConfig = config.ink ?? DEFAULT_INK
  const setInk = (patch: Partial<InkConfig>) =>
    update({ ...config, ink: { ...ink, ...patch } })

  const flash = () => {
    setSavedFlash(true)
    window.setTimeout(() => setSavedFlash(false), 1200)
  }

  return (
    <div className="design">
      <div className="row">
        <label>Preset</label>
        <select value={presetNames().includes(config.preset) ? config.preset : 'Default'}
                onChange={(e) => update(presetConfig(e.target.value))}>
          {presetNames().map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
      </div>
      {TOKEN_LABELS.map(([key, label]) => (
        <div className="row" key={key}>
          <label>{label}</label>
          <input type="color" value={config.theme[key] ?? '#000000'}
                 onChange={(e) => setToken(key, e.target.value)} />
        </div>
      ))}
      <div className="row">
        <label>Font</label>
        <select value={config.fontFamily}
                onChange={(e) => update({ ...config, preset: 'Custom',
                                          fontFamily: e.target.value })}>
          {Object.keys(FONT_FAMILIES).map((name) => (
            <option key={name} value={name}>{name}</option>
          ))}
        </select>
      </div>
      <div className="row">
        <label>Font size {config.fontSize}px</label>
        <input type="range" min={11} max={17} step={1} value={config.fontSize}
               onChange={(e) => update({ ...config, preset: 'Custom',
                                         fontSize: Number(e.target.value) })} />
      </div>
      <div className="row">
        <label>Outline width {config.outlineWidth}px</label>
        <input type="range" min={0} max={4} step={1} value={config.outlineWidth}
               onChange={(e) => update({ ...config, preset: 'Custom',
                                         outlineWidth: Number(e.target.value) })} />
      </div>
      <div className="row">
        <label>Panel opacity</label>
        <input type="range" min={0.5} max={1} step={0.05} value={config.panelOpacity}
               onChange={(e) => update({ ...config, preset: 'Custom',
                                         panelOpacity: Number(e.target.value) })} />
      </div>
      <div className="row">
        <label>Corner radius {config.radius}px</label>
        <input type="range" min={0} max={16} step={1} value={config.radius}
               onChange={(e) => update({ ...config, preset: 'Custom',
                                         radius: Number(e.target.value) })} />
      </div>
      <div className="row"><label>Map ink</label></div>
      <div className="row">
        <label>Character</label>
        <select value={ink.character}
                onChange={(e) => update({ ...config, ink:
                  characterInk(e.target.value, ink.ink) })}>
          {Object.keys(INK_CHARACTERS).map((n) => <option key={n} value={n}>{n}</option>)}
          {!(ink.character in INK_CHARACTERS) && <option value="Custom">Custom</option>}
        </select>
      </div>
      <div className="row">
        <label>Wobble {ink.wobble.toFixed(1)}</label>
        <input type="range" min={0} max={2.5} step={0.1} value={ink.wobble}
               onChange={(e) => setInk({ character: 'Custom',
                                         wobble: Number(e.target.value) })} />
      </div>
      <div className="row">
        <label>Weight {ink.weight.toFixed(1)}</label>
        <input type="range" min={0.4} max={2} step={0.1} value={ink.weight}
               onChange={(e) => setInk({ character: 'Custom',
                                         weight: Number(e.target.value) })} />
      </div>
      <div className="row">
        <label>Density {ink.density.toFixed(1)}</label>
        <input type="range" min={0.5} max={1.6} step={0.1} value={ink.density}
               onChange={(e) => setInk({ character: 'Custom',
                                         density: Number(e.target.value) })} />
      </div>
      <div className="row">
        <label>Ink colour</label>
        <input type="color" value={ink.ink}
               onChange={(e) => setInk({ ink: e.target.value })} />
      </div>
      <div className="row buttons">
        <button onClick={() => { saveAsDefault(config); flash() }}>
          {savedFlash ? '✓ Saved' : 'Save as Default'}
        </button>
      </div>
      <div className="row buttons">
        <button onClick={() => {
          const name = window.prompt('Preset name:', 'My Layout')
          if (name) { saveUserPreset(name, config); update({ ...config, preset: name }) }
        }}>Save as Preset…</button>
        <button onClick={() => update(resetToDefaults())}>Reset</button>
      </div>
    </div>
  )
}
