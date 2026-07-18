"""
Line weight as visual hierarchy.

Same wobbly-dot line as before, but now each stamped dot's THICKNESS and
DARKNESS can change along the line. That single upgrade lets us express the four
line-weight principles:

  1. Focal point / silhouette : hero objects get thick, dark outlines;
                                background objects get thin, pale ones.
  2. Lighting & shadow        : an edge facing the light thins & lightens;
                                the edge facing away thickens & darkens.
  3. Depth / contact points   : where two things touch, lay an extra-heavy,
                                near-black line (fake ambient occlusion).
  4. Internal detail          : folds, textures, panel lines use the thinnest,
                                palest weight so they never fight the silhouette.

The trick that makes it work: give every VERTEX its own weight + color, then
taper (lerp) smoothly between them as we draw each edge.
"""

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


# ----------------------------------------------------------------------------
# small math helpers
# ----------------------------------------------------------------------------
def lerp(a, b, t):
    return a + (b - a) * t


def lerp_color(c0, c1, t):
    return tuple(int(lerp(c0[k], c1[k], t)) for k in range(3))


def normalize(vx, vy):
    length = np.hypot(vx, vy) or 1.0
    return vx / length, vy / length


def smooth_series(vals, radius=4, closed=True):
    """Gaussian-blur a list of numbers ALONG the path.

    Curvature is concentrated at one vertex, which would spike into a node. By
    smearing that spike over its neighbors, the weight ramps up gradually as the
    path approaches the bend and eases off after it -- a gradual swell, not a
    blob planted on the corner.
    """
    n = len(vals)
    if radius <= 0 or n == 0:
        return list(vals)
    sigma = radius / 2.0
    ker = [np.exp(-(d * d) / (2 * sigma * sigma)) for d in range(-radius, radius + 1)]
    out = []
    for i in range(n):
        acc = wsum = 0.0
        for off, kw in zip(range(-radius, radius + 1), ker):
            idx = i + off
            if closed:
                idx %= n
            elif idx < 0 or idx >= n:
                continue
            acc += vals[idx] * kw
            wsum += kw
        out.append(acc / wsum if wsum else 0.0)
    return out


def _smooth_vectors(vecs, radius=4, closed=True):
    """Blur a list of (x, y) vectors along the path, component by component."""
    xs = smooth_series([v[0] for v in vecs], radius, closed)
    ys = smooth_series([v[1] for v in vecs], radius, closed)
    return list(zip(xs, ys))


def inner_bisector(a, p, b):
    """Vector pointing to the INSIDE (concave side) of the bend at p.

    It is the sum of the two unit edge directions leaving p. On a straight run
    the two nearly cancel (~0); at a tight turn it grows and points into the
    curve -- exactly the side the extra line-weight should build toward. Works
    for convex AND concave corners, since it follows the local bend, not the
    shape's center.
    """
    d1x, d1y = normalize(a[0] - p[0], a[1] - p[1])
    d2x, d2y = normalize(b[0] - p[0], b[1] - p[1])
    return d1x + d2x, d1y + d2y


# ----------------------------------------------------------------------------
# fast batched rasterizer: stamp thousands of dots in vectorized numpy passes
# instead of one PIL ellipse (+ scalar RNG) per dot
# ----------------------------------------------------------------------------
_DISK_CACHE = {}


def _disk(r):
    """Cached (dy, dx) pixel offsets of a filled disk of integer radius r."""
    if r not in _DISK_CACHE:
        g = np.arange(-r, r + 1)
        dy, dx = np.meshgrid(g, g, indexing="ij")
        m = dx * dx + dy * dy <= (r + 0.3) ** 2
        _DISK_CACHE[r] = (dy[m].astype(np.int32), dx[m].astype(np.int32))
    return _DISK_CACHE[r]


def _splat(buf, xs, ys, rs, cols):
    """Darken-composite many dots into an RGB uint8 buffer, grouped by radius.

    All dots of the same integer radius share one precomputed disk stamp, so
    each group rasterizes in a single vectorized np.minimum.at pass. Darken
    compositing (min) matches opaque dark ink on light paper and is order-
    independent, letting us batch every dot of a shape into one call.
    """
    if len(xs) == 0:
        return
    H, W = buf.shape[:2]
    xi = np.round(xs).astype(np.int32)
    yi = np.round(ys).astype(np.int32)
    ri = np.clip(np.round(rs).astype(np.int32), 0, 64)
    ci = np.clip(np.round(cols), 0, 255).astype(np.uint8)

    for r in np.unique(ri):
        sel = ri == r
        dy, dx = _disk(int(r))
        yy = yi[sel][:, None] + dy[None, :]        # (K, D)
        xx = xi[sel][:, None] + dx[None, :]
        inb = (yy >= 0) & (yy < H) & (xx >= 0) & (xx < W)
        cc = np.broadcast_to(ci[sel][:, None, :], yy.shape + (3,))
        np.minimum.at(buf, (yy[inb], xx[inb]), cc[inb])


class Canvas:
    """A numpy RGB buffer with a batched dot primitive; converts to/from PIL.

    Text is deferred (drawn once at to_pil time) so a whole image can be stamped
    into the fast numpy buffer and only crosses back into PIL a single time.
    """

    def __init__(self, background):
        self.buf = np.asarray(background.convert("RGB"), dtype=np.uint8).copy()
        self._texts = []

    def splat(self, xs, ys, rs, cols):
        _splat(self.buf, np.asarray(xs), np.asarray(ys),
               np.asarray(rs), np.asarray(cols, dtype=float).reshape(-1, 3))

    def text(self, xy, s, fill=(0, 0, 0), font=None):
        self._texts.append((xy, s, fill, font))

    def to_pil(self):
        img = Image.fromarray(self.buf)
        if self._texts:
            d = ImageDraw.Draw(img)
            for xy, s, fill, font in self._texts:
                d.text(xy, s, fill=fill, font=font)
        return img


# ----------------------------------------------------------------------------
# the core line: thickness AND color taper from start to end
# ----------------------------------------------------------------------------
def draw_textured_line(canvas, p0, p1, w0, w1, c0, c1,
                       offset_jitter=1.0, size_jitter=0.4, spacing=1.3):
    """Stamp a wobbly, weight/color-tapered line as one vectorized dot batch."""
    x0, y0 = p0
    x1, y1 = p1
    steps = max(int(np.hypot(x1 - x0, y1 - y0) / spacing), 1)
    t = np.linspace(0.0, 1.0, steps + 1)

    x = x0 + (x1 - x0) * t + np.random.normal(0, offset_jitter, t.shape)
    y = y0 + (y1 - y0) * t + np.random.normal(0, offset_jitter, t.shape)
    r = np.maximum(0.4, (w0 + (w1 - w0) * t) + np.random.normal(0, size_jitter, t.shape))
    c0, c1 = np.asarray(c0, float), np.asarray(c1, float)
    cols = c0 + (c1 - c0) * t[:, None]
    canvas.splat(x, y, r, cols)


def contour_inward_normals(pts):
    """Unit normal at each vertex pointing INTO a closed contour.

    Perpendicular to the local tangent, oriented to the interior via the
    contour's winding. Unlike the corner bisector, it is defined and smooth
    everywhere (even on straight edges), so weight can grow inward consistently
    and thick strokes stay smooth instead of scalloping.
    """
    n = len(pts)
    normals = []
    for i in range(n):
        (ax, ay), (bx, by) = pts[(i - 1) % n], pts[(i + 1) % n]
        tx, ty = normalize(bx - ax, by - ay)   # tangent
        normals.append((-ty, tx))              # left-hand normal
    # orient all normals toward the interior (majority vote against centroid)
    cx = sum(p[0] for p in pts) / n
    cy = sum(p[1] for p in pts) / n
    score = sum(nx * (cx - px) + ny * (cy - py)
                for (nx, ny), (px, py) in zip(normals, pts))
    if score < 0:
        normals = [(-nx, -ny) for nx, ny in normals]
    return normals


def stamp_weighted_path(canvas, pts, weights, colors, inward, base_w,
                        closed=True, offset_jitter=0.6, size_jitter=0.3,
                        spacing=1.2):
    """Fill a variable-weight stroke's cross-section inward, vectorized.

    Same model as before -- pin the outer edge, lay a fixed-size nib inward to
    the required thickness so it stays smooth at any weight -- but every dot of
    every edge is computed as numpy arrays and rasterized in a single batch,
    replacing tens of thousands of per-dot ellipse + scalar-RNG calls.
    """
    pts = np.asarray(pts, float)
    weights = np.asarray(weights, float)
    inward = np.asarray(inward, float)
    cols = np.asarray(colors, float)
    n = len(pts)
    edges = n if closed else n - 1
    dot_r = max(0.6, base_w * 0.9)         # fine, fixed nib
    rib_step = dot_r * 0.8                  # inward spacing between dots

    Xs, Ys, Rs, Cs = [], [], [], []
    for i in range(edges):
        j = (i + 1) % n
        p0, p1 = pts[i], pts[j]
        steps = max(int(np.hypot(*(p1 - p0)) / spacing), 1)
        t = np.linspace(0.0, 1.0, steps + 1)                       # (S,)

        px = p0[0] + (p1[0] - p0[0]) * t
        py = p0[1] + (p1[1] - p0[1]) * t
        w = weights[i] + (weights[j] - weights[i]) * t
        ix = inward[i, 0] + (inward[j, 0] - inward[i, 0]) * t
        iy = inward[i, 1] + (inward[j, 1] - inward[i, 1]) * t
        ln = np.hypot(ix, iy)
        ln[ln == 0] = 1.0
        inx, iny = ix / ln, iy / ln
        cseg = cols[i] + (cols[j] - cols[i]) * t[:, None]          # (S, 3)

        # rib grid: fill inward from the outer edge by the full thickness (2w)
        ribs = np.maximum(0.0, 2 * w - 2 * dot_r) / rib_step
        M = int(np.ceil(ribs.max())) if ribs.size else 0
        mm = np.arange(M + 1)[None, :]                             # (1, M+1)
        valid = mm <= ribs[:, None]                               # (S, M+1)
        off = dot_r + mm * rib_step                               # inward distance
        cx = px[:, None] + inx[:, None] * off                     # (S, M+1)
        cy = py[:, None] + iny[:, None] * off
        cg = np.broadcast_to(cseg[:, None, :], valid.shape + (3,))

        Xs.append(cx[valid]); Ys.append(cy[valid])
        Rs.append(np.full(int(valid.sum()), dot_r)); Cs.append(cg[valid])

    if not Xs:
        return
    x = np.concatenate(Xs); y = np.concatenate(Ys)
    r = np.concatenate(Rs); c = np.concatenate(Cs)
    x = x + np.random.normal(0, offset_jitter, x.shape)
    y = y + np.random.normal(0, offset_jitter, y.shape)
    r = np.maximum(0.4, r + np.random.normal(0, size_jitter, r.shape))
    canvas.splat(x, y, r, c)


# ----------------------------------------------------------------------------
# a lit shape: weight & color driven by the light direction
# (also thickens at tight corners -- see principle 5 below)
# ----------------------------------------------------------------------------
def draw_lit_shape(canvas, pts, light_dir,
                   min_w=1.0, max_w=4.5,
                   lit_color=(120, 114, 104),   # thin/pale where lit
                   shadow_color=(24, 21, 18),    # thick/dark where in shadow
                   curve_scale=45.0, curve_cap=4.0,  # corner-bulge strength/ceiling
                   curve_spread=4,                    # how far the bulge ramps
                   closed=True, **line_kwargs):
    """pts: list of (x, y). light_dir: vector pointing TOWARD the light.

    Each vertex's weight = light-based weight + a corner bulge that is smeared
    over its neighbors, so a single shape shows BOTH effects: it thins toward
    the light and darkens away from it, while every tight turn swells gradually
    from the inner edge instead of blobbing on the vertex.
    """
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    lx, ly = normalize(*light_dir)
    n = len(pts)

    light_w, colors, bonus = [], [], []
    for i, (px, py) in enumerate(pts):
        # outward normal ~ direction from center to the vertex
        nx, ny = normalize(px - cx, py - cy)
        lighting = nx * lx + ny * ly        # +1 faces light, -1 faces away
        shade = (1 - lighting) / 2          # 0 = fully lit, 1 = full shadow
        light_w.append(lerp(min_w, max_w, shade))
        colors.append(lerp_color(lit_color, shadow_color, shade))

        # raw corner bulge (1/radius), except at open-path endpoints
        if closed or 0 < i < n - 1:
            k = local_curvature(pts[(i - 1) % n], pts[i], pts[(i + 1) % n])
            bonus.append(min(curve_cap, curve_scale * k))
        else:
            bonus.append(0.0)

    # smear the corner bulge so it ramps up gradually toward each turn
    bonus = smooth_series(bonus, radius=curve_spread, closed=closed)
    weights = [lw + b for lw, b in zip(light_w, bonus)]

    # inward direction: true contour normal (closed) is smooth everywhere;
    # open paths fall back to the local bend bisector
    if closed:
        inward = contour_inward_normals(pts)
    else:
        inward = _smooth_vectors(
            [inner_bisector(pts[(i - 1) % n], pts[i], pts[(i + 1) % n])
             if 0 < i < n - 1 else (0.0, 0.0) for i in range(n)],
            radius=curve_spread, closed=False)

    # grow the extra weight inward from a pinned outer edge (no corner blobs)
    stamp_weighted_path(canvas, pts, weights, colors, inward, base_w=min_w,
                        closed=closed, **line_kwargs)


# ----------------------------------------------------------------------------
# principle 3: soft contact / occlusion shadow where things touch
# ----------------------------------------------------------------------------
def add_soft_contact_shadow(img, cx, y, half_width, thickness,
                            color=(15, 12, 10), strength=0.65,
                            blur=11, offset_jitter=3.5, spacing=1.3):
    """
    Build the shadow as a soft GRADIENT instead of a solid disk.

    Why this reads as soft (vs the old hard smudge):
      - We stamp into a separate grayscale "density" mask, not the picture.
      - Each dot's darkness AND radius taper to zero at the two ends
        (edge = 1 in the middle, 0 at the tips), so nothing chops off.
      - GaussianBlur smears the whole mask, turning hard dot edges into a fade.
      - The mask is used as an ALPHA channel, so the color blends into the
        paper by degree instead of painting flat, opaque black.
    """
    mask = Image.new("L", img.size, 0)
    md = ImageDraw.Draw(mask)

    steps = max(int((2 * half_width) / spacing), 1)
    for i in range(steps + 1):
        t = i / steps
        edge = 1 - (2 * t - 1) ** 2                 # 1 at center, 0 at the tips
        x = lerp(cx - half_width, cx + half_width, t) + np.random.normal(0, offset_jitter)
        yy = y + np.random.normal(0, offset_jitter * 0.4)
        rx = max(0.5, thickness * edge)
        ry = rx * 0.45                              # flat ellipse -> ground shadow
        val = int(255 * edge)                       # darker in the middle
        md.ellipse([x - rx, yy - ry, x + rx, yy + ry], fill=val)

    mask = mask.filter(ImageFilter.GaussianBlur(blur))
    mask = mask.point(lambda v: int(v * strength))  # keep it subtle, not pure black

    shadow = Image.new("RGB", img.size, color)
    img.paste(shadow, (0, 0), mask)                 # mask = how much color to blend in


# ----------------------------------------------------------------------------
# principle 5: the tighter a turn, the thicker the line right around it
# ----------------------------------------------------------------------------
# Drawing logic: when a pen changes direction fast, ink pools at the bend and
# the line reads heavier there -- corners of a box, the point of a leaf, the
# nose of a shoe. The sharper (tighter) the turn, the bigger that bulge, and it
# is LOCAL: the line thins back out as soon as the path straightens.
#
# We measure "tightness" as local curvature ~= (turn angle) / (segment length),
# which is just 1 / radius. A hairpin has a tiny radius -> big number -> thick.
# A gentle sweep has a huge radius -> ~0 -> stays thin.
def turn_angle(a, p, b):
    """Angle the path bends through at p: 0 = straight, up to pi = hairpin."""
    v1x, v1y = normalize(p[0] - a[0], p[1] - a[1])
    v2x, v2y = normalize(b[0] - p[0], b[1] - p[1])
    dot = max(-1.0, min(1.0, v1x * v2x + v1y * v2y))
    return float(np.arccos(dot))


def local_curvature(a, p, b):
    """Approx 1/radius at p. Big where the turn is tight, ~0 where straight."""
    seg = 0.5 * (np.hypot(p[0] - a[0], p[1] - a[1]) +
                 np.hypot(b[0] - p[0], b[1] - p[1]))
    return turn_angle(a, p, b) / seg if seg > 1e-6 else 0.0


def draw_curvature_shape(canvas, pts, base_w=1.3, curve_scale=55.0, cap=6.5,
                         curve_spread=4, color=(24, 21, 18), closed=True,
                         **line_kwargs):
    """Draw a path whose weight swells at tight turns and thins on straights.

    The swell is smeared over the bend (smooth_series) and added on the inside
    of the turn (stamp_weighted_path), so a sharp corner reads as a gradual
    thickening from the inner edge, not a round blob planted on the vertex.
    """
    n = len(pts)
    bonus = []
    for i in range(n):
        # open paths have no bend defined at the two endpoints
        if not closed and (i == 0 or i == n - 1):
            bonus.append(0.0)
            continue
        k = local_curvature(pts[(i - 1) % n], pts[i], pts[(i + 1) % n])
        bonus.append(min(cap, curve_scale * k))  # local, capped bulge

    bonus = smooth_series(bonus, radius=curve_spread, closed=closed)
    if closed:
        inward = contour_inward_normals(pts)
    else:
        inward = _smooth_vectors(
            [inner_bisector(pts[(i - 1) % n], pts[i], pts[(i + 1) % n])
             if 0 < i < n - 1 else (0.0, 0.0) for i in range(n)],
            radius=curve_spread, closed=False)
    weights = [base_w + b for b in bonus]
    colors = [color] * n
    stamp_weighted_path(canvas, pts, weights, colors, inward, base_w=base_w,
                        closed=closed, **line_kwargs)


# ----------------------------------------------------------------------------
# shape point generators
# ----------------------------------------------------------------------------
def subdivide(pts, per_edge=8, closed=True):
    """Add in-between points so a corner's bulge can taper along its edges."""
    n = len(pts)
    out = []
    segs = n if closed else n - 1
    for i in range(segs):
        a, b = pts[i], pts[(i + 1) % n]
        for k in range(per_edge):
            t = k / per_edge
            out.append((lerp(a[0], b[0], t), lerp(a[1], b[1], t)))
    if not closed:
        out.append(pts[-1])
    return out


def star_points(cx, cy, outer, inner, spikes=5):
    pts = []
    for i in range(spikes * 2):
        ang = i * np.pi / spikes - np.pi / 2
        r = outer if i % 2 == 0 else inner
        pts.append((cx + r * np.cos(ang), cy + r * np.sin(ang)))
    return pts


def spiral_points(cx, cy, r_start, turns=3.5, n=520, r_end=6):
    """A path that coils inward -> radius shrinks -> turns get tighter."""
    pts = []
    for i in range(n):
        t = i / (n - 1)
        r = lerp(r_start, r_end, t)
        ang = t * turns * 2 * np.pi
        pts.append((cx + r * np.cos(ang), cy + r * np.sin(ang)))
    return pts


def circle_points(cx, cy, r, n=72):
    return [(cx + r * np.cos(a), cy + r * np.sin(a))
            for a in np.linspace(0, 2 * np.pi, n, endpoint=False)]


# --- complicated test shapes (unit-ish, centered on origin, ~[-1, 1]) --------
def _xf(pts, cx, cy, s):
    """Scale a unit shape by s and move it to (cx, cy)."""
    return [(cx + x * s, cy + y * s) for (x, y) in pts]


def heart_unit(n=280):
    """Smooth curve + a concave dimple on top + a sharp cusp at the bottom."""
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    x = 16 * np.sin(t) ** 3
    y = 13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t)
    return list(zip(x / 17.0, -y / 17.0))          # flip y: cusp points down


def gear_unit(teeth=12, r_in=0.62, r_out=1.0):
    """Many small sharp teeth -> lots of tight turns close together."""
    verts = []
    slot = 2 * np.pi / teeth
    for k in range(teeth):
        a = k * slot
        for frac, r in [(0.00, r_in), (0.12, r_out),
                        (0.38, r_out), (0.50, r_in)]:
            ang = a + frac * slot
            verts.append((r * np.cos(ang), r * np.sin(ang)))
    return subdivide(verts, per_edge=4)


def leaf_unit(m=140, amp=0.62):
    """A lens/leaf with a sharp cusp at each end (finite-angle points)."""
    xs = np.linspace(-1, 1, m)
    upper = [(x, amp * (1 - x * x)) for x in xs]
    lower = [(x, -amp * (1 - x * x)) for x in xs[::-1]]
    return upper + lower


def blob_unit(n=320):
    """Organic outline whose curvature drifts high and low smoothly."""
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    r = 1 + 0.22 * np.sin(3 * t + 0.5) + 0.13 * np.sin(5 * t + 1.2) \
        + 0.09 * np.sin(7 * t)
    return list(zip(r * np.cos(t), r * np.sin(t)))


def flower_unit(petals=6, n=520):
    """Rounded petals separated by sharp concave notches (inside-out corners)."""
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    r = 0.55 + 0.45 * np.abs(np.sin(petals * t))
    return list(zip(r * np.cos(t), r * np.sin(t)))


def bolt_unit():
    """A lightning bolt: hard zig-zag with alternating convex/concave kinks."""
    verts = [(-0.10, -1.00), (0.38, -0.20), (0.08, -0.12), (0.58, 0.18),
             (-0.12, 1.00), (0.00, 0.22), (-0.38, 0.14), (-0.02, -0.30)]
    return subdivide(verts, per_edge=6)


def figure8_unit(n=400):
    """A lemniscate (infinity symbol): a single closed path that CROSSES itself."""
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    d = 1 + np.sin(t) ** 2
    return list(zip(np.cos(t) / d, np.sin(t) * np.cos(t) / d * 2))


def text_outlines(text, font_size=1.0, font_path=None):
    """Return each glyph contour of `text` as a closed point path (unit-ish).

    Uses matplotlib's TextPath to get real font outlines. Letters like 'o' or
    'e' come back as two contours (outer edge + inner hole); each is drawn as
    its own closed path, so counters get their own line weight too. Pass
    font_path to trace any .ttf/.ttc file on disk (e.g. a system serif font).
    """
    from matplotlib.textpath import TextPath
    from matplotlib.font_manager import FontProperties

    prop = (FontProperties(fname=font_path) if font_path
            else FontProperties(family="DejaVu Sans", weight="bold"))
    tp = TextPath((0, 0), text, size=font_size, prop=prop)
    polys = tp.to_polygons()
    if not polys:
        return []
    all_pts = np.vstack(polys)
    cx, cy = all_pts[:, 0].mean(), all_pts[:, 1].mean()
    scale = 1.0 / (all_pts[:, 0].max() - all_pts[:, 0].min())  # normalize width
    contours = []
    for poly in polys:
        pts = [((x - cx) * scale, -(y - cy) * scale) for x, y in poly]
        if len(pts) > 3:
            contours.append(pts[:-1])   # drop duplicate closing vertex
    return contours


# ----------------------------------------------------------------------------
# "line as the text": trace a font's SKELETON (center-line) and pen it as a
# single stroke, instead of outlining the glyph. Perfect for cursive / gothic.
# ----------------------------------------------------------------------------
def glyph_mask(text, font_path, px=210, pad=36):
    """Render `text` as a filled boolean bitmap using a real font."""
    from PIL import ImageFont
    font = ImageFont.truetype(font_path, px)
    probe = ImageDraw.Draw(Image.new("L", (8, 8)))
    l, t, r, b = probe.textbbox((0, 0), text, font=font)
    mask = Image.new("L", (r - l + 2 * pad, b - t + 2 * pad), 0)
    ImageDraw.Draw(mask).text((pad - l, pad - t), text, fill=255, font=font)
    return np.array(mask) > 128


def _neighbors(r, c, present):
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if (dr or dc) and (r + dr, c + dc) in present:
                yield (r + dr, c + dc)


def trace_skeleton(mask):
    """Reduce a filled glyph to 1px center-lines, then walk them into polylines.

    skeletonize() thins the letter to its medial axis (the path a pen would
    take). We then treat lit pixels as a graph: chains of degree-2 pixels are
    strokes, and pixels with degree 1 (stroke ends) or >=3 (junctions) are the
    nodes we start/stop at -- turning the pixel skeleton into ordered strokes.
    """
    from skimage.morphology import skeletonize
    skel = skeletonize(mask)
    present = {(int(r), int(c)) for r, c in zip(*np.where(skel))}
    deg = {p: sum(1 for _ in _neighbors(*p, present)) for p in present}
    seen = set()

    def walk(a, b):
        path = [a, b]
        seen.add(frozenset((a, b)))
        prev, cur = a, b
        while deg.get(cur) == 2:
            nxt = next((q for q in _neighbors(*cur, present)
                        if q != prev and frozenset((cur, q)) not in seen), None)
            if nxt is None:
                break
            seen.add(frozenset((cur, nxt)))
            path.append(nxt)
            prev, cur = cur, nxt
        return path

    paths = []
    for nd in [p for p in present if deg[p] != 2]:          # start at nodes
        for q in _neighbors(*nd, present):
            if frozenset((nd, q)) not in seen:
                paths.append(walk(nd, q))
    for p in present:                                        # leftover loops (o, 0)
        for q in _neighbors(*p, present):
            if frozenset((p, q)) not in seen:
                paths.append(walk(p, q))

    # terminals are free stroke ends (degree 1) -- where the pen lifts on/off,
    # as opposed to junctions (degree >= 3) where strokes should stay full width
    terminals = {p for p, d in deg.items() if d == 1}
    return paths, terminals


def _simplify(path, step=3):
    out = path[::step]
    if out[-1] != path[-1]:
        out.append(path[-1])
    return out


def draw_pen_stroke(canvas, pts, color=(32, 27, 23),
                    nib_angle=35.0, nib_max=4.6, nib_min=0.8,
                    taper_start=True, taper_end=True, taper_len=9,
                    offset_jitter=0.5, size_jitter=0.3, spacing=1.0):
    """Ink a center-line path as a BROAD-NIB calligraphic stroke.

    A flat calligraphy nib held at a fixed `nib_angle` leaves a wide mark when
    the pen travels across the nib edge and a hairline when it travels along it.
    So thickness = nib_min ... nib_max scaled by |sin(travel_angle - nib_angle)|:
    thick down-strokes, thin connecting up-strokes -- the essence of script.

    Free stroke ends taper to a point (taper_start / taper_end), mimicking the
    pen lifting on and off the page; ends that are junctions keep full width.
    """
    m = len(pts)
    if m < 2:
        return
    phi = np.radians(nib_angle)
    weights = []
    for i in range(m):
        a, b = pts[max(0, i - 1)], pts[min(m - 1, i + 1)]
        theta = np.arctan2(b[1] - a[1], b[0] - a[0])       # travel direction
        weights.append(nib_min + (nib_max - nib_min) * abs(np.sin(theta - phi)))

    # ease the weight to ~0 over the first/last `taper_len` points (pen lift)
    L = min(taper_len, m // 2)
    if L > 0:
        for i in range(m):
            f = 1.0
            if taper_start and i < L:
                f = min(f, i / L)
            if taper_end and i > m - 1 - L:
                f = min(f, (m - 1 - i) / L)
            weights[i] *= f * f * (3 - 2 * f)              # smoothstep to a point

    for i in range(m - 1):
        draw_textured_line(canvas, pts[i], pts[i + 1], weights[i], weights[i + 1],
                           color, color, offset_jitter=offset_jitter,
                           size_jitter=size_jitter, spacing=spacing)


def rect_points(cx, cy, hw, hh, per_side=18):
    corners = [(cx - hw, cy - hh), (cx + hw, cy - hh),
               (cx + hw, cy + hh), (cx - hw, cy + hh)]
    pts = []
    for i in range(4):
        a, b = corners[i], corners[(i + 1) % 4]
        for k in range(per_side):
            t = k / per_side
            pts.append((lerp(a[0], b[0], t), lerp(a[1], b[1], t)))
    return pts


# ----------------------------------------------------------------------------
# demo scene showing all four principles at once
# ----------------------------------------------------------------------------
def generate_scene(output_path="line_weight_demo.png"):
    W = H = 1100
    try:
        img = Image.open("old_paper_bg.png").convert("RGB").resize((W, H))
    except FileNotFoundError:
        img = Image.new("RGB", (W, H), (238, 231, 210))
    canvas = Canvas(img)

    LIGHT = (-1, -1)  # light comes from the top-left (screen y points down)

    # --- BACKGROUND object: thin, pale, flat -> reads as "far away" ---
    bg = rect_points(760, 340, 150, 150)
    draw_lit_shape(canvas, bg, LIGHT, min_w=0.9, max_w=1.4,
                   lit_color=(150, 145, 138), shadow_color=(120, 114, 104),
                   offset_jitter=0.7, spacing=1.4)

    hero_cx, hero_cy, hero_r = 430, 470, 210
    ground_y = hero_cy + hero_r

    # --- GROUND line (medium weight) ---
    draw_textured_line(canvas, (70, ground_y), (1030, ground_y),
                       2.2, 2.2, (60, 55, 50), (60, 55, 50),
                       offset_jitter=0.9, spacing=1.4)

    # --- HERO object: thick silhouette, strong light/shadow contrast ---
    hero = circle_points(hero_cx, hero_cy, hero_r)
    draw_lit_shape(canvas, hero, LIGHT, min_w=1.0, max_w=6.0,
                   lit_color=(120, 114, 104), shadow_color=(20, 17, 15),
                   offset_jitter=1.1, size_jitter=0.5, spacing=1.2)

    # --- INTERNAL DETAIL: thin, pale inner line (a fold / highlight edge) ---
    detail = circle_points(hero_cx - 55, hero_cy - 55, 95, n=60)
    draw_lit_shape(canvas, detail, LIGHT, min_w=0.7, max_w=1.3,
                   lit_color=(150, 145, 138), shadow_color=(110, 104, 96),
                   offset_jitter=0.6, spacing=1.5)

    canvas.to_pil().save(output_path, "PNG")
    print(f"Saved: {output_path}  ({W}x{H})")


def _paper(W, H):
    try:
        return Image.open("old_paper_bg.png").convert("RGB").resize((W, H))
    except FileNotFoundError:
        return Image.new("RGB", (W, H), (238, 231, 210))


# ----------------------------------------------------------------------------
# demo for principle 5: tight turns thicken the line right around them
# ----------------------------------------------------------------------------
def generate_curvature_demo(output_path="curvature_demo.png"):
    W, H = 1100, 620
    img = _paper(W, H)
    canvas = Canvas(img)

    # STAR: sharp points = tight turns -> tips swell; long straight edges stay thin
    star = subdivide(star_points(300, 310, outer=210, inner=85), per_edge=9)
    draw_curvature_shape(canvas, star, base_w=1.2, curve_scale=55, cap=7,
                         offset_jitter=1.0, size_jitter=0.4, spacing=1.2)

    # SPIRAL: radius shrinks toward the center, so each turn gets tighter and
    # the line grows heavier the closer it coils in.
    spiral = spiral_points(820, 310, r_start=230, turns=4.5)
    draw_curvature_shape(canvas, spiral, base_w=1.0, curve_scale=48, cap=7,
                         closed=False, offset_jitter=1.0, size_jitter=0.4,
                         spacing=1.2)

    canvas.to_pil().save(output_path, "PNG")
    print(f"Saved: {output_path}  ({W}x{H})")


# ----------------------------------------------------------------------------
# demo: lighting AND corner-bulge on the same shapes
# ----------------------------------------------------------------------------
def generate_combined_demo(output_path="combined_demo.png"):
    W, H = 1100, 620
    img = _paper(W, H)
    canvas = Canvas(img)
    LIGHT = (-1, -1)  # top-left

    # A star: corners bulge (curvature) AND the top-left points stay pale/thin
    # while the lower-right points go dark/thick (lighting) -- both at once.
    star = subdivide(star_points(300, 300, outer=200, inner=82), per_edge=9)
    draw_lit_shape(canvas, star, LIGHT, min_w=1.2, max_w=5.5,
                   curve_scale=55, curve_cap=5,
                   offset_jitter=1.0, size_jitter=0.4, spacing=1.2)

    # A square: same idea on simple 90-degree corners.
    box = rect_points(810, 300, 175, 175)
    draw_lit_shape(canvas, box, LIGHT, min_w=1.2, max_w=5.5,
                   curve_scale=55, curve_cap=5,
                   offset_jitter=1.0, size_jitter=0.4, spacing=1.2)

    canvas.to_pil().save(output_path, "PNG")
    print(f"Saved: {output_path}  ({W}x{H})")


# ----------------------------------------------------------------------------
# gallery: stress-test the weighting on complicated shapes
# ----------------------------------------------------------------------------
def generate_gallery(output_path="shapes_gallery.png"):
    cols, rows, cell = 3, 2, 400
    W, H = cols * cell, rows * cell
    img = _paper(W, H)
    canvas = Canvas(img)
    LIGHT = (-1, -1)

    shapes = [
        ("heart", heart_unit(),   1.30),
        ("gear", gear_unit(),     1.30),
        ("leaf", leaf_unit(),     1.45),
        ("blob", blob_unit(),     1.35),
        ("flower", flower_unit(), 1.35),
        ("bolt", bolt_unit(),     1.35),
    ]

    for idx, (name, unit, spread_r) in enumerate(shapes):
        cx = (idx % cols) * cell + cell // 2
        cy = (idx // cols) * cell + cell // 2
        pts = _xf(unit, cx, cy, cell * 0.34)
        draw_lit_shape(canvas, pts, LIGHT,
                       min_w=1.1, max_w=5.5,
                       curve_scale=42, curve_cap=4.5, curve_spread=6,
                       offset_jitter=0.7, size_jitter=0.4, spacing=1.15)
        canvas.text((cx - 18, cy + cell // 2 - 30), name, fill=(70, 62, 54))

    canvas.to_pil().save(output_path, "PNG")
    print(f"Saved: {output_path}  ({W}x{H})")


# ----------------------------------------------------------------------------
# self-intersecting path, text outlines, and an extreme-contrast stress test
# ----------------------------------------------------------------------------
def generate_figure8(output_path="figure8_demo.png"):
    W, H = 700, 500
    img = _paper(W, H)
    canvas = Canvas(img)
    pts = _xf(figure8_unit(), W // 2, H // 2, 260)
    draw_lit_shape(canvas, pts, (-1, -1), min_w=1.1, max_w=5.5,
                   curve_scale=42, curve_cap=4.5, curve_spread=6,
                   offset_jitter=0.7, size_jitter=0.4, spacing=1.15)
    canvas.to_pil().save(output_path, "PNG")
    print(f"Saved: {output_path}  ({W}x{H})")


def generate_text(text="SKETCH", output_path="text_demo.png"):
    contours = text_outlines(text)
    W, H = 1200, 360
    img = _paper(W, H)
    canvas = Canvas(img)
    for c in contours:
        pts = _xf(c, W // 2, H // 2, W * 0.82)
        draw_lit_shape(canvas, pts, (-1, -1), min_w=1.0, max_w=4.5,
                       curve_scale=30, curve_cap=3.5, curve_spread=5,
                       offset_jitter=0.6, size_jitter=0.35, spacing=1.1)
    canvas.to_pil().save(output_path, "PNG")
    print(f"Saved: {output_path}  ({W}x{H})")


def generate_contrast_ramp(output_path="contrast_ramp.png"):
    """Same star, pushed from subtle to extreme weight to find the limit."""
    cols, cell = 4, 320
    W, H = cols * cell, cell
    img = _paper(W, H)
    canvas = Canvas(img)
    settings = [("subtle", 3.0, 20, 2.0),
                ("normal", 5.5, 42, 4.5),
                ("strong", 9.0, 70, 8.0),
                ("extreme", 15.0, 120, 14.0)]
    for idx, (name, max_w, cscale, ccap) in enumerate(settings):
        cx = idx * cell + cell // 2
        cy = cell // 2 - 10
        star = subdivide(star_points(0, 0, outer=1.0, inner=0.42), per_edge=9)
        pts = _xf(star, cx, cy, cell * 0.30)
        draw_lit_shape(canvas, pts, (-1, -1), min_w=1.0, max_w=max_w,
                       curve_scale=cscale, curve_cap=ccap, curve_spread=6,
                       offset_jitter=0.7, size_jitter=0.4, spacing=1.1)
        canvas.text((cx - 20, cell - 26), name, fill=(70, 62, 54))
    canvas.to_pil().save(output_path, "PNG")
    print(f"Saved: {output_path}  ({W}x{H})")


def generate_font_showcase(word="Type", output_path="font_showcase.png"):
    """Trace the same word in fonts with very different serif styles."""
    S = "/System/Library/Fonts/"
    X = S + "Supplemental/"
    fonts = [
        ("Helvetica  -  sans serif (no serifs)", S + "Helvetica.ttc"),
        ("Times New Roman  -  old-style serif", X + "Times New Roman.ttf"),
        ("Baskerville  -  transitional serif", X + "Baskerville.ttc"),
        ("Didot  -  modern high-contrast serif", X + "Didot.ttc"),
        ("Rockwell  -  slab serif", X + "Rockwell.ttc"),
        ("American Typewriter  -  slab / typewriter", X + "AmericanTypewriter.ttc"),
    ]
    from PIL import ImageFont
    try:
        label_font = ImageFont.truetype(S + "Helvetica.ttc", 22)
    except OSError:
        label_font = None

    row_h = 250
    W, H = 1200, row_h * len(fonts)
    img = _paper(W, H)
    canvas = Canvas(img)

    for i, (label, path) in enumerate(fonts):
        cy = i * row_h + row_h // 2 + 20
        contours = text_outlines(word, font_path=path)
        for c in contours:
            pts = _xf(c, 640, cy, 430)
            draw_lit_shape(canvas, pts, (-1, -1), min_w=0.8, max_w=3.2,
                           curve_scale=22, curve_cap=3.0, curve_spread=5,
                           offset_jitter=0.5, size_jitter=0.3, spacing=1.05)
        canvas.text((36, i * row_h + 26), label, fill=(70, 62, 54), font=label_font)

    canvas.to_pil().save(output_path, "PNG")
    print(f"Saved: {output_path}  ({W}x{H})")


def generate_script_showcase(word="Quill", output_path="script_showcase.png"):
    """Draw the word as a single pen line (center-line) in script/gothic fonts."""
    from PIL import ImageFont
    X = "/System/Library/Fonts/Supplemental/"
    fonts = [
        ("Snell Roundhand  -  formal cursive", X + "SnellRoundhand.ttc"),
        ("Zapfino  -  calligraphic script", X + "Zapfino.ttf"),
        ("Trattatello  -  medieval hand", X + "Trattatello.ttf"),
        ("Luminari  -  medieval / fantasy", X + "Luminari.ttf"),
        ("Bradley Hand  -  casual handwriting", X + "Bradley Hand Bold.ttf"),
    ]

    target_h, max_w_allowed = 150, 900
    rows = []
    for label, path in fonts:
        mask = glyph_mask(word, path, px=210)
        paths, terminals = trace_skeleton(mask)
        strokes = [(_simplify(p), p[0] in terminals, p[-1] in terminals)
                   for p in paths if len(p) >= 8]
        H, Wm = mask.shape
        scale = min(target_h / H, max_w_allowed / Wm)
        rows.append((label, strokes, Wm * scale, H * scale, scale))

    row_h = target_h + 95
    W = int(max(r[2] for r in rows) + 130)
    img = _paper(W, row_h * len(rows))
    canvas = Canvas(img)
    try:
        label_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 22)
    except OSError:
        label_font = None

    for i, (label, strokes, ws, hs, scale) in enumerate(rows):
        x_off = (W - ws) / 2
        y_off = i * row_h + 52
        for st, tap0, tap1 in strokes:
            pts = [(x_off + c * scale, y_off + r * scale) for (r, c) in st]
            draw_pen_stroke(canvas, pts, taper_start=tap0, taper_end=tap1)
        canvas.text((30, i * row_h + 18), label, fill=(70, 62, 54), font=label_font)

    canvas.to_pil().save(output_path, "PNG")
    print(f"Saved: {output_path}  ({W}x{row_h * len(rows)})")


if __name__ == "__main__":
    generate_scene()
    generate_curvature_demo()
    generate_combined_demo()
    generate_gallery()
    generate_figure8()
    generate_text()
    generate_contrast_ramp()
    generate_font_showcase()
    generate_script_showcase()
