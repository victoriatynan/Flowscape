# 09 · QA & Decision Framework

> **Tier:** Enforcement · **Status:** Migrated (from `UI-new`, `Rendering-Lighting`)
> **Related:** [03 Shapes](03_Shapes_Silhouettes.md) · [04 Linework](04_Linework_Ink.md) · [05 Lighting](05_Lighting_Shading.md)

The checks every asset must pass before it is "done." When in doubt, an asset that fails any of
the three tests below is revised **before** more detail is added.

## The three tests

### 1. Silhouette test
Reduce the asset to a solid black silhouette. Is it immediately recognizable? Icons especially
must read as a black ink silhouette before color. Fail → fix the structure, not the detail.

### 2. Squint test
Blur the image / view from a distance / reduce to a thumbnail:
- Primary silhouette remains instantly recognizable.
- Major light and shadow masses still describe volume.
- Focal elements remain visually dominant.
- Decorative details disappear before structural information.
- Composition stays balanced and readable **without relying on color**.

If squinting makes the object confusing or lose form, the value structure is insufficient.

### 3. Grayscale test
Remove all color. The asset must remain fully readable — every material recognizable by line and
value alone. Color is only ever reinforcement (see [06 Color](06_Color_Theory.md)).

## Full asset checklist

Every UI asset must satisfy all of the following:

- [ ] Silhouette is immediately recognizable.
- [ ] Line weight follows the defined hierarchy ([04](04_Linework_Ink.md)).
- [ ] Stroke width varies continuously with believable pen pressure.
- [ ] Thickest lines at bases, overlaps, shadowed structural edges.
- [ ] Thinnest lines at tips, exposed edges, illuminated surfaces.
- [ ] Internal contours explain volume without competing with the silhouette.
- [ ] Surface detail reinforces material and never creates unnecessary noise.
- [ ] Curves are organically asymmetric — no perfect geometric construction.
- [ ] Negative space intentionally preserved (~60–70% open) for clarity.
- [ ] Cross-hatching follows surface curvature and only describes form.
- [ ] Every material has a unique rendering vocabulary independent of color.
- [ ] Watercolor stays transparent and never obscures the ink drawing.
- [ ] Paper texture remains visible beneath all painted regions.
- [ ] Colors globally harmonized, restrained saturation, warm grading.
- [ ] No pure black, pure white, or synthetic RGB.
- [ ] Lighting is diffuse, matte, painterly; single consistent light source (~upper-left 45°).
- [ ] Decorative elements enhance the aesthetic without reducing usability.
- [ ] The handcrafted quality is obvious at 100% zoom on a standard monitor (not micro-texture).
- [ ] Asset is fully readable in grayscale before watercolor.

## Final bar

> The finished asset should be visually indistinguishable from a high-quality scanned
> illustration from a fantasy cartographer's field journal or botanical manuscript — never from
> a modern vector graphics editor.
