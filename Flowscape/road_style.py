"""
Road Visual Style System.

Strict separation from geometry:
  - road_geometry.py computes the centerline, edges, and surface polygon
    (logical/world space, in feet). UNCHANGED by this module.
  - This module ONLY describes how that geometry is *painted*: lane
    marking lines and decals (arrows/symbols/text). It never feeds back
    into geometry, placement, or the graph.

A road's style is purely cosmetic configuration, stored under the road's
existing free-form `data` dict (e.g. data["style"] = {...}), so it rides
along with map_data.py's save/load without any schema changes (data is
already saved/loaded as an opaque dict).

Nothing here is required for a road to render -- DEFAULT_STYLE is used
whenever a road has no "style" entry.
"""

import math
from dataclasses import dataclass, field, fields, asdict


# ----------------------------------------------------------------------
# Lane markings
# ----------------------------------------------------------------------

MARKING_SOLID = "solid"
MARKING_DASHED = "dashed"
MARKING_DOTTED = "dotted"
MARKING_DOUBLE = "double"
MARKING_NONE = "none"


@dataclass
class LaneMarking:
    """Visual description of a single painted line along the road."""
    style: str = MARKING_NONE          # solid | dashed | dotted | double | none
    color: tuple = (255, 255, 255)
    thickness: float = 1.0             # feet
    dash_length: float = 6.0           # feet (dashed/dotted)
    gap_length: float = 6.0            # feet (dashed/dotted)
    offset: float = 0.0                # feet from centerline (perpendicular)


# ----------------------------------------------------------------------
# Decals (arrows, symbols, text painted on the road surface)
# ----------------------------------------------------------------------

DECAL_ARROW = "arrow"
DECAL_SYMBOL = "symbol"
DECAL_TEXT = "text"


@dataclass
class Decal:
    """
    A single painted element on a road surface.

    - kind: "arrow" | "symbol" | "text"
    - position: 0..1 along the road centerline (matches sampled_points)
    - offset: feet, perpendicular to the centerline (lane placement)
    - rotation_offset: degrees, added on top of the road's local heading
    - scale: visual scale multiplier
    - color / label: rendering details (label used for "text"/"symbol")
    """
    kind: str = DECAL_ARROW
    position: float = 0.5
    offset: float = 0.0
    rotation_offset: float = 0.0
    scale: float = 1.0
    color: tuple = (255, 255, 255)
    label: str = ""


# ----------------------------------------------------------------------
# Road style
# ----------------------------------------------------------------------

@dataclass
class RoadStyle:
    """
    Full visual description of a road. Independent of `Road.width`
    (logical, in feet) -- `lane_width_scale` only affects how lane
    markings are spaced/drawn, never the road polygon.
    """
    lane_width_scale: float = 1.0
    center_marking: LaneMarking = field(
        default_factory=lambda: LaneMarking(style=MARKING_DASHED, color=(255, 255, 255),
                                             thickness=0.5, dash_length=8.0, gap_length=8.0))
    edge_marking: LaneMarking = field(
        default_factory=lambda: LaneMarking(style=MARKING_SOLID, color=(255, 255, 255),
                                             thickness=0.5, offset=0.0))
    decals: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


DEFAULT_STYLE = RoadStyle()


def style_from_dict(d):
    """Build a RoadStyle from a plain dict (e.g. road.data['style']).
    Missing fields fall back to DEFAULT_STYLE's values."""
    if not d:
        return DEFAULT_STYLE
    center = LaneMarking(**d.get("center_marking", {})) if "center_marking" in d else DEFAULT_STYLE.center_marking
    edge = LaneMarking(**d.get("edge_marking", {})) if "edge_marking" in d else DEFAULT_STYLE.edge_marking
    decals = [Decal(**dec) for dec in d.get("decals", [])]
    return RoadStyle(
        lane_width_scale=d.get("lane_width_scale", DEFAULT_STYLE.lane_width_scale),
        center_marking=center,
        edge_marking=edge,
        decals=decals,
    )


def get_road_style(road):
    """Read-only accessor: returns the road's RoadStyle, or DEFAULT_STYLE
    if `road.data` has no "style" entry. Never mutates the road."""
    return style_from_dict(road.data.get("style"))


# ----------------------------------------------------------------------
# Geometry helpers (consume road_geometry output, never recompute it)
# ----------------------------------------------------------------------

def _normalize(dx, dy):
    length = math.hypot(dx, dy)
    if length == 0:
        return (0.0, 0.0)
    return (dx / length, dy / length)


def _tangents(sampled_points):
    """Same approach as road_geometry.compute_tangents, kept local so this
    purely-visual module doesn't need to import internals."""
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


def offset_polyline(sampled_points, offset_ft):
    """Return sampled_points shifted `offset_ft` feet perpendicular to the
    local tangent at each point (positive = left of travel direction)."""
    if offset_ft == 0:
        return list(sampled_points)
    tangents = _tangents(sampled_points)
    out = []
    for (px, py), (tx, ty) in zip(sampled_points, tangents):
        nx, ny = -ty, tx
        out.append((px + nx * offset_ft, py + ny * offset_ft))
    return out


def marking_segments(points, marking):
    """
    Convert a polyline + LaneMarking into a list of (start, end) point
    pairs to stroke. Solid/double -> the whole line (one or two offset
    copies). Dashed/dotted -> alternating on/off runs by arc length.
    "none" -> [].
    """
    if marking.style == MARKING_NONE or len(points) < 2:
        return []

    if marking.style == MARKING_SOLID:
        return [points]

    if marking.style == MARKING_DOUBLE:
        gap = max(marking.thickness * 2.0, 0.5)
        return [offset_polyline(points, gap / 2.0), offset_polyline(points, -gap / 2.0)]

    # Dashed / dotted: walk the polyline by arc length, emitting on/off runs.
    on_length = marking.dash_length if marking.style == MARKING_DASHED else marking.thickness
    off_length = marking.gap_length

    segments = []
    current = []
    dist_in_phase = 0.0
    on = True

    current.append(points[0])
    for i in range(1, len(points)):
        a = points[i - 1]
        b = points[i]
        seg_len = math.hypot(b[0] - a[0], b[1] - a[1])
        remaining = seg_len
        cursor = a
        while remaining > 0:
            phase_len = on_length if on else off_length
            available = phase_len - dist_in_phase
            step = min(available, remaining)
            t = step / seg_len if seg_len > 0 else 0
            nxt = (cursor[0] + (b[0] - cursor[0]) * (step / max(remaining, 1e-9)),
                   cursor[1] + (b[1] - cursor[1]) * (step / max(remaining, 1e-9)))
            if on:
                current.append(nxt)
            dist_in_phase += step
            remaining -= step
            cursor = nxt
            if dist_in_phase >= phase_len - 1e-9:
                if on and len(current) >= 2:
                    segments.append(list(current))
                current = [cursor] if not on else []
                on = not on
                dist_in_phase = 0.0
                if on:
                    current = [cursor]

    if on and len(current) >= 2:
        segments.append(current)

    return segments


# ----------------------------------------------------------------------
# Road profile system
# ----------------------------------------------------------------------
#
# A RoadProfile describes the *full* cross-section of a road -- lanes,
# center/edge markings, shoulders, and an optional median -- in feet.
# `RoadProfile.total_width()` is the real on-screen road width (lanes +
# median + shoulders); the renderer uses this (via compute_road_edges /
# compute_road_polygon from road_geometry, unchanged) to build the actual
# road surface polygon, instead of only drawing the centerline.
#
# Like RoadStyle, a profile is opaque config stored under
# road.data["profile"] -- it never touches the graph or spline geometry.

SHOULDER_NONE = "none"
SHOULDER_MACADAM = "macadam"   # narrow (e.g. 1 ft) gravel/dirt shoulder
SHOULDER_PAVED = "paved"       # wide (e.g. 4 ft) paved shoulder
SHOULDER_SIDEWALK = "sidewalk"  # paved pedestrian sidewalk strip

SHOULDER_COLORS = {
    SHOULDER_MACADAM: (90, 85, 78),
    SHOULDER_PAVED: (140, 140, 145),
    SHOULDER_SIDEWALK: (190, 190, 185),
}
MEDIAN_COLOR = (60, 120, 70)

CENTER_MARKING_PRESETS = {
    "double_yellow": LaneMarking(style=MARKING_DOUBLE, color=(230, 200, 40), thickness=0.33),
    "single_yellow": LaneMarking(style=MARKING_SOLID, color=(230, 200, 40), thickness=0.33),
    "dashed_yellow": LaneMarking(style=MARKING_DASHED, color=(230, 200, 40), thickness=0.33,
                                  dash_length=10.0, gap_length=10.0),
    "none": LaneMarking(style=MARKING_NONE),
}

EDGE_LINE_PRESETS = {
    "solid_white": LaneMarking(style=MARKING_SOLID, color=(255, 255, 255), thickness=0.33),
    "dashed_white": LaneMarking(style=MARKING_DASHED, color=(255, 255, 255), thickness=0.33,
                                 dash_length=6.0, gap_length=6.0),
    "none": LaneMarking(style=MARKING_NONE),
}


# ----------------------------------------------------------------------
# Boundary styles (data-driven lane-marking system)
# ----------------------------------------------------------------------
#
# A road's cross-section is a series of strips (sidewalk, shoulder, lane,
# lane, ...) separated by BOUNDARIES. Each boundary has exactly one style,
# drawn exactly once -- this replaces the old per-lane marking generation
# (which could produce duplicate/overlapping lines as lane counts change).
#
# Boundary style names are plain strings stored in RoadProfile so they can
# be swapped (e.g. DOUBLE_YELLOW -> DASHED_YELLOW) purely as data, with no
# geometry/rendering changes.

BOUNDARY_SOLID_WHITE = "solid_white"
BOUNDARY_DASHED_WHITE = "dashed_white"
BOUNDARY_SOLID_YELLOW = "solid_yellow"
BOUNDARY_DASHED_YELLOW = "dashed_yellow"
BOUNDARY_DOUBLE_YELLOW = "double_yellow"
BOUNDARY_DOUBLE_SOLID_WHITE = "double_solid_white"
BOUNDARY_CURB = "curb"
BOUNDARY_NONE = "none"

BOUNDARY_STYLES = {
    BOUNDARY_SOLID_WHITE: LaneMarking(style=MARKING_SOLID, color=(255, 255, 255), thickness=0.33),
    BOUNDARY_DASHED_WHITE: LaneMarking(style=MARKING_DASHED, color=(255, 255, 255), thickness=0.33,
                                        dash_length=6.0, gap_length=6.0),
    BOUNDARY_SOLID_YELLOW: LaneMarking(style=MARKING_SOLID, color=(230, 200, 40), thickness=0.33),
    BOUNDARY_DASHED_YELLOW: LaneMarking(style=MARKING_DASHED, color=(230, 200, 40), thickness=0.33,
                                         dash_length=10.0, gap_length=10.0),
    BOUNDARY_DOUBLE_YELLOW: LaneMarking(style=MARKING_DOUBLE, color=(230, 200, 40), thickness=0.33),
    BOUNDARY_DOUBLE_SOLID_WHITE: LaneMarking(style=MARKING_DOUBLE, color=(255, 255, 255), thickness=0.33),
    BOUNDARY_CURB: LaneMarking(style=MARKING_SOLID, color=(60, 60, 60), thickness=0.33),
    BOUNDARY_NONE: LaneMarking(style=MARKING_NONE),
    # Internal default for inter-lane separators (same-direction lanes).
    # Not part of the public boundary-style vocabulary above, but selected
    # automatically unless a profile overrides `lane_separator_style`.
    "_lane_separator": LaneMarking(style=MARKING_DASHED, color=(255, 255, 255), thickness=0.25,
                                    dash_length=4.0, gap_length=4.0),
}

# Back-compat aliases: old `center_marking_style` / `edge_line_style` values
# map onto the new boundary-style vocabulary so existing presets/data keep
# rendering identically.
_CENTER_STYLE_ALIASES = {
    "double_yellow": BOUNDARY_DOUBLE_YELLOW,
    "single_yellow": BOUNDARY_SOLID_YELLOW,
    "dashed_yellow": BOUNDARY_DASHED_YELLOW,
    "none": BOUNDARY_NONE,
}
_EDGE_STYLE_ALIASES = {
    "solid_white": BOUNDARY_SOLID_WHITE,
    "dashed_white": BOUNDARY_DASHED_WHITE,
    "none": BOUNDARY_NONE,
}


@dataclass
class RoadProfile:
    """Cross-section configuration for a road, in feet.

    The cross-section is modeled as a series of strips (lanes, median,
    shoulders/sidewalks) separated by boundaries. `lane_count_forward` /
    `lane_count_reverse` default to `lanes_per_direction` when left as
    None, so existing presets/data keep working unchanged.
    """
    lane_width: float = 10.0
    lanes_per_direction: int = 1
    lane_count_forward: int = None
    lane_count_reverse: int = None
    center_marking_style: str = "double_yellow"
    edge_line_style: str = "solid_white"
    center_boundary_style: str = None
    edge_boundary_style: str = None
    lane_separator_style: str = None
    shoulder_type: str = SHOULDER_NONE
    shoulder_width: float = 0.0
    median_width: float = 0.0

    def lanes_forward(self):
        return self.lane_count_forward if self.lane_count_forward is not None else self.lanes_per_direction

    def lanes_reverse(self):
        return self.lane_count_reverse if self.lane_count_reverse is not None else self.lanes_per_direction

    def left_width(self):
        """Distance from the centerline to the left-side carriageway edge
        (median half + left/forward lanes). The centerline itself never
        moves -- only this offset changes when left-side lanes change."""
        return self.median_width / 2.0 + self.lanes_forward() * self.lane_width

    def right_width(self):
        """Distance from the centerline to the right-side carriageway edge
        (median half + right/reverse lanes). Independent of left_width()."""
        return self.median_width / 2.0 + self.lanes_reverse() * self.lane_width

    def carriageway_width(self):
        """Total width of all travel lanes + median, excluding shoulders."""
        return self.left_width() + self.right_width()

    def total_width(self):
        """Full road width: lanes + median + both shoulders."""
        return self.carriageway_width() + 2 * self.shoulder_width


# Future road-category presets. Each only configures RoadProfile fields --
# no geometry/graph/renderer changes are needed to add a new category.
ROAD_PROFILE_PRESETS = {
    "residential": RoadProfile(
        lane_width=10.0, lanes_per_direction=1,
        center_marking_style="single_yellow", edge_line_style="solid_white",
        shoulder_type=SHOULDER_SIDEWALK, shoulder_width=4.0,
    ),
    "urban": RoadProfile(
        lane_width=10.0, lanes_per_direction=1,
        center_marking_style="double_yellow", edge_line_style="solid_white",
        shoulder_type=SHOULDER_MACADAM, shoulder_width=1.0,
    ),
    "highway": RoadProfile(
        lane_width=12.0, lanes_per_direction=2,
        center_marking_style="dashed_yellow", edge_line_style="solid_white",
        shoulder_type=SHOULDER_PAVED, shoulder_width=4.0, median_width=4.0,
    ),
    "industrial": RoadProfile(
        lane_width=11.0, lanes_per_direction=1,
        center_marking_style="double_yellow", edge_line_style="solid_white",
        shoulder_type=SHOULDER_PAVED, shoulder_width=4.0,
    ),
    "expressway": RoadProfile(
        lane_width=12.0, lanes_per_direction=3,
        center_marking_style="none", edge_line_style="solid_white",
        shoulder_type=SHOULDER_PAVED, shoulder_width=4.0, median_width=8.0,
    ),
}

DEFAULT_PROFILE = ROAD_PROFILE_PRESETS["urban"]


def profile_from_dict(d):
    """
    Build a RoadProfile from a plain dict (e.g. road.data['profile']).
    `{"preset": "highway", ...overrides}` starts from a named preset and
    applies any field overrides on top; missing/empty -> DEFAULT_PROFILE.
    """
    if not d:
        return DEFAULT_PROFILE
    base = ROAD_PROFILE_PRESETS.get(d.get("preset"), DEFAULT_PROFILE)
    kwargs = {f.name: getattr(base, f.name) for f in fields(RoadProfile)}
    for key, value in d.items():
        if key != "preset" and key in kwargs:
            kwargs[key] = value
    return RoadProfile(**kwargs)


def get_road_profile(road):
    """Read-only accessor: returns the road's RoadProfile, or
    DEFAULT_PROFILE if road.data has no "profile" entry."""
    return profile_from_dict(road.data.get("profile"))


def profile_markings(profile):
    """
    Return [(LaneMarking, offset_ft), ...] for every BOUNDARY in the
    profile's cross-section, derived purely from the strip layout (lane
    counts, lane width, median) and each boundary's configured style.
    Each boundary is emitted exactly once, regardless of how many lanes
    are on either side -- no per-lane duplication.

    Cross-section, center to edge on each side:
        [median?] [lane separators]* [outer edge]
    """
    markings = []
    half_median = profile.median_width / 2.0

    # Center boundary: only meaningful when there's no median (a median is
    # its own region, drawn by profile_median_region -- its edges aren't
    # painted lane lines).
    if profile.median_width <= 0:
        center_style = profile.center_boundary_style or _CENTER_STYLE_ALIASES.get(
            profile.center_marking_style, profile.center_marking_style)
        center = BOUNDARY_STYLES.get(center_style, BOUNDARY_STYLES[BOUNDARY_NONE])
        if center.style != MARKING_NONE:
            markings.append((center, 0.0))

    edge_style = profile.edge_boundary_style or _EDGE_STYLE_ALIASES.get(
        profile.edge_line_style, profile.edge_line_style)
    edge = BOUNDARY_STYLES.get(edge_style, BOUNDARY_STYLES[BOUNDARY_NONE])

    separator_style = profile.lane_separator_style or "_lane_separator"
    separator = BOUNDARY_STYLES.get(separator_style, BOUNDARY_STYLES["_lane_separator"])

    for sign, lane_count in ((1, profile.lanes_forward()), (-1, profile.lanes_reverse())):
        # Boundaries between adjacent same-direction lanes.
        if separator.style != MARKING_NONE:
            for i in range(1, lane_count):
                offset = sign * (half_median + i * profile.lane_width)
                markings.append((separator, offset))

        # Outer edge boundary (lane/shoulder boundary).
        if edge.style != MARKING_NONE:
            outer = sign * (half_median + lane_count * profile.lane_width)
            markings.append((edge, outer))

    return markings


def profile_shoulder_regions(sampled_points, profile):
    """
    Return [{"polygon": [...], "color": (r,g,b)}, ...] world-space
    polygons for the road's shoulder strips (one per side), or [] if the
    profile has no shoulders.
    """
    if profile.shoulder_type == SHOULDER_NONE or profile.shoulder_width <= 0:
        return []
    color = SHOULDER_COLORS.get(profile.shoulder_type, (120, 120, 120))
    regions = []
    # Each side's shoulder is offset from the centerline by that side's own
    # carriageway width (left_width()/right_width()) -- the centerline
    # itself is never used as a midpoint to derive a shared half-width, so
    # changing one side's lane count never shifts the other side's shoulder.
    for sign, side_width in ((1, profile.left_width()), (-1, profile.right_width())):
        inner = offset_polyline(sampled_points, sign * side_width)
        outer = offset_polyline(sampled_points, sign * (side_width + profile.shoulder_width))
        regions.append({"polygon": inner + list(reversed(outer)), "color": color})
    return regions


def profile_median_region(sampled_points, profile):
    """Return a {"polygon": [...], "color": (r,g,b)} for the profile's
    median strip, or None if median_width <= 0."""
    if profile.median_width <= 0:
        return None
    half = profile.median_width / 2.0
    left = offset_polyline(sampled_points, half)
    right = offset_polyline(sampled_points, -half)
    return {"polygon": left + list(reversed(right)), "color": MEDIAN_COLOR}


def decal_transform(sampled_points, decal):
    """
    Resolve a Decal's world-space position and heading (radians) for the
    given road's sampled centerline points. Returns (pos, angle_radians).
    """
    n = len(sampled_points)
    t = max(0.0, min(1.0, decal.position))
    idx = min(n - 1, int(round(t * (n - 1))))
    px, py = sampled_points[idx]

    tangents = _tangents(sampled_points)
    tx, ty = tangents[idx]
    angle = math.atan2(ty, tx) + math.radians(decal.rotation_offset)

    # Apply perpendicular offset (lane placement).
    nx, ny = -ty, tx
    pos = (px + nx * decal.offset, py + ny * decal.offset)
    return pos, angle
