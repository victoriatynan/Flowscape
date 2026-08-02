"""
Engineering STANDARDS the metrics apply -- as plain, swappable data.

Per M1 principle 5 ("standards are configurable implementations, not
architecture"), every number a metric would otherwise hardcode lives here in one
place: per-lane capacity, the V/C -> level-of-service bands, the practical-
capacity threshold a finding keys on, and (Milestone 3) the horizontal stopping
sight distance kinematics and thresholds. Swap this module's tables for an HCM or
an AASHTO/agency profile and the metric/finding CODE does not change.

The shipped values are a deliberately simplified EDUCATIONAL profile (round
numbers, planning-level V/C-based LOS), not an HCM computation. `functional_class`
and `design_speed` are optional on a road (the P1 classification system is not
yet re-applied), so sensible DEFAULTS apply whenever they are absent.
"""

import math

# Per-lane capacity in veh/hr/lane, keyed by functional class. Planning-level,
# one direction, ideal conditions.
CAPACITY_PER_LANE_VPH = {
    "freeway": 2000,
    "highway": 2000,
    "arterial": 1000,
    "collector": 800,
    "local": 600,
}

# Applied when a road has no functional_class yet (pre-P1).
DEFAULT_CAPACITY_PER_LANE_VPH = 800

# Planning-level V/C -> LOS bands, ascending by the ratio's upper bound. A road
# with V/C at or below a band's limit (and above the previous) earns its letter;
# anything above the last finite band is F (at/over capacity).
LOS_BREAKPOINTS = (
    (0.60, "A"),
    (0.70, "B"),
    (0.80, "C"),
    (0.90, "D"),
    (1.00, "E"),
    # > 1.00 -> "F"
)
LOS_OVER_CAPACITY = "F"

# The finding threshold: at or above this V/C a road is "operating above
# practical capacity" (onset of LOS E). Severity then scales with how far over.
PRACTICAL_CAPACITY_VC = 0.90

# The mirror-image threshold: at or BELOW this V/C a road carries so little of
# its capacity that it is a candidate for right-sizing (a road diet -- reclaim a
# lane for parking, transit, or active-travel). A planning-level flag, not a
# mandate. Severity deepens as utilization falls further below it.
EXCESS_CAPACITY_VC = 0.30
EXCESS_CAPACITY_HIGH_VC = 0.15       # far under-utilized -> high severity


def capacity_per_lane_vph(functional_class):
    """Per-lane capacity for a functional class, falling back to the documented
    default when the class is unknown or absent."""
    return CAPACITY_PER_LANE_VPH.get(functional_class,
                                     DEFAULT_CAPACITY_PER_LANE_VPH)


def los_letter(vc):
    """Level-of-service letter for a V/C ratio, or None when V/C is undefined
    (no measured volume)."""
    if vc is None:
        return None
    for limit, letter in LOS_BREAKPOINTS:
        if vc <= limit:
            return letter
    return LOS_OVER_CAPACITY


def excess_capacity_severity(vc):
    """Grade how over-provisioned a road is by its (low) V/C. 'none' at or above
    the excess threshold; low/high below it, mirroring `ssd_severity`'s shape."""
    if vc is None or vc >= EXCESS_CAPACITY_VC:
        return "none"
    if vc <= EXCESS_CAPACITY_HIGH_VC:
        return "high"
    return "low"


# ---------------------------------------------------------------------------
# Horizontal geometry -- stopping sight distance (Milestone 3).
#
# A simplified AASHTO Green Book profile for HORIZONTAL (plan-view) SSD. There is
# no grade term: the 2D world model is flat by definition, so the downgrade
# correction is absent rather than faked with a zero input.
# ---------------------------------------------------------------------------

# Required-SSD kinematics.
PERCEPTION_REACTION_S = 2.5          # driver perception-reaction time, seconds
DECELERATION_FPS2 = 11.2            # comfortable deceleration, ft/s^2
GRAVITY_FPS2 = 32.2                 # for the a/g friction-equivalent term

# Design-speed default (mph) when a road has no design_speed yet (pre-P1), keyed
# by functional class, falling back to a global default -- the graceful-
# degradation twin of DEFAULT_CAPACITY_PER_LANE_VPH.
DESIGN_SPEED_BY_CLASS = {
    "freeway": 65,
    "highway": 55,
    "arterial": 40,
    "collector": 30,
    "local": 25,
}
DEFAULT_DESIGN_SPEED_MPH = 30

# Assumed lateral clearance (ft) from the centerline to the sight obstruction,
# used by the horizontal-sightline relation until a roadside-obstruction model
# lands (Option A). A single swappable stand-in for real roadside geometry.
DEFAULT_LATERAL_CLEARANCE_FT = 10.0

# The AASHTO horizontal-sightline constant, 90/pi: relates a curve's radius,
# middle-ordinate clearance, and available sight distance along the arc.
_HSO_CONST = 90.0 / math.pi          # ~= 28.6479

# SSD-deficiency severity bands, keyed on the deficit RATIO
# (required - available) / required. At/under MODERATE is "low", etc.
SSD_DEFICIT_MODERATE = 0.10
SSD_DEFICIT_HIGH = 0.25


def effective_design_speed(functional_class, design_speed):
    """The design speed (mph) to analyze a road at: its own `design_speed` when
    set, else the class default, else the global default. Mirrors how capacity
    falls back for an absent functional class."""
    if design_speed is not None:
        return design_speed
    return DESIGN_SPEED_BY_CLASS.get(functional_class, DEFAULT_DESIGN_SPEED_MPH)


def required_ssd_ft(design_speed_mph):
    """AASHTO stopping sight distance (ft) for a design speed, plan-view (no
    grade): SSD = 1.47*V*t + V^2 / (30 * (a/g)). All constants above are
    swappable."""
    v = design_speed_mph
    braking_friction = DECELERATION_FPS2 / GRAVITY_FPS2
    return 1.47 * v * PERCEPTION_REACTION_S + (v * v) / (30.0 * braking_friction)


def available_ssd_ft(radius_ft, clearance_ft=None):
    """Available sight distance (ft) along a horizontal curve of `radius_ft`,
    limited by lateral clearance `clearance_ft` to the sight obstruction (AASHTO
    horizontal-sightline relation): S = (R/28.65) * arccos((R - M) / R).

    `clearance_ft` defaults to the module constant, read at CALL time so swapping
    the standard actually takes effect. Returns None for a straight road (radius
    is None) -- curvature does not limit sight there. A clearance at or beyond the
    radius means the whole inside of the curve is clear, so sight is
    unconstrained (None)."""
    if clearance_ft is None:
        clearance_ft = DEFAULT_LATERAL_CLEARANCE_FT
    if radius_ft is None:
        return None
    if clearance_ft >= radius_ft:
        return None                       # obstruction outside the curve -> clear
    ratio = (radius_ft - clearance_ft) / radius_ft   # in (0, 1)
    # AASHTO: S = (R / 28.65) * cos^-1[(R - M) / R], the arccos taken in DEGREES
    # (the 90/pi constant assumes degrees). Equivalent to S = 2R*arccos(ratio).
    return radius_ft / _HSO_CONST * math.degrees(math.acos(ratio))


def ssd_severity(required_ft, available_ft):
    """Grade an SSD shortfall by its deficit ratio. 'none' when sight meets or
    exceeds the requirement; otherwise low/moderate/high by the bands above."""
    if available_ft is None or available_ft >= required_ft:
        return "none"
    deficit = (required_ft - available_ft) / required_ft
    if deficit >= SSD_DEFICIT_HIGH:
        return "high"
    if deficit >= SSD_DEFICIT_MODERATE:
        return "moderate"
    return "low"


# ---------------------------------------------------------------------------
# Horizontal geometry -- curve advisory (safe) speed (Milestone 3).
#
# The AASHTO point-mass relation V = sqrt(15 * R * (e + f)) with R in feet gives
# the maximum speed (mph) a horizontal curve of radius R comfortably supports.
# The 2D world model is flat, so superelevation e is 0 -- documented, not faked,
# exactly as the SSD profile has no grade term. `f` is the side-friction factor.
# ---------------------------------------------------------------------------

SIDE_FRICTION_FACTOR = 0.15          # AASHTO comfortable side friction (low speed)
MAX_SUPERELEVATION = 0.0             # flat 2D model -> no superelevation term

# A curve is worth an advisory when its safe speed falls this many mph or more
# below the road's design speed; the deeper the shortfall, the worse the grade.
ADVISORY_SPEED_MODERATE_MPH = 5.0
ADVISORY_SPEED_HIGH_MPH = 10.0


def curve_advisory_speed_mph(radius_ft):
    """Comfortable curve (advisory) speed, mph, for a horizontal curve of
    `radius_ft`. Returns None for a straight road (radius None) -- no curve, no
    speed limit from curvature. All constants above are swappable."""
    if radius_ft is None:
        return None
    return math.sqrt(15.0 * radius_ft * (MAX_SUPERELEVATION + SIDE_FRICTION_FACTOR))


def advisory_speed_severity(design_speed_mph, advisory_speed_mph):
    """Grade a curve by how far its advisory speed sits below the design speed.
    'none' when the curve comfortably supports the design speed; otherwise
    low/moderate/high by the reduction bands above."""
    if advisory_speed_mph is None or advisory_speed_mph >= design_speed_mph:
        return "none"
    reduction = design_speed_mph - advisory_speed_mph
    if reduction >= ADVISORY_SPEED_HIGH_MPH:
        return "high"
    if reduction >= ADVISORY_SPEED_MODERATE_MPH:
        return "moderate"
    return "low"


# ---------------------------------------------------------------------------
# Access management -- intersection spacing / block length (Milestone 3).
#
# A block (a road bounded by an intersection at each end) shorter than the
# minimum spacing packs conflict points together, hurting both capacity and
# safety. A planning-level minimum; the deeper the shortfall, the worse.
# ---------------------------------------------------------------------------

MIN_INTERSECTION_SPACING_FT = 300.0
SHORT_BLOCK_HIGH_RATIO = 0.50        # under half the minimum -> high severity


def short_block_severity(length_ft):
    """Grade an intersection-bounded block by how far under the minimum spacing
    it falls. 'none' at or above the minimum; low/high below it."""
    if length_ft >= MIN_INTERSECTION_SPACING_FT:
        return "none"
    if length_ft <= MIN_INTERSECTION_SPACING_FT * SHORT_BLOCK_HIGH_RATIO:
        return "high"
    return "low"
