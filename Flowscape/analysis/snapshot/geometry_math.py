"""
Plan-view (horizontal) geometry math -- pure functions over a road's three
quadratic-Bezier control points.

A Flowscape road is a single quadratic Bezier B(t) = (1-t)^2 P0 + 2(1-t)t P1 +
t^2 P2, where P0/P2 are the endpoint node positions and P1 is the control point
(midpoint + curve_offset). From those three points alone the horizontal geometry
is EXACT -- no sampling, no approximation -- so the builder can normalize raw
sim geometry into canonical plan-view facts here, and the values are testable to
the analytic answer.

Coordinates are in FEET already (road_geometry.PIXELS_PER_FOOT == 1.0), so radii
come out in true feet. Everything here is 2D; there is no vertical component by
construction (see ANALYSIS_PLATFORM_M3.md -- Horizontal Geometric Design).

Boundary note: this is the quadratic-Bezier form. If roads ever become
multi-segment polylines, swap these closed forms for a circumradius scan over
the sampled centerline -- the builder is the only caller.
"""

import math
from typing import Optional

# Below this |u x A| the road is effectively straight (control point on the
# chord): curvature is undefined and radius is reported as None (infinite).
_STRAIGHT_EPS = 1e-9


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _cross(a, b):
    """2D scalar cross product a x b."""
    return a[0] * b[1] - a[1] * b[0]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def governing_curve_radius_ft(p0, p1, p2) -> Optional[float]:
    """The GOVERNING (tightest) horizontal radius of curvature along the road,
    in feet, or None when the road is straight.

    For a quadratic Bezier the second derivative is constant, so the numerator
    of curvature |B' x B''| is constant and the radius R(t) = 2|u + tA|^3 /
    |u x A| is minimized wherever |u + tA| is minimized, with

        u = P1 - P0            (initial velocity direction, up to scale)
        A = P0 - 2 P1 + P2     (constant acceleration, up to scale)

    The tightest radius is the governing value an engineer checks against.
    """
    u = _sub(p1, p0)
    a = (p0[0] - 2 * p1[0] + p2[0], p0[1] - 2 * p1[1] + p2[1])

    cross_ua = abs(_cross(u, a))
    if cross_ua < _STRAIGHT_EPS:
        return None                       # straight (or degenerate) -> no curve

    aa = _dot(a, a)
    if aa < _STRAIGHT_EPS:
        return None                       # no curvature vector -> straight
    # t* minimizing |u + tA|, clamped to the road's extent [0, 1].
    t_star = max(0.0, min(1.0, -_dot(u, a) / aa))
    min_speed = math.hypot(u[0] + t_star * a[0], u[1] + t_star * a[1])
    return 2.0 * (min_speed ** 3) / cross_ua


def horizontal_deflection_deg(p0, p1, p2) -> float:
    """Total plan-view deflection angle (degrees): the turn between the road's
    start tangent (P1 - P0) and end tangent (P2 - P1). 0 for a straight road,
    approaching 180 for a hairpin. Always non-negative -- direction of turn is
    not encoded."""
    t_in = _sub(p1, p0)
    t_out = _sub(p2, p1)
    if math.hypot(*t_in) < _STRAIGHT_EPS or math.hypot(*t_out) < _STRAIGHT_EPS:
        return 0.0
    ang = math.atan2(abs(_cross(t_in, t_out)), _dot(t_in, t_out))
    return math.degrees(ang)
