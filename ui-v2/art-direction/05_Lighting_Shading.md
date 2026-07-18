# 05 · Lighting & Shading

> **Tier:** ★ Most important · **Status:** Migrated (from `Rendering-Lighting`, `UI-new`, `UI-Graphic-Design`)
> **Related:** [04 Linework](04_Linework_Ink.md) · [07 Materials](07_Materials_Textures.md) · [09 QA](09_QA_Decision_Framework.md)

Lighting exists to communicate three-dimensional **form, material, and depth** — not simply to
make objects darker. Every shadow, highlight, and transition should reinforce the object's
underlying structure. The viewer should understand an object's volume even with all color
removed. Rendering should resemble traditional ink and watercolor illustration, not digital
painting.

## Light source consistency

Establish a **single dominant light source** before rendering. Unless a scene requires otherwise:

- Primary light direction: **upper-left (~45°)**
- Secondary ambient bounce from the environment
- Soft global illumination

The light source stays consistent across **all** UI assets. Identical objects must not have
different lighting directions.

## Form before texture

Shading describes the large 3D form before any material texture. Rendering order is always:

> silhouette → major forms → shadow masses → secondary forms → material definition →
> fine texture → small highlights

Never begin by adding texture or surface detail.

## Shadow hierarchy — three categories

### Form shadows — surface turning from the light
Soft transitions, large shapes, low-frequency value change; define curvature. Never sharp edges
on rounded objects. (Tree trunks, rounded stones, hills, wooden handles.) These establish volume.

### Cast shadows — one object blocking light from another
Higher contrast, more defined edges near the caster, softening with distance; follow the
receiving surface. Separate overlapping objects and anchor them to the environment.

### Occlusion shadows — where light cannot physically reach
Always the **darkest values**. Small, high-contrast, narrow, soft-edged, **warm dark brown
rather than pure black**. (Between roots, under rocks, inside bark cracks, between stacked
papers, under overlapping leaves, around intersections.) Use sparingly — they create depth.

## Value grouping

Group values into large readable masses (large light / large midtone / large shadow), not
isolated patches. Avoid scattered dark spots; group shadows together. Improves small-size
readability. (See [02 Composition](02_Composition_Hierarchy.md).)

## Edge control — three edge types in every illustration

- **Hard edges** (used sparingly): object silhouettes, cast-shadow contact points, stone
  fractures, sharp carved edges.
- **Soft edges** (most common): rounded wood, leaves, cloth, watercolor transitions, form shadows.
- **Lost edges** (intentional): edges that disappear into nearby values where values become
  similar, light washes out contours, or objects blend into atmosphere. Not every edge is
  outlined equally.

## Ambient & reflected light

- Shadows never go fully black — every shadow still receives indirect environmental light,
  shifting slightly cooler/neutral while staying muted. Avoid dead black shadows.
- Rounded objects get subtle **reflected light** on the shadow side (trunks, stones, buildings,
  wooden objects). It reinforces volume — never brighter than the directly lit surface.

## Highlight placement

Highlights exist only where they reinforce form. Never symmetric, never white circles. Place on:
curvature facing the light, rounded corners, polished edges, moist surfaces, slightly worn wood.
Follow the object's geometry.

## Shadow temperature

Classical color theory — **light:** slightly warmer, more saturated; **shadow:** slightly
cooler, slightly desaturated. Avoid dramatically blue shadows unless the environment requires.

## Watercolor shadow behavior

Build shadows through **transparent glazing**, not opaque paint. Each wash deepens value while
preserving paper texture, pigment variation, and color harmony. Transitions show slight pigment
pooling, uneven drying, soft feathering, layered transparency — never digital gradients.

## Overall lighting mood

Diffuse and ambient. **Avoid** gloss, metallic reflections, bloom, rim lighting, sharp
highlights, hard shadows. **Use** soft watercolor glazing, broad shadow transitions, warm
reflected light, matte surfaces. Shading comes from watercolor layering, not digital lighting.

## Contrast management

Reserve highest contrast for focal points (full hierarchy in
[02 Composition](02_Composition_Hierarchy.md)). Everything cannot be equally important.
