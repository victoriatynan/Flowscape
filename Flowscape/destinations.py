"""
Destination System: the background DATA layer for trip generation.

Strict separation (same philosophy as map_data.py): this module is pure
simulation data + logic. No pygame, no rendering, no input handling. It turns
*buildings on the road network* into *trips* (origin node -> destination node
+ a departure time), which the existing traffic_sim.TrafficSimulation then
turns into vehicles.

Demand model (Phase 1):
  - BuildingType   : shared, reusable archetype. Owns its category, size,
                     vehicle-count RANGE and a daily ACTIVITY PROFILE (a list
                     of Activities, one per part of the day). One per archetype,
                     held in BUILDING_TYPES.
  - Activity        : a thing the building's vehicles do during a part of the
                     day (e.g. "Lunch", "Evening Return"). It carries a
                     departure WINDOW and a set of weighted destination CHOICES.
                     A choice of STAY produces no trip (the vehicle stays put).
  - Building        : a lightweight placed instance that REFERENCES a
                     BuildingType by name (see buildings.Building). It also
                     carries a stable per-placement `seed`; every randomized
                     property (vehicle count, which activity each vehicle does,
                     departure time) is DERIVED from that seed, so a building's
                     behavior is reproducible and only changes when reseeded.

The flow is unchanged: Building -> Trip -> connection node -> spawn vehicle.
A road node never sources trips by itself; only buildings with connection
nodes participate.

What this module deliberately does NOT do yet (later phases): travel-time-aware
departure scheduling (Phase 2), user-facing demand controls / per-category
activity toggles + weights + global multipliers UI (Phase 3). The data model
already leaves room for them (demand_multipliers is wired through here).
"""

from dataclasses import dataclass
import math
import random

# ----------------------------------------------------------------------
# Categories: the top-level land-use groups that shape demand.
# ----------------------------------------------------------------------
RESIDENTIAL = "Residential"
COMMERCIAL = "Commercial"
INDUSTRIAL = "Industrial"
EDUCATION = "Education"
PUBLIC_SERVICES = "Public Services"
RECREATION = "Recreation"

CATEGORIES = (RESIDENTIAL, COMMERCIAL, INDUSTRIAL, EDUCATION,
              PUBLIC_SERVICES, RECREATION)

# ----------------------------------------------------------------------
# Sizes.
# ----------------------------------------------------------------------
SMALL = "Small"
MEDIUM = "Medium"
LARGE = "Large"

# ----------------------------------------------------------------------
# Periods of the day. An activity belongs to one; it is informational (the
# real timing lives in each activity's departure window).
# ----------------------------------------------------------------------
MORNING = "morning"
MIDDAY = "midday"
EVENING = "evening"

# A destination choice of STAY means "no trip": the vehicle stays at the
# building for that activity. Modeled as a None destination category.
STAY = None

# ----------------------------------------------------------------------
# Operating hours per category, 24h decimal (open_hour, close_hour). Kept as
# reference metadata on each BuildingType. Residential is always-on.
# ----------------------------------------------------------------------
CATEGORY_HOURS = {
    RESIDENTIAL: (0.0, 24.0),
    COMMERCIAL: (8.0, 21.0),
    INDUSTRIAL: (6.0, 22.0),
    EDUCATION: (7.0, 16.0),
    PUBLIC_SERVICES: (8.0, 20.0),
    RECREATION: (10.0, 23.0),
}

# ----------------------------------------------------------------------
# Desired-ARRIVAL windows (24h decimal), shared by the default activity
# profiles. Phase 2 semantic change: a window is now when a traveller wants to
# ARRIVE, not when they leave. Each trip draws a random desired arrival in its
# window and the departure is back-computed (arrival - estimated travel +
# jitter), so distant trips leave earlier and traffic spreads naturally.
# ----------------------------------------------------------------------
WORK_WINDOW = (7.0, 9.0)          # desired arrival at work (wide -> commute spreads)
SCHOOL_WINDOW = (7.0, 8.5)        # desired arrival at school
LUNCH_WINDOW = (11.5, 13.0)       # arrive for lunch
EVENING_WINDOW = (16.5, 18.5)     # arrive home in the evening
SCHOOL_OUT_WINDOW = (14.5, 16.0)  # school lets out earlier
LEISURE_WINDOW = (9.0, 19.0)      # errands / weekend trips spread broadly

# ----------------------------------------------------------------------
# Travel-time estimate for departure scheduling (Phase 2). Deliberately NOT the
# lane router: a straight-line distance over an average speed is enough to
# stagger departures (distant trips leave earlier); it does not try to predict
# the real drive time. `departure = desired_arrival - est_travel + jitter`.
# ----------------------------------------------------------------------
AVG_SPEED_FT_PER_HR = 30 * 5280.0   # ~30 mph in feet/hour
MIN_TRAVEL_SIM_HR = 0.02            # floor (~1.2 min) so near trips still spread
DEPART_OFFSET_SIM_HR = 0.12         # +/- ~7 min jitter, desyncs neighbours


# ----------------------------------------------------------------------
# Activity model.
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class DestChoice:
    """One weighted option for an activity: send the vehicle to a building of
    `dest_category`, or STAY (no trip). Weights are relative, not required to
    sum to 1; Phase 3's toggles work by zeroing/redistributing these."""
    dest_category: str   # a category, or STAY (None)
    weight: float


@dataclass(frozen=True)
class Activity:
    """A part of a building type's day. The building's vehicles each pick one
    of `choices` (by weight); non-STAY picks become trips departing at a random
    time within `window`."""
    name: str
    period: str          # MORNING / MIDDAY / EVENING (informational)
    window: tuple        # (lo, hi) 24h decimal departure window
    choices: tuple       # tuple[DestChoice]


def _act(name, period, window, *pairs):
    """Activity from (category_or_STAY, weight) pairs."""
    return Activity(name, period, window,
                    tuple(DestChoice(cat, w) for cat, w in pairs))


# ----------------------------------------------------------------------
# Default activity profiles, per category: (weekday_profile, weekend_profile).
# A profile is a tuple of Activities. An empty profile means "generates no
# trips" (e.g. industry/schools are closed on weekends). These are the
# hardcoded Phase 1 defaults; Phase 3 will let the user toggle/reweight them.
#
# Note on flow balance: Residential floods OUT in the morning (commute); the
# workplace/leisure categories flood BACK to Residential in the evening. That
# keeps the day's traffic two-directional without per-vehicle trip chaining.
# ----------------------------------------------------------------------
CATEGORY_PROFILES = {
    RESIDENTIAL: (
        (  # weekday
            _act("Morning Commute", MORNING, WORK_WINDOW,
                 (COMMERCIAL, 0.45), (INDUSTRIAL, 0.15), (EDUCATION, 0.10),
                 (PUBLIC_SERVICES, 0.10), (STAY, 0.20)),
            _act("Midday Errand", MIDDAY, LEISURE_WINDOW,
                 (COMMERCIAL, 0.15), (RECREATION, 0.10), (STAY, 0.75)),
            _act("Evening Out", EVENING, EVENING_WINDOW,
                 (RECREATION, 0.15), (COMMERCIAL, 0.10), (STAY, 0.75)),
        ),
        (  # weekend
            _act("Weekend Morning", MORNING, LEISURE_WINDOW,
                 (RECREATION, 0.35), (STAY, 0.65)),
            _act("Weekend Shopping", MIDDAY, LEISURE_WINDOW,
                 (COMMERCIAL, 0.40), (RECREATION, 0.20), (STAY, 0.40)),
            _act("Weekend Evening", EVENING, EVENING_WINDOW,
                 (RECREATION, 0.20), (COMMERCIAL, 0.15), (STAY, 0.65)),
        ),
    ),
    COMMERCIAL: (
        (  # weekday
            _act("Lunch", MIDDAY, LUNCH_WINDOW,
                 (COMMERCIAL, 0.40), (RECREATION, 0.15), (STAY, 0.45)),
            _act("Evening Return", EVENING, EVENING_WINDOW,
                 (RESIDENTIAL, 0.90), (STAY, 0.10)),
        ),
        (  # weekend (open, but lighter)
            _act("Weekend Lunch", MIDDAY, LUNCH_WINDOW,
                 (COMMERCIAL, 0.30), (STAY, 0.70)),
            _act("Weekend Return", EVENING, EVENING_WINDOW,
                 (RESIDENTIAL, 0.80), (STAY, 0.20)),
        ),
    ),
    INDUSTRIAL: (
        (  # weekday
            _act("Evening Return", EVENING, EVENING_WINDOW,
                 (RESIDENTIAL, 0.90), (STAY, 0.10)),
        ),
        (),  # weekend: closed
    ),
    EDUCATION: (
        (  # weekday
            _act("Afternoon Return", EVENING, SCHOOL_OUT_WINDOW,
                 (RESIDENTIAL, 0.90), (STAY, 0.10)),
        ),
        (),  # weekend: closed
    ),
    PUBLIC_SERVICES: (
        (  # weekday
            _act("Lunch", MIDDAY, LUNCH_WINDOW,
                 (COMMERCIAL, 0.30), (STAY, 0.70)),
            _act("Evening Return", EVENING, EVENING_WINDOW,
                 (RESIDENTIAL, 0.70), (STAY, 0.30)),
        ),
        (  # weekend: reduced staffing (hospitals etc. stay open)
            _act("Evening Return", EVENING, EVENING_WINDOW,
                 (RESIDENTIAL, 0.50), (STAY, 0.50)),
        ),
    ),
    RECREATION: (
        (  # weekday
            _act("Evening Return", EVENING, EVENING_WINDOW,
                 (RESIDENTIAL, 0.80), (STAY, 0.20)),
        ),
        (  # weekend
            _act("Evening Return", EVENING, EVENING_WINDOW,
                 (RESIDENTIAL, 0.80), (STAY, 0.20)),
        ),
    ),
}


# ----------------------------------------------------------------------
# Building types.
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class BuildingType:
    """Shared, reusable definition of a building archetype. Frozen because a
    type is a constant: instances reference it, they never mutate it.

    `count_range` is the (min, max) number of vehicles a placed building of
    this type sources per day; each placement rolls a stable value inside it
    from its own seed. `weekday_profile` / `weekend_profile` are the activity
    profiles that decide where those vehicles go and when."""
    name: str
    category: str
    size: str
    count_range: tuple          # (min, max) vehicles/day this type sources
    weekday_profile: tuple      # tuple[Activity]
    weekend_profile: tuple      # tuple[Activity]
    open_hour: float            # 24h decimal
    close_hour: float           # 24h decimal

    @property
    def capacity(self):
        """Nominal capacity = top of the vehicle-count range. Used for
        occupancy seeding/caps in the editor (back-compat with the old fixed
        `capacity` field)."""
        return self.count_range[1]


def _bt(name, category, size, count_range):
    """BuildingType with hours + activity profiles seeded from its category."""
    open_hour, close_hour = CATEGORY_HOURS[category]
    weekday, weekend = CATEGORY_PROFILES[category]
    return BuildingType(name, category, size, count_range,
                        weekday, weekend, open_hour, close_hour)


# The catalogue. Grouped by category; count ranges are rough, easily tuned.
BUILDING_TYPES = {
    # Residential
    "Small House":         _bt("Small House",         RESIDENTIAL, SMALL,  (1, 3)),
    "Large House":         _bt("Large House",         RESIDENTIAL, MEDIUM, (2, 5)),
    "Small Apartment":     _bt("Small Apartment",     RESIDENTIAL, MEDIUM, (8, 20)),
    "Large Apartment":     _bt("Large Apartment",     RESIDENTIAL, LARGE,  (25, 60)),
    # Commercial
    "Small Business":      _bt("Small Business",      COMMERCIAL,  SMALL,  (5, 20)),
    "Large Business":      _bt("Large Business",      COMMERCIAL,  LARGE,  (50, 200)),
    "Restaurant":          _bt("Restaurant",          COMMERCIAL,  SMALL,  (10, 40)),
    "Cafe":                _bt("Cafe",                COMMERCIAL,  SMALL,  (5, 20)),
    "Retail":              _bt("Retail",              COMMERCIAL,  MEDIUM, (15, 50)),
    "Supermarket":         _bt("Supermarket",         COMMERCIAL,  LARGE,  (30, 80)),
    "Hotel":               _bt("Hotel",               COMMERCIAL,  LARGE,  (20, 60)),
    # Industrial
    "Factory":             _bt("Factory",             INDUSTRIAL,  LARGE,  (40, 150)),
    "Warehouse":           _bt("Warehouse",           INDUSTRIAL,  MEDIUM, (15, 50)),
    "Distribution Center": _bt("Distribution Center", INDUSTRIAL,  LARGE,  (30, 100)),
    # Education
    "Elementary":          _bt("Elementary",          EDUCATION,   MEDIUM, (10, 40)),
    "High School":         _bt("High School",         EDUCATION,   LARGE,  (20, 80)),
    "University":          _bt("University",          EDUCATION,   LARGE,  (80, 300)),
    # Public Services
    "Hospital":            _bt("Hospital",            PUBLIC_SERVICES, LARGE,  (40, 150)),
    "Police":              _bt("Police",              PUBLIC_SERVICES, SMALL,  (10, 30)),
    "Fire":                _bt("Fire",                PUBLIC_SERVICES, SMALL,  (8, 20)),
    "Government":          _bt("Government",          PUBLIC_SERVICES, MEDIUM, (15, 50)),
    "Library":             _bt("Library",             PUBLIC_SERVICES, SMALL,  (5, 20)),
    # Recreation
    "Park":                _bt("Park",                RECREATION,  MEDIUM, (5, 30)),
    "Sports Complex":      _bt("Sports Complex",      RECREATION,  LARGE,  (20, 80)),
    "Stadium":             _bt("Stadium",             RECREATION,  LARGE,  (50, 250)),
    "Museum":              _bt("Museum",              RECREATION,  MEDIUM, (15, 60)),
    "Theater":             _bt("Theater",             RECREATION,  MEDIUM, (20, 70)),
}

# Canonical picker/palette order for the catalogue (grouped by category).
# Owned here with the catalogue; the editor Building tool and the web API's
# building-types schema both consume it. Excludes the back-compat aliases.
BUILDING_TYPE_ORDER = [
    "Small House", "Large House", "Small Apartment", "Large Apartment",
    "Small Business", "Large Business", "Restaurant", "Cafe", "Retail",
    "Supermarket", "Hotel",
    "Factory", "Warehouse", "Distribution Center",
    "Elementary", "High School", "University",
    "Hospital", "Police", "Fire", "Government", "Library",
    "Park", "Sports Complex", "Stadium", "Museum", "Theater",
]

# Back-compat aliases: maps saved with the old archetype names (and the legacy
# default "House") still resolve to a sensible current type, so old saves and
# defaults keep working without a migration pass.
_TYPE_ALIASES = {
    "House": "Small House",
    "Apartment": "Large Apartment",
    "Small Office": "Small Business",
    "Large Office": "Large Business",
    "Store": "Retail",
    "School": "High School",
}
for _old, _new in _TYPE_ALIASES.items():
    BUILDING_TYPES[_old] = BUILDING_TYPES[_new]


def building_type_of(building):
    """The BuildingType a placed Building instance references (None if its
    type name is unknown)."""
    return BUILDING_TYPES.get(building.building_type)


# Default per-category demand multipliers (Phase 3 will let the user change
# these from the UI). A multiplier scales how many vehicles each building of
# that category sources, without touching the building's own randomized roll.
DEFAULT_DEMAND_MULTIPLIERS = {c: 1.0 for c in CATEGORIES}


# ----------------------------------------------------------------------
# Trip generation.
# ----------------------------------------------------------------------
@dataclass
class Trip:
    """One generated trip: travel from one building's attached node to
    another's. `depart_hour` (24h decimal) is back-computed from `desired_arrival`
    minus `est_travel` plus a small jitter, so distant trips leave earlier. Feed
    (origin_node_id, dest_node_id) into the spawn pipeline. The extra fields
    (activity / desired_arrival / est_travel) are carried for scheduling and
    debugging and don't change the spawn call."""
    origin_node_id: int
    dest_node_id: int
    depart_hour: float
    origin_building_id: int
    dest_building_id: int
    period: str
    activity: str = ""
    desired_arrival: float = 0.0
    est_travel: float = 0.0


def _buildings_by_category(network):
    """Group placed buildings by their type's category. Only buildings that
    are attached to at least one road node can source/sink trips."""
    groups = {c: [] for c in CATEGORIES}
    for b in network.buildings.values():
        if not b.connection_node_ids:
            continue
        bt = BUILDING_TYPES.get(b.building_type)
        if bt is None:
            continue
        groups[bt.category].append(b)
    return groups


def _building_seed(building):
    """The stable RNG seed for a placed building. Buildings carry an explicit
    `seed`; fall back to the id so older instances are still deterministic."""
    seed = getattr(building, "seed", None)
    return building.id if seed is None else seed


def _rng(*parts):
    """A Random seeded from the given parts. random.Random rejects tuples, so
    parts are joined into a single stable string key."""
    return random.Random("|".join(str(p) for p in parts))


def _estimate_travel_hours(origin, dest):
    """Lightweight straight-line travel-time estimate (sim-hours) for departure
    scheduling. NOT the lane router: it only needs to stagger departures so a
    trip far from its destination leaves earlier, not predict real drive time."""
    dist = math.hypot(origin.x - dest.x, origin.y - dest.y)
    return max(MIN_TRAVEL_SIM_HR, dist / AVG_SPEED_FT_PER_HR)


def building_vehicle_count(building, btype=None):
    """How many vehicles this placed building sources per day. Derived ONLY
    from the building's stable seed (NOT the day), so the count is constant
    across days and changes only when the building is reseeded."""
    if btype is None:
        btype = BUILDING_TYPES.get(building.building_type)
    if btype is None:
        return 0
    lo, hi = btype.count_range
    return _rng("count", _building_seed(building)).randint(lo, hi)


def _pick_choice(choices, rng):
    """Weighted pick among an activity's DestChoices."""
    total = sum(c.weight for c in choices)
    if total <= 0:
        return None
    r = rng.uniform(0, total)
    upto = 0.0
    for c in choices:
        upto += c.weight
        if r <= upto:
            return c
    return choices[-1]


def generate_trips(network, day_index=0, weekend=False, limit=None,
                   demand_multipliers=None):
    """Generate one day's trips for every building on `network`.

    Each connected building rolls a stable vehicle count (from its seed), then
    for each activity in its profile distributes those vehicles across the
    activity's weighted destination choices. Non-STAY picks become trips to a
    randomly chosen building of the target category, departing at a random time
    in the activity's window. Returns a list[Trip] sorted by departure time.

    Determinism: every random draw is seeded from (building seed, day_index),
    so a given map replays identically day-to-day while still varying across
    days. `weekend` selects each type's weekday vs weekend activity profile.

    `demand_multipliers` (category -> float) scales each category's per-building
    vehicle count without changing the buildings' randomized characteristics;
    defaults to 1.0 everywhere (Phase 3 UI will drive this).

    `limit`, if given, randomly samples down to that many trips (keeping a
    spread across the day), useful for an on-screen demo where the full,
    realistic trip count would be too many vehicles to watch at once.

    Pure and deterministic. Reads the network read-only; spawns nothing.
    """
    groups = _buildings_by_category(network)
    multipliers = dict(DEFAULT_DEMAND_MULTIPLIERS)
    if demand_multipliers:
        multipliers.update(demand_multipliers)

    trips = []
    for category in CATEGORIES:
        mult = multipliers.get(category, 1.0)
        for origin in groups[category]:
            bt = BUILDING_TYPES.get(origin.building_type)
            if bt is None:
                continue
            profile = bt.weekend_profile if weekend else bt.weekday_profile
            if not profile:
                continue
            count = max(0, round(building_vehicle_count(origin, bt) * mult))
            if count == 0:
                continue
            seed = _building_seed(origin)
            for ai, activity in enumerate(profile):
                rng = _rng("trips", seed, day_index, ai)
                lo, hi = activity.window   # desired-ARRIVAL window
                for _ in range(count):
                    choice = _pick_choice(activity.choices, rng)
                    if choice is None or choice.dest_category is STAY:
                        continue
                    dests = groups.get(choice.dest_category)
                    if not dests:
                        continue
                    dest = rng.choice(dests)
                    if dest is origin:
                        continue  # no zero-length self-trip
                    # Back-compute departure from the desired arrival so distant
                    # trips leave earlier; jitter desyncs neighbouring buildings.
                    desired_arrival = rng.uniform(lo, hi)
                    est_travel = _estimate_travel_hours(origin, dest)
                    offset = rng.uniform(-DEPART_OFFSET_SIM_HR, DEPART_OFFSET_SIM_HR)
                    depart_hour = min(24.0, max(0.0, desired_arrival - est_travel + offset))
                    trips.append(Trip(
                        origin_node_id=rng.choice(origin.connection_node_ids),
                        dest_node_id=rng.choice(dest.connection_node_ids),
                        depart_hour=depart_hour,
                        origin_building_id=origin.id,
                        dest_building_id=dest.id,
                        period=activity.period,
                        activity=activity.name,
                        desired_arrival=desired_arrival,
                        est_travel=est_travel,
                    ))

    if limit is not None and len(trips) > limit:
        trips = _rng("limit", day_index).sample(trips, limit)

    trips.sort(key=lambda t: t.depart_hour)
    return trips
