"""
Road Data + Geometry Generation (no rendering, no input handling here).

Design notes:
- Curvature is stored as a single scalar per road: the perpendicular offset
  (in pixels) of a quadratic Bezier control point from the midpoint of the
  straight line between the two endpoint nodes.
- computeRoadGeometry() is the one place that turns
  (start_pos, end_pos, curvature) into sampled points. Both the live preview
  and committed roads call this same function, so they always look identical
  and any future intersection-detection code can rely on it too.
"""

import math
from dataclasses import dataclass, field

from road_style import get_road_profile


@dataclass
class Node:
    id: int
    x: float
    y: float
    # Flexible node system: 'type' distinguishes road nodes, zone anchors,
    # future traffic lights/stop signs/etc. 'data' holds per-type extras
    # (e.g. {"state": "red"} for a traffic light) without new subclasses.
    type: str = "road_node"
    data: dict = field(default_factory=dict)

    @property
    def pos(self):
        return (self.x, self.y)


# How many pixels represent one foot. Centerline/curvature math is unchanged
# (still pixel-based), this constant only converts road WIDTH (feet) into
# pixels for edge-offset calculations.
PIXELS_PER_FOOT = 1.0


@dataclass
class Road:
    id: int
    start_node_id: int
    end_node_id: int
    # 2D offset of the bezier control point from the start->end midpoint.
    # Free-form (not restricted to perpendicular), so dragging the control
    # point can bend the curve in any direction.
    curve_offset: tuple = (0.0, 0.0)
    lane_count: int = 1
    width: float = 12.0      # road width in FEET (default: two-lane residential)
    is_preview: bool = False
    # Future-ready free-form extras (e.g. traffic light timing overrides).
    data: dict = field(default_factory=dict)
    # Populated by compute_road_geometry(); not set directly.
    left_edge_points: list = field(default_factory=list)
    right_edge_points: list = field(default_factory=list)
    road_polygon: list = field(default_factory=list)


@dataclass
class Zone:
    """An independent polygon, separate from the node/road graph."""
    id: int
    type: str  # "Residential" | "Commercial" | "Industrial"
    boundary_points: list = field(default_factory=list)  # [(x, y) ft, ...]
    data: dict = field(default_factory=dict)


def _perpendicular(dx, dy):
    length = math.hypot(dx, dy)
    if length == 0:
        return (0.0, 0.0)
    return (-dy / length, dx / length)


def compute_control_point(start_pos, end_pos, curve_offset):
    """Return the single Bezier control point for a road: the start->end
    midpoint plus a free-form 2D offset."""
    sx, sy = start_pos
    ex, ey = end_pos
    mx, my = (sx + ex) / 2.0, (sy + ey) / 2.0
    ox, oy = curve_offset
    return (mx + ox, my + oy)


def sample_quadratic_bezier(p0, p1, p2, sample_count=24):
    """Evaluate a quadratic bezier at sample_count+1 evenly spaced t values."""
    points = []
    for i in range(sample_count + 1):
        t = i / sample_count
        mt = 1 - t
        x = mt * mt * p0[0] + 2 * mt * t * p1[0] + t * t * p2[0]
        y = mt * mt * p0[1] + 2 * mt * t * p1[1] + t * t * p2[1]
        points.append((x, y))
    return points


def sample_cubic_bezier(p0, p1, p2, p3, sample_count=24):
    """Evaluate a cubic bezier at sample_count+1 evenly spaced t values.
    With control points p1/p2 placed along the endpoint tangents, the curve
    leaves p0 and arrives at p3 tangent-continuous with those directions."""
    points = []
    for i in range(sample_count + 1):
        t = i / sample_count
        mt = 1 - t
        a, b, c, d = mt * mt * mt, 3 * mt * mt * t, 3 * mt * t * t, t * t * t
        x = a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0]
        y = a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]
        points.append((x, y))
    return points


def _normalize(dx, dy):
    length = math.hypot(dx, dy)
    if length == 0:
        return (0.0, 0.0)
    return (dx / length, dy / length)


def compute_tangents(sampled_points):
    """
    For each sampled centerline point, compute a normalized tangent
    (direction of travel) using a central difference of neighboring points.
    Endpoints fall back to a one-sided difference.
    """
    n = len(sampled_points)
    tangents = []
    for i in range(n):
        if i == 0:
            ax, ay = sampled_points[0]
            bx, by = sampled_points[1]
        elif i == n - 1:
            ax, ay = sampled_points[-2]
            bx, by = sampled_points[-1]
        else:
            ax, ay = sampled_points[i - 1]
            bx, by = sampled_points[i + 1]
        tangents.append(_normalize(bx - ax, by - ay))
    return tangents


def compute_road_edges(sampled_points, width_ft, pixels_per_foot=PIXELS_PER_FOOT):
    """
    From centerline sample points + a width (feet), compute the left and
    right edge point lists. Each edge point is offset from the centerline
    by half the road width, along the perpendicular of the local tangent.

    Returns (left_edge_points, right_edge_points), both in the same order
    as sampled_points (start -> end).
    """
    half_width_px = (width_ft * pixels_per_foot) / 2.0
    tangents = compute_tangents(sampled_points)

    left_edge_points = []
    right_edge_points = []
    for (px, py), (tx, ty) in zip(sampled_points, tangents):
        # Perpendicular to tangent: rotate 90 degrees.
        nx, ny = -ty, tx
        left_edge_points.append((px + nx * half_width_px, py + ny * half_width_px))
        right_edge_points.append((px - nx * half_width_px, py - ny * half_width_px))

    return left_edge_points, right_edge_points


def compute_road_polygon(left_edge_points, right_edge_points):
    """Closed outline of the road surface: left edge forward, then right edge
    reversed (the reversal avoids a self-intersecting bowtie)."""
    return left_edge_points + list(reversed(right_edge_points))


def compute_road_geometry(start_pos, end_pos, curve_offset, width_ft=12.0,
                           sample_count=24, pixels_per_foot=PIXELS_PER_FOOT):
    """
    Single shared geometry path for preview and committed roads.

    Returns dict with:
      - control_point: the bezier control point
      - sampled_points: list of (x, y) along the centerline
      - left_edge_points: list of (x, y) along the left road edge
      - right_edge_points: list of (x, y) along the right road edge
      - road_polygon: closed polygon outlining the road surface
    """
    control_point = compute_control_point(start_pos, end_pos, curve_offset)
    sampled_points = sample_quadratic_bezier(start_pos, control_point, end_pos, sample_count)
    left_edge_points, right_edge_points = compute_road_edges(
        sampled_points, width_ft, pixels_per_foot
    )
    road_polygon = compute_road_polygon(left_edge_points, right_edge_points)
    return {
        "control_point": control_point,
        "sampled_points": sampled_points,
        "left_edge_points": left_edge_points,
        "right_edge_points": right_edge_points,
        "road_polygon": road_polygon,
    }


# ----------------------------------------------------------------------
# Junction / continuation surface helpers (moved verbatim from
# road_editor.py, per REFACTOR_PLAN.md step 2: geometry belongs here).
# ----------------------------------------------------------------------

def _trim_polyline(points, start_trim, end_trim):
    """Shorten a polyline by `start_trim`/`end_trim` feet (arc length) from
    each end, inserting an interpolated point at the exact trim distance.
    Returns the original points unchanged if the line is too short to trim."""
    pts = list(points)
    if start_trim > 0:
        remaining = start_trim
        while len(pts) >= 2:
            seg = math.hypot(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
            if seg > remaining:
                t = remaining / seg
                pts[0] = (pts[0][0] + (pts[1][0] - pts[0][0]) * t,
                          pts[0][1] + (pts[1][1] - pts[0][1]) * t)
                break
            remaining -= seg
            pts.pop(0)
    if end_trim > 0:
        remaining = end_trim
        while len(pts) >= 2:
            seg = math.hypot(pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1])
            if seg > remaining:
                t = remaining / seg
                pts[-1] = (pts[-1][0] + (pts[-2][0] - pts[-1][0]) * t,
                           pts[-1][1] + (pts[-2][1] - pts[-1][1]) * t)
                break
            remaining -= seg
            pts.pop()
    if len(pts) < 2:
        return points
    return pts


def _normalize2(dx, dy):
    length = math.hypot(dx, dy)
    if length == 0:
        return (0.0, 0.0)
    return (dx / length, dy / length)


# Junction-corner bow strength: peak control-point offset as a fraction of
# the half-chord, reached at the angular extremes (a fully closed convex
# wedge and a fully open reflex gap). Larger = deeper scallops / taller flares.
FILLET_BOW = 0.55


def _fillet_points(point_a, point_b, node_pos, sector, samples=6):
    """Corner edge between two adjacent road edge points at a junction. The
    curvature is set by `sector`: the corner's angular span in radians (the
    CCW gap between the two roads' outward directions, 0..2*pi), which is what
    distinguishes a convex corner from a reflex one (the dot product between
    tangents cannot: a 120 deg convex corner and a 240 deg reflex corner
    have the same tangent angle):

        sector < 180 deg (convex, incl. right angles): concave, bows INTO the
            junction; deeper as the corner sharpens, fading to flat at 180.
        sector = 180 deg (straight-through): flat.
        sector > 180 deg (reflex gap): convex, bows OUTWARD away from the
            node, growing as the gap opens past 180.

    One linear law does all of it: the perpendicular bow is half_chord *
    FILLET_BOW * (pi - sector)/pi, positive (inward) for convex, negative
    (outward) for reflex, zero at 180 deg. A symmetric quadratic offset
    perpendicular to the chord, so it can never self-intersect. `node_pos`
    only fixes which perpendicular is "inward". Returns interior points only
    (endpoints excluded)."""
    chord = (point_b[0] - point_a[0], point_b[1] - point_a[1])
    clen = math.hypot(chord[0], chord[1])
    if clen < 1e-9:
        return []

    # (pi - sector)/pi: +1 fully-closed convex .. 0 at 180 .. -1 fully-open reflex.
    bow_scale = (math.pi - sector) / math.pi
    if abs(bow_scale) < 1e-3:
        return []                                        # straight-through -> flat

    # Unit perpendicular to the chord, oriented toward the node ("inward").
    perp = (-chord[1] / clen, chord[0] / clen)
    to_node = (node_pos[0] - point_a[0], node_pos[1] - point_a[1])
    if perp[0] * to_node[0] + perp[1] * to_node[1] < 0:
        perp = (-perp[0], -perp[1])

    bow = (clen * 0.5) * FILLET_BOW * bow_scale          # >0 inward, <0 outward
    mx, my = (point_a[0] + point_b[0]) * 0.5, (point_a[1] + point_b[1]) * 0.5
    ctrl = (mx + perp[0] * bow, my + perp[1] * bow)

    pts = []
    for i in range(1, samples):
        t = i / samples
        mt = 1 - t
        x = mt * mt * point_a[0] + 2 * mt * t * ctrl[0] + t * t * point_b[0]
        y = mt * mt * point_a[1] + 2 * mt * t * ctrl[1] + t * t * point_b[1]
        pts.append((x, y))
    return pts


def _line_intersection(p1, d1, p2, d2):
    """Intersection of line (p1 + t*d1) and line (p2 + s*d2), or None if
    parallel/degenerate."""
    denom = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(denom) < 1e-9:
        return None
    t = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / denom
    return (p1[0] + d1[0] * t, p1[1] + d1[1] * t)


def _segment_intersection(a1, a2, b1, b2):
    """Return the intersection point of segments a1->a2 and b1->b2, or None
    if they don't cross (parallel, or crossing point outside either
    segment)."""
    d1 = (a2[0] - a1[0], a2[1] - a1[1])
    d2 = (b2[0] - b1[0], b2[1] - b1[1])
    denom = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(denom) < 1e-9:
        return None
    t = ((b1[0] - a1[0]) * d2[1] - (b1[1] - a1[1]) * d2[0]) / denom
    s = ((b1[0] - a1[0]) * d1[1] - (b1[1] - a1[1]) * d1[0]) / denom
    if -1e-6 <= t <= 1 + 1e-6 and -1e-6 <= s <= 1 + 1e-6:
        return (a1[0] + d1[0] * t, a1[1] + d1[1] * t)
    return None


# ----------------------------------------------------------------------
# Watchdog: read-only geometry diagnostics. Detects suspicious geometry
# (crossings without nodes, trims that overflow a road's length, degenerate
# profile widths) and reports it for visualization; it does NOT modify or
# fix anything.
# ----------------------------------------------------------------------

def detect_geometry_issues(network):
    """Return a list of {"type", "pos", "message"} issue dicts describing
    geometry the renderer can highlight, e.g.:
      - "crossing_no_node": two roads' centerlines cross at a point that
        isn't a shared graph node.
      - "trim_overflow": a road's intersection trims consume its entire
        length, collapsing its drawable geometry.
      - "degenerate_width": a road's profile produces a zero/negative
        left_width()/right_width() or lane_width.
    """
    issues = []
    roads = [r for r in network.roads.values() if not r.is_preview]

    # 1. Centerline crossings between roads that share no node.
    for i in range(len(roads)):
        for j in range(i + 1, len(roads)):
            r1, r2 = roads[i], roads[j]
            shared = {r1.start_node_id, r1.end_node_id} & {r2.start_node_id, r2.end_node_id}
            if shared:
                continue
            pts1 = network.geometry_for_road(r1)["sampled_points"]
            pts2 = network.geometry_for_road(r2)["sampled_points"]
            found = False
            for k in range(len(pts1) - 1):
                if found:
                    break
                for l in range(len(pts2) - 1):
                    pt = _segment_intersection(pts1[k], pts1[k + 1], pts2[l], pts2[l + 1])
                    if pt is not None:
                        issues.append({
                            "type": "crossing_no_node",
                            "pos": pt,
                            "message": f"Roads {r1.id} and {r2.id} cross without a shared node",
                        })
                        found = True
                        break

    # 2/3. Per-road trim and profile sanity.
    for road in roads:
        geometry = network.geometry_for_road(road)
        pts = geometry["sampled_points"]
        start_trim = network.road_trim_at_node(road, road.start_node_id)
        end_trim = network.road_trim_at_node(road, road.end_node_id)
        if start_trim > 0 or end_trim > 0:
            trimmed = _trim_polyline(pts, start_trim, end_trim)
            if len(trimmed) < 2:
                mid = pts[len(pts) // 2]
                issues.append({
                    "type": "trim_overflow",
                    "pos": mid,
                    "message": f"Road {road.id}: intersection trims ({start_trim:.1f}+{end_trim:.1f}ft) "
                               f"exceed road length -- geometry collapsed",
                })

        profile = get_road_profile(road)
        if profile.left_width() <= 0 or profile.right_width() <= 0 or profile.lane_width <= 0:
            mid = pts[len(pts) // 2]
            issues.append({
                "type": "degenerate_width",
                "pos": mid,
                "message": f"Road {road.id}: degenerate profile width "
                           f"(left={profile.left_width():.2f}, right={profile.right_width():.2f}, "
                           f"lane_width={profile.lane_width:.2f})",
            })

    return issues


def _build_junction_polygon(entries, node_pos):
    """Merge each connected road's near-end edge pair into one junction
    polygon, ordered by each road's outward tangent angle (NOT by raw point
    angle; with >=4 roads a road's own left/right edge points can be on
    opposite sides of the node, so sorting points directly produces a
    self-intersecting polygon).

    Each entry is one road: {"left", "right", "outward", "color"}, where
    "left"/"right" are that road's near-end edge points using a consistent
    convention (perpendicular to the OUTWARD tangent, rotated +90 = left).

    Going counter-clockwise by outward-tangent angle, road i contributes its
    own chord [right_i, left_i], then fills the gap to the next road's
    right_(i+1) point with a Bezier fillet whose shape is set by that corner's
    angular span (the CCW gap to the next road): convex corners (< 180 deg)
    bow inward, the straight-through (180 deg) is flat, and reflex gaps
    (> 180 deg) bow outward (see _fillet_points).

    Returns (polygon_points, edge_lines) where edge_lines is
    [(curve_points, color), ...] for the connectors only."""
    ordered = sorted(entries, key=lambda e: math.atan2(e["outward"][1], e["outward"][0]))
    polygon = []
    edge_lines = []
    n = len(ordered)
    for i in range(n):
        a = ordered[i]
        b = ordered[(i + 1) % n]
        polygon.append(a["right"])
        polygon.append(a["left"])

        # The road geometry feeding these entries has already been trimmed
        # back (in road_trim_at_node) by an extra curb-return radius beyond
        # the bare carriageway/shoulder edge, so a["left"] and b["right"]
        # are themselves the curve's start/end points, with no further
        # pullback is needed. A tangent-continuous Bezier fillet bridges
        # them directly, replacing the straight segment entirely (the
        # straight boundary geometry simply doesn't extend past these
        # points anymore).
        # Corner's angular span: the CCW gap from road a's outward direction
        # to road b's (0..2pi). < pi = convex corner, > pi = reflex gap --
        # the sign that flips the fillet from concave to outward.
        ang_a = math.atan2(a["outward"][1], a["outward"][0])
        ang_b = math.atan2(b["outward"][1], b["outward"][0])
        sector = (ang_b - ang_a) % (2 * math.pi)
        fillet = _fillet_points(a["left"], b["right"], node_pos, sector)
        polygon.extend(fillet)

        edge_lines.append(([a["left"]] + fillet + [b["right"]], a["color"]))
    return polygon, edge_lines


def _is_fold(entries):
    """True for a 2-road node whose arms are < 90 deg apart: the two outward
    tangents point the same general way, so it is a sharp fold rather than a
    gentle continuation."""
    if len(entries) != 2:
        return False
    a, b = entries[0]["outward"], entries[1]["outward"]
    return a[0] * b[0] + a[1] * b[1] > 0.0


def _is_width_taper(entries):
    """True for a 2-road CONTINUATION (>= 90 deg bend) whose two mouths differ
    in width, the case that wants an S-curve width-transition surface. Sharp
    folds are excluded: they take the rounded continuation band even when the
    widths differ, since an S-curve can't follow the tight bend. Equal-width
    bends and 3+ way junctions are False too."""
    if len(entries) != 2 or _is_fold(entries):
        return False
    def mw(e):
        return math.hypot(e["left"][0] - e["right"][0], e["left"][1] - e["right"][1])
    return abs(mw(entries[0]) - mw(entries[1])) > 1e-3


def _build_continuation_polygon(entries, samples=8):
    """Asphalt band through an equal-width 2-road continuation/bend. Instead
    of an intersection's concave corner cuts, the two roads' mouths are joined
    edge-to-edge by tangent-continuous cubics (the SAME curves used for the
    lane-line connectors), so the surface follows the bend smoothly with no
    notch or overlap, and the painted edge lines sit exactly on the asphalt
    edge. entries: two {left, right, outward, color}. Returns
    (polygon, edge_lines)."""
    a, b = entries

    def edge_curve(p, out_p, q, out_q):
        gap = math.hypot(q[0] - p[0], q[1] - p[1])
        if gap < 1e-9:
            return [p, q]
        handle = 0.4 * gap
        c1 = (p[0] - out_p[0] * handle, p[1] - out_p[1] * handle)   # toward node
        c2 = (q[0] - out_q[0] * handle, q[1] - out_q[1] * handle)   # tangent to q's road
        return sample_cubic_bezier(p, c1, c2, q, samples)

    al, ar = a["left"], a["right"]
    bl, br = b["left"], b["right"]
    # Pair each A edge to the B edge on the same physical side (the non-
    # crossing pairing = smaller total endpoint distance).
    straight = (math.hypot(al[0] - bl[0], al[1] - bl[1])
                + math.hypot(ar[0] - br[0], ar[1] - br[1]))
    crossed = (math.hypot(al[0] - br[0], al[1] - br[1])
               + math.hypot(ar[0] - bl[0], ar[1] - bl[1]))
    b_for_left, b_for_right = (bl, br) if straight <= crossed else (br, bl)

    side1 = edge_curve(al, a["outward"], b_for_left, b["outward"])
    side2 = edge_curve(b_for_right, b["outward"], ar, a["outward"])
    polygon = [ar, al] + side1 + [b_for_left, b_for_right] + side2
    edge_lines = [([al] + side1 + [b_for_left], a["color"]),
                  ([b_for_right] + side2 + [ar], a["color"])]
    return polygon, edge_lines


def _taper_curve(point_a, tangent_a, point_b, tangent_b, samples=8):
    """Cubic S-curve edge for a width transition: leaves `point_a` heading
    back toward the node (against `tangent_a`, which points outward into
    its road) and arrives at `point_b` moving outward along `tangent_b`,
    so each end is tangent-continuous with its road's straight edge.
    Unlike a junction corner fillet this curve is SUPPOSED to cross its
    chord (an S-shape has an inflection), so no faces-in constraint
    applies. The no-loop guarantee is the same as _fillet_points': any
    backward chord component is stripped from a control displacement, so
    the curve advances monotonically along its chord and can never double
    back into a loop, even across a sharply bent continuation node.
    Returns interior points only (excludes the endpoints)."""
    chord = (point_b[0] - point_a[0], point_b[1] - point_a[1])
    clen = math.hypot(chord[0], chord[1])
    if clen < 1e-9:
        return []
    ux, uy = chord[0] / clen, chord[1] / clen
    d = clen / 3.0

    disp_a = (-tangent_a[0] * d, -tangent_a[1] * d)   # depart toward the node
    disp_b = (-tangent_b[0] * d, -tangent_b[1] * d)   # arrive along +tangent_b
    back_a = disp_a[0] * ux + disp_a[1] * uy
    if back_a < 0:
        disp_a = (disp_a[0] - ux * back_a, disp_a[1] - uy * back_a)
    back_b = disp_b[0] * ux + disp_b[1] * uy
    if back_b > 0:
        disp_b = (disp_b[0] - ux * back_b, disp_b[1] - uy * back_b)

    c1 = (point_a[0] + disp_a[0], point_a[1] + disp_a[1])
    c2 = (point_b[0] + disp_b[0], point_b[1] + disp_b[1])
    pts = []
    for i in range(1, samples):
        t = i / samples
        mt = 1 - t
        x = (mt ** 3) * point_a[0] + 3 * (mt ** 2) * t * c1[0] + 3 * mt * (t ** 2) * c2[0] + (t ** 3) * point_b[0]
        y = (mt ** 3) * point_a[1] + 3 * (mt ** 2) * t * c1[1] + 3 * mt * (t ** 2) * c2[1] + (t ** 3) * point_b[1]
        pts.append((x, y))
    return pts


def _build_taper_polygon(entries):
    """Width-transition surface for a continuation node joining exactly two
    roads of different total widths. The wider road's mouth sits a token
    setback from the node at its full width; the narrower road's mouth sits
    a taper length down its own corridor, so the whole transition lives
    on the narrower road's side and the wider road never necks down before
    the node. Each long edge is a tangent-continuous S-curve between the
    corresponding mouth corners (see _taper_curve).

    Same contract as _build_junction_polygon: entries are the two roads'
    {"left", "right", "outward", "color"} mouths; returns
    (polygon_points, edge_lines)."""
    a, b = entries
    polygon = []
    edge_lines = []
    for p, q in ((a, b), (b, a)):
        polygon.append(p["right"])
        polygon.append(p["left"])
        curve = _taper_curve(p["left"], p["outward"], q["right"], q["outward"])
        polygon.extend(curve)
        edge_lines.append(([p["left"]] + curve + [q["right"]], p["color"]))
    return polygon, edge_lines


# ----------------------------------------------------------------------
# Node-surface assembly: the pure-geometry pass that turns a network's
# trimmed road mouths into junction / continuation / width-taper surface
# polygons (extracted from the renderer so the editor and the web API
# tessellate identically).
# ----------------------------------------------------------------------

def build_node_surfaces(network,
                        junction_builder=None,
                        taper_builder=None,
                        continuation_builder=None):
    """Assemble every node's surface geometry, exactly as the editor
    renderer draws it:

      - each non-preview road with a node trim gets its centerline trimmed
        back and contributes a mouth entry {left, right, outward, color,
        shoulder_width, outer_color} to each trimmed end's node;
      - each node with >= 2 entries gets a surface polygon: a width-taper
        (S-curve) for 2-road continuations of differing widths, a smooth
        band for equal-width bends, or a corner-fillet junction polygon
        for 3+ ways -- plus a full-profile-width outer (sidewalk/shoulder)
        polygon when any entry has a shoulder;
      - nodes with exactly one road get a circular dead-end cap.

    The three `*_builder` hooks default to this module's builders; the
    renderer passes its own module globals so diagnostic monkey-patching
    (check_fillet_direction.py / check_taper.py) keeps intercepting.

    Returns {"trimmed_points": {road_id: [pts]},
             "nodes": [{"node_id", "kind", "polygon", "edge_lines",
                        "mouth_width", "outer_polygon", "outer_edge_lines",
                        "outer_color"}],
             "caps": [{"node_id", "pos", "radius"}]}.
    """
    from road_style import (EDGE_LINE_PRESETS, SHOULDER_NONE, SHOULDER_COLORS,
                            get_road_profile as _profile)
    junction_builder = junction_builder or _build_junction_polygon
    taper_builder = taper_builder or _build_taper_polygon
    continuation_builder = continuation_builder or _build_continuation_polygon

    junction_edge_points = {}
    trimmed_points = {}

    def _add_entry(node_id, trim_point, outward, left_width, right_width,
                   color, shoulder_width, outer_color):
        # left/right via a consistent convention based on the OUTWARD tangent
        # (away from the node, back into the road): rotate +90 deg for
        # "left". left_width/right_width are each side's own offset from the
        # (immutable) centerline, never a shared half-width, so an
        # asymmetric profile produces an asymmetric junction edge.
        perp = (-outward[1], outward[0])
        left = (trim_point[0] + perp[0] * left_width,
                trim_point[1] + perp[1] * left_width)
        right = (trim_point[0] - perp[0] * right_width,
                 trim_point[1] - perp[1] * right_width)
        junction_edge_points.setdefault(node_id, []).append(
            {"left": left, "right": right, "outward": outward, "color": color,
             "shoulder_width": shoulder_width, "outer_color": outer_color})

    for road in network.roads.values():
        if road.is_preview:
            continue
        start_trim = network.road_trim_at_node(road, road.start_node_id)
        end_trim = network.road_trim_at_node(road, road.end_node_id)
        if not (start_trim > 0 or end_trim > 0):
            continue
        geometry = network.geometry_for_road(road)
        pts = _trim_polyline(geometry["sampled_points"], start_trim, end_trim)
        trimmed_points[road.id] = pts

        profile = _profile(road)
        edge_color = EDGE_LINE_PRESETS.get(
            profile.edge_line_style, EDGE_LINE_PRESETS["none"]).color
        has_outer = (profile.shoulder_type != SHOULDER_NONE
                     and profile.shoulder_width > 0)
        shoulder_width = profile.shoulder_width if has_outer else 0.0
        outer_color = SHOULDER_COLORS.get(profile.shoulder_type, (120, 120, 120))

        if start_trim > 0 and len(pts) >= 2:
            outward = _normalize2(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
            _add_entry(road.start_node_id, pts[0], outward,
                       profile.left_width(), profile.right_width(),
                       edge_color, shoulder_width, outer_color)
        if end_trim > 0 and len(pts) >= 2:
            # At the end node the "outward" tangent points back toward the
            # start, which flips the perpendicular, so swap left/right widths
            # so each entry point keeps its correct physical-side width.
            outward = _normalize2(pts[-2][0] - pts[-1][0], pts[-2][1] - pts[-1][1])
            _add_entry(road.end_node_id, pts[-1], outward,
                       profile.right_width(), profile.left_width(),
                       edge_color, shoulder_width, outer_color)

    nodes_out = []
    for node_id, entries in junction_edge_points.items():
        if len(entries) < 2:
            continue

        # Outer (sidewalk/shoulder) surface first, mirroring the renderer's
        # draw order (outer under, asphalt on top). Kind selection always
        # comes from the INNER entries.
        outer_polygon = None
        outer_edge_lines = None
        outer_color = None
        if any(e.get("shoulder_width", 0.0) > 0 for e in entries):
            outer_entries = []
            for e in entries:
                sw = e.get("shoulder_width", 0.0)
                perp = (-e["outward"][1], e["outward"][0])
                outer_entries.append({
                    "left": (e["left"][0] + perp[0] * sw,
                             e["left"][1] + perp[1] * sw),
                    "right": (e["right"][0] - perp[0] * sw,
                              e["right"][1] - perp[1] * sw),
                    "outward": e["outward"],
                    "color": e["outer_color"] if sw > 0 else e["color"],
                })
            if _is_width_taper(entries):
                outer_polygon, outer_edge_lines = taper_builder(outer_entries)
            elif len(entries) == 2:
                outer_polygon, outer_edge_lines = continuation_builder(outer_entries)
            else:
                outer_polygon, outer_edge_lines = junction_builder(
                    outer_entries, network.nodes[node_id].pos)
            outer_color = next(e["outer_color"] for e in entries
                               if e.get("shoulder_width", 0.0) > 0)

        if _is_width_taper(entries):
            kind = "taper"
            polygon, edge_lines = taper_builder(entries)
        elif len(entries) == 2:
            kind = "continuation"
            polygon, edge_lines = continuation_builder(entries)
        else:
            kind = "junction"
            polygon, edge_lines = junction_builder(
                entries, network.nodes[node_id].pos)

        mouth_width = math.hypot(entries[0]["left"][0] - entries[0]["right"][0],
                                 entries[0]["left"][1] - entries[0]["right"][1])
        nodes_out.append({"node_id": node_id, "kind": kind,
                          "polygon": polygon, "edge_lines": edge_lines,
                          "mouth_width": mouth_width,
                          "outer_polygon": outer_polygon,
                          "outer_edge_lines": outer_edge_lines,
                          "outer_color": outer_color})

    caps = []
    for node in network.nodes.values():
        roads = [r for r in network.roads_for_node(node.id) if not r.is_preview]
        if len(roads) == 1:
            caps.append({"node_id": node.id, "pos": node.pos,
                         "radius": _profile(roads[0]).total_width() / 2.0})

    return {"trimmed_points": trimmed_points, "nodes": nodes_out, "caps": caps}
