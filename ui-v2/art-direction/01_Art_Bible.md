# 01 · Art Bible

> **Tier:** Core · **Status:** Migrated (from `UI-new`, `UI-Graphic-Design`)
> **Related:** [04 Linework](04_Linework_Ink.md) · [05 Lighting](05_Lighting_Shading.md) · [09 QA](09_QA_Decision_Framework.md)

## Vision

The Flowscape interface emulates a **traditionally illustrated fantasy cartographer's field
journal** rather than a digitally designed application. Every visual element — UI *and*
simulation — should appear physically created with dip-pen ink, graphite underdrawing,
transparent watercolor, and textured cotton paper before being scanned into the app.

It should evoke an explorer's atlas, botanical manuscript, or illuminated journal, and
communicate **craftsmanship, warmth, and timelessness** — never precision-manufactured software.

> The interface *is* the illustration. It is not a modern interface with botanical decorations
> laid on top; every panel, button, icon, border, and label is drawn.

## Priorities — the illustration hierarchy

Every asset follows the same order of importance used in traditional ink illustration:

1. Silhouette
2. Structure
3. Value
4. Line weight
5. Material definition
6. Color
7. Decorative detail

**Decoration never compensates for poor structure.** An illustration must be fully
understandable in grayscale, before any color is applied.

## Make the craft obvious (readability & scale)

The handcrafted style must be visible at normal viewing distance and 100% zoom on a standard
monitor — not a microscopic texture revealed only when magnified.

- Ink line-weight variation should be **obvious**, not subtle.
- Watercolor strokes, pigment pooling, and darker edges visible without zooming.
- Paper texture visible behind every element.
- Decorative flourishes large enough to contribute to identity, never tiny noise.
- When choosing between realistic-but-imperceptible vs. slightly-exaggerated-but-visible,
  **always choose the more visible option.**

> Treat the interface as a hand-painted illustration that happens to function as software,
> rather than software with subtle artistic effects. If a user cannot immediately tell the
> interface is hand-illustrated from a normal viewing distance, the rendering is too subtle.

## Forbidden styles

Reject modern UI aesthetics and rendering techniques wholesale:

- Flat / Material / Fluent Design, Glassmorphism, Neumorphism, minimalism
- Clean vector graphics, SVG-style illustration, uniform stroke widths
- Crisp geometric borders, pixel-perfect / machine-generated alignment
- Pure white backgrounds, pure black ink, high-saturation / neon color, synthetic RGB
- Smooth digital gradients, soft drop shadows, plastic/glossy/metallic surfaces
- Generic icon packs (Material, Fluent, SF Symbols, Heroicons, Lucide, Feather)

> If an element looks like it was generated as a modern vector graphic first and decorated
> afterward, it fails.

## ⚠ Aesthetic conflict to resolve

The Heritage Atlas source called for **engraved brass / metallic** accents and "engineering,
not fantasy." That conflicts with the botanical/watercolor prohibitions above (no metal, no
gloss). These docs resolve toward the hand-illustrated watercolor language; see
[00 README](00_README.md) and [06 Color Theory](06_Color_Theory.md) for the pending call.
