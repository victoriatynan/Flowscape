> **Status (2026-07-08): implemented, rescoped for the web client.** The
> pygame references predate the completed web migration. The framework this
> plan asks for collapses onto the web platform: themes are CSS custom
> properties (`web/src/uiConfig.ts` + `App.css`) with preset inheritance
> (presets override only what changes on top of the developer defaults);
> user preferences are versioned config in localStorage layered over shipped
> defaults; and the "design sandbox" is an in-app Design panel (🎨 in the
> toolbar) editing the live interface — so the preview can never drift from
> the product. Save-as-Default, named user presets, and built-in themes
> (Default / Dark Simulation / Blueprint / Minimal) are live. Typography:
> a named font-stack selector (System / Humanist / Display / Serif /
> Monospace) plus font size. Shape: global outline color + thickness
> (0–4 px, applied to every panel, button, and input), corner radius, and
> panel opacity. World/canvas colors remain the map's fantasy-24 identity
> (served by /api/palette) and are deliberately not user-themable.
> Original text follows.

Create a standalone UI Design Sandbox for Flowscape that allows me to prototype, customize, and save the interface design before implementing final UI changes.

The system should be designed as a long-term UI configuration framework, not just a temporary editor. UI appearance, layout, behavior, and user preferences should be separated from the actual UI code so the interface can evolve without requiring major rewrites.

The goal is to create a professional editor-style UI framework where I can visually design the interface, save my preferred layouts, and allow Flowscape to automatically load those settings in the future.

---

## 1. Live UI Preview

Create a preview window that displays example Flowscape UI elements such as:

* Side panels
* Toolbars
* Buttons
* Sliders
* Dropdown menus
* Inspector panels
* Traffic statistics displays
* Simulation controls

Any changes made through the editor should update the preview immediately.

The preview should behave similarly to the actual Flowscape interface so designs can be tested before being implemented.

---

## 2. Adjustable UI Properties

Allow customization through sliders, inputs, dropdowns, and toggles.

### Layout

* Panel width and height
* Panel positions
* Docking behavior
* Toolbar size
* Spacing between elements
* Padding and margins
* UI scaling
* Screen-relative positioning

Avoid storing fixed pixel positions where possible.

Instead of:

```
sidebar_x = 1400
sidebar_width = 300
```

Prefer:

```
sidebar = {
    "dock": "right",
    "width_percentage": 0.25
}
```

This allows the UI to support:

* Different resolutions
* Different aspect ratios
* Desktop version
* Future web version

---

## 3. Visual Style Controls

Allow customization of:

### Colors

* Background colors
* Accent colors
* Text colors
* Warning/error colors
* Congestion colors
* Transparency

### Shape and Effects

* Border thickness
* Corner radius
* Shadows
* Highlight effects
* Hover effects
* Selected states
* Disabled states

### Typography

* Font selection
* Font size
* Font weight
* Text spacing

---

## 4. Component Customization

Allow editing individual UI components.

Examples:

Buttons:

* Size
* Icon placement
* Text alignment
* Hover behavior
* Selected appearance

Panels:

* Header style
* Collapsing behavior
* Docking behavior

Sliders:

* Track style
* Handle size
* Value display

This should allow future UI components to be added without redesigning the system.

---

# 5. Save as Default System

Include a prominent:

## "Save as Default"

button.

When pressed:

1. Save the current UI configuration to a persistent configuration file.
2. Flowscape automatically loads this configuration when starting.
3. The interface opens with the saved default design every time.

The system should save configuration data, not UI objects.

Example:

```
UI Design Sandbox
        |
        ↓
UI Configuration Data
        |
        ↓
Save as Default
        |
        ↓
ui_settings.json
        |
        ↓
Flowscape Startup
        |
        ↓
Load UI Configuration
```

---

# 6. UI Presets

Support multiple UI profiles.

Examples:

* Default
* Engineering Mode
* Teaching Mode
* Minimal Mode
* Debug Mode
* Custom User Layout

Allow:

* Creating new presets
* Saving current settings as a preset
* Loading presets
* Switching between presets

Example:

```
Presets

[Default]
[Teaching]
[Engineering]
[Minimal]

[Save Current As New Preset]
[Save as Default]
```

---

# 7. User Preferences vs Developer Defaults

Separate built-in defaults from user customization.

Use two layers:

## Developer Default

Example:

```
default_ui.json
```

Contains:

* The official Flowscape interface design
* The layout shipped with the application
* Default themes

## User Preferences

Example:

```
user_preferences.json
```

Contains:

* Personal panel sizes
* Favorite layout
* Enabled/disabled panels
* Personal theme adjustments

Loading order:

```
Developer Defaults
        ↓
Apply User Preferences
        ↓
Final UI
```

This allows users to customize the interface without modifying the original files.

---

# 8. Theme System With Inheritance

Create a theme system where themes can build on top of each other.

Example:

```
Base Theme
      |
      ↓
Industrial Theme
      |
      ↓
Custom User Theme
```

Instead of copying every setting, themes only override what changes.

Example:

```
Industrial Theme:

inherits:
    Base Theme

changes:
    panel_color
    accent_color
    font_style
```

Possible themes:

* Industrial
* Blueprint
* Engineering CAD
* Dark Simulation
* Educational
* Custom

---

# 9. Versioned Configuration Files

Future-proof configuration files by including:

* Configuration version number
* Migration support for older settings

Example:

```json
{
    "version": 1,
    "theme": {},
    "layout": {},
    "components": {}
}
```

If the UI system changes later, older configuration files should be upgraded instead of becoming unusable.

Example:

```
Old Settings File
        |
        ↓
Migration System
        |
        ↓
New Settings Format
```

---

# 10. Separate UI Logic From Configuration

Do not hard-code UI values inside components.

Avoid:

```python
panel_width = 300
```

Instead:

```python
panel_width = UIConfig.panel_width
```

UI components should request their appearance and behavior settings from the configuration system.

The UI should be responsible for:

* Displaying information
* Handling interaction

The configuration system should control:

* Appearance
* Layout
* Defaults
* Preferences

---

# 11. Future Platform Support

Design the system so the same UI configuration approach could support:

* Current Pygame desktop version
* Future web version
* Different screen resolutions
* Different aspect ratios
* Different user preferences

The UI configuration should not depend on the rendering system.

---

# Final Architecture Goal

```
UI System
|
├── UI Manager
|
├── UI Components
|     ├── Buttons
|     ├── Panels
|     ├── Sliders
|     ├── Menus
|     └── Inspector Views
|
├── UI Configuration Manager
|     ├── Load Settings
|     ├── Save Settings
|     ├── Manage Presets
|     ├── Handle Defaults
|     └── Version Migration
|
├── Theme Manager
|     ├── Base Themes
|     ├── Custom Themes
|     └── Theme Inheritance
|
├── User Preferences
|
└── UI Design Sandbox
```

The final system should allow me to visually design Flowscape's interface, save the preferred design, support user customization, maintain compatibility with future versions, and allow the UI to evolve independently from the traffic simulation engine.
