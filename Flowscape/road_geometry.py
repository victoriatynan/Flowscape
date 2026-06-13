"""
Road Data + Geometry Generation (no rendering, no input handling here).

Design notes:
- Curvature is stored as a single scalar per road: the perpendicular offset
  (in pixels) of a quadratic Bezier control point from the midpoint of the
  straight line between the two endpoint nodes.
- computeRoadGeometry() is the single source of truth for turning
  (start_pos, end_pos, curvature) into sampled points. Both the live preview
  and committed roads call this same function, so they always look identical
  and any future intersection-detection code can rely on it too.
"""

import math
from dataclasses import dataclass, field


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
    """
    Build a closed polygon outlining the road surface: walk the left edge
    start->end, then the right edge end->start. Reversing the right edge
    keeps the outline non-self-intersecting (no "bowtie").
    """
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
