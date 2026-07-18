# 03 · Shapes & Silhouettes

> **Tier:** Core · **Status:** Migrated (from `UI-new`, `UI-Graphic-Design`, `Rendering-Lighting`)
> **Related:** [02 Composition](02_Composition_Hierarchy.md) · [04 Linework](04_Linework_Ink.md) · [09 QA](09_QA_Decision_Framework.md)

Silhouette is the **first** thing in the illustration hierarchy. If the silhouette fails, the
asset fails regardless of color or detail.

## Shape language — organic, never primitive

Every object is constructed from flowing organic curves. **Never** build objects from primitive
geometric shapes.

**Avoid:** perfect circles, rectangles, ellipses; uniform corner radii; mechanically smooth
Bézier curves; CAD-like precision; perfect bilateral symmetry.

**Every silhouette should contain:** variable curvature, slight asymmetry, natural contour
drift, organic deformation, rounded transitions, hand-guided flow.

Applies to UI components too — panels and buttons should have slightly irregular silhouettes,
hand-drawn contours, small asymmetries, and imperfect corners. No two repeated shapes identical.

## Large → medium → small construction

Build in this order — never begin with decorative details:

> **Large shapes** (dominate) → **secondary forms** (reinforce) → **small details** (decorate)

- Large forms should dominate.
- Medium forms should reinforce.
- Small forms should decorate.

## Shadow shapes describe structure

Shadow boundaries follow the underlying geometry — they are intentionally designed, never
airbrush blobs, circular gradients, or random dark patches. If a shadow is removed, the object
should lose volume. (Mechanics in [05 Lighting](05_Lighting_Shading.md).)

## The silhouette test

An illustration must be recognizable as a **solid black silhouette** before any interior
detail or color. Icons especially must read as a black ink silhouette first. (See the full
check in [09 QA](09_QA_Decision_Framework.md).)

## TODO / to expand

- [ ] Silhouette proportion guidance per asset class (vehicle, tree, building, icon)
- [ ] Reference silhouette sheet (approved vs. rejected shapes)
