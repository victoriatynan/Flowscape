# 06 · Color Theory

> **Tier:** Core · **Status:** Migrated — ⚠ palette decision needed
> **Related:** [05 Lighting](05_Lighting_Shading.md) · [07 Materials](07_Materials_Textures.md) · [08 UI](08_UI_Icons_Components.md)

## Color philosophy

Color should resemble **natural pigments rather than emitted light** — every color physically
mixed, no synthetic RGB appearance. **Color reinforces structure; it never defines it.** An
asset must read fully in grayscale before color is applied.

## Palette (Fantasy Cartography direction)

Warm, muted, harmonious. Every color carries a slight **earth-tone bias**.

Warm parchment · ivory · moss green · sage green · olive green · forest green · weathered wood ·
slate gray · river blue · ochre · brass gold · rust · dusty lavender · clay brown.

White is always **exposed paper**, never pure digital white.

## Saturation rules

Globally desaturate every color before use; target natural watercolor pigment. **Prohibited:**
neon, fluorescent, pure cyan / magenta / yellow, fully saturated green, digital blue, pure RGB
primaries. No color dominates the interface through saturation alone.

## Value hierarchy

Never establish emphasis with saturation alone. Emphasis order: silhouette contrast → line
weight → value contrast → shape scale → detail density → hue variation → saturation.
(See [02 Composition](02_Composition_Hierarchy.md).)

## ⚠ Decision needed — two palettes in the source

| | Heritage Atlas | Fantasy Cartography / Botanical |
|---|---|---|
| Background | Deep teal, forest green, dark slate | Warm ivory / aged cream paper |
| Secondary | Sage, olive, terracotta, dusty rose, parchment | Moss/sage/olive, clay, slate, river blue |
| Accents | **Antique brass, burnished gold, aged bronze (metallic)** | Ochre, rust, brass *gold as pigment*, dusty lavender |
| Finish | Engraved metal, cloth-bound covers | Watercolor on cotton paper, **no metallic** |

The two share the earthy green/parchment base but conflict on **metallic accents**: Heritage
Atlas wants real brass/bronze finish; the botanical direction forbids metallic/gloss and treats
"brass gold" as a flat pigment color only.

**These docs assume the botanical resolution** (brass as a muted pigment, no metallic finish).
Confirm or override before a swatch set is locked.

## TODO / to expand

- [ ] Lock the final swatch set with hex values once the palette decision is made
- [ ] Define semantic roles (background, panel, ink, primary accent, warning/error, selection)
- [ ] Simulation-specific colors (roads, lane markings, vehicles, overlays, heatmaps) — must
      stay readable over paper texture; see [08 UI](08_UI_Icons_Components.md)
