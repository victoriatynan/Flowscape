# 07 · Materials & Textures

> **Tier:** Core · **Status:** Migrated (from `Rendering-Lighting`, `UI-new`, `UI-Graphic-Design`)
> **Related:** [04 Linework](04_Linework_Ink.md) · [05 Lighting](05_Lighting_Shading.md) · [06 Color](06_Color_Theory.md)

Every material has its own visual vocabulary and must remain recognizable **in grayscale**,
before color.

## Material vocabularies

### Wood
Thick irregular contour; long directional grain; rounded worn edges; hairline cracks; visible
growth patterns; darker crevices; slight warping. Broad soft form shadows; rounded highlights
along worn edges; no sharp reflections.

### Stone
Heavy silhouette; chipped/weathered edges; sparse fractures; soft corners; layered planes;
weight toward the base. Larger shadow planes; broken highlights; localized chips catching light;
rough-surface scattering.

### Vegetation / leaves
Flowing contours; elegant tapering; organic branching; minimal interior detail; overlapping
masses; delicate terminals. Thin translucent edges; soft shadow transitions; slight local-color
variation; minimal texture.

### Metal / brass
Cleaner contours; engraved ornamentation; slight edge wear; **oxidized / tarnished** brass
appearance; restrained highlights; slight reflected light. ⚠ Keep matte/pigmented, not glossy —
see the palette decision in [06 Color](06_Color_Theory.md).

### Paper
Visible cotton grain and fiber texture; warm ivory coloration; slight discoloration; pigment
absorption; ink bleed. Almost no specular highlight; gentle diffuse value changes.

## Watercolor rendering

Watercolor stays **subordinate to the ink drawing** — line work dominates; paint reinforces.
Every painted region contains: transparent layering, uneven pigment density, subtle value and
hue variation, pigment pooling, soft glazing, visible paper grain, edge darkening, controlled
bloom. **Flat digital fills are prohibited.** Build value through transparent glazing (see
[05 Lighting](05_Lighting_Shading.md)).

## Paper simulation

All illustration appears on textured cotton paper, and the paper influences every color:
warm ivory base, fine grain, cotton fiber, slight aging, soft discoloration. Background is never
perfectly flat or pure white.

## Surface texture / imperfection

Nothing is perfectly clean. Include subtle, **consistent** ink speckles, paint splatters, dry-
brush edges, paper grain, slight watercolor bleed. These read as intentional craftsmanship, not
damage — and must remain visible at UI scale (see [01 Art Bible](01_Art_Bible.md)).
